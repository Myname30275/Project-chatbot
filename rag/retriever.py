"""ค้นคืนชิ้นความรู้ของร้านที่เกี่ยวข้องกับคำถาม (Retrieval ของ RAG)

ใช้ 2 วิธีคู่กัน (hybrid):
- semantic: cosine ระหว่าง embedding ของคำถามกับของแต่ละ chunk (index สร้างไว้ล่วงหน้าที่
  rag/index.json) — จับความหมายได้ เช่น "หมาตัวใหญ่" ↔ "สุนัขใหญ่"
- lexical : TF-IDF แบบ character n-gram (2–3 ตัวอักษร) — ภาษาไทยไม่เว้นวรรคระหว่างคำ จึงตัดเป็น
  n-gram แทนการตัดคำ ไม่ต้องใช้ไลบรารีตัดคำ จับคำเฉพาะได้แม่น เช่น "ต่อมกลิ่น"

คะแนนรวม = 0.7 × semantic + 0.3 × lexical ถ้าใช้ semantic ไม่ได้ (ไม่ได้ตั้ง key, เรียก API ล้ม,
หรือ index ไม่ตรงกับข้อมูลร้านปัจจุบัน) จะใช้ lexical อย่างเดียว — ระบบไม่ล้ม และไม่ใช้ index เก่า
ที่อาจมีราคาผิด
"""

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from config import settings
from rag import embedder
from rag.chunker import Chunk, build_chunks, chunks_hash

logger = logging.getLogger(__name__)

INDEX_PATH = Path(__file__).resolve().parent / "index.json"
SEMANTIC_WEIGHT = 0.7


@dataclass
class Hit:
    chunk: Chunk
    score: float


# ---------- lexical: TF-IDF character n-gram ----------

_STRIP_RE = re.compile(r"[\s\-–—:：,.()\[\]/*#|\"'“”]+")


def _ngrams(text: str) -> Counter:
    t = _STRIP_RE.sub("", text.lower())
    return Counter(t[i : i + n] for n in (2, 3) for i in range(len(t) - n + 1))


class _TfIdf:
    def __init__(self, docs: list[str]):
        grams = [_ngrams(d) for d in docs]
        df = Counter(g for doc in grams for g in doc)
        n = len(docs)
        self.idf = {g: math.log((n + 1) / (c + 1)) + 1 for g, c in df.items()}
        self.vectors = [self._vec(g) for g in grams]

    def _vec(self, grams: Counter) -> dict[str, float]:
        v = {g: tf * self.idf.get(g, 0.0) for g, tf in grams.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def scores(self, query: str) -> list[float]:
        q = self._vec(_ngrams(query))
        return [sum(w * doc.get(g, 0.0) for g, w in q.items()) for doc in self.vectors]


# ---------- retriever ----------


class Retriever:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]] | None):
        self.chunks = chunks
        self.vectors = vectors
        self.lexical = _TfIdf([c.text for c in chunks])

    @property
    def mode(self) -> str:
        return "hybrid" if self.vectors else "lexical"

    async def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        top_k = top_k or settings.RAG_TOP_K
        lex = self.lexical.scores(query)
        scores = lex
        if self.vectors:
            try:
                (q,) = await embedder.embed([query])
                sem = [sum(a * b for a, b in zip(q, v)) for v in self.vectors]
                scores = [SEMANTIC_WEIGHT * s + (1 - SEMANTIC_WEIGHT) * l for s, l in zip(sem, lex)]
            except embedder.EmbeddingError as exc:
                logger.warning("RAG: ใช้ embedding ไม่ได้ ค้นแบบ lexical แทน — %s", exc)
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return [Hit(c, s) for c, s in ranked[:top_k] if s > 0]


def _load_vectors(chunks: list[Chunk]) -> list[list[float]] | None:
    """โหลด index ที่สร้างไว้ — คืน None (ใช้ lexical) ถ้าไม่มีไฟล์ หรือไม่ตรงกับข้อมูลร้าน/ค่าตั้งค่าปัจจุบัน"""
    if not settings.embeddings_enabled:
        logger.info("RAG: ไม่ได้ตั้งค่า embedding — ค้นแบบ lexical อย่างเดียว")
        return None
    if not INDEX_PATH.exists():
        logger.warning("RAG: ไม่พบ %s — รัน `python -m rag.build_index` เพื่อสร้าง", INDEX_PATH.name)
        return None
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    if index.get("hash") != chunks_hash(chunks):
        logger.warning("RAG: index เก่ากว่าข้อมูลใน shop/ — ค้นแบบ lexical จนกว่าจะรัน build_index ใหม่")
        return None
    if index.get("model") != settings.EMBED_MODEL or index.get("dimensions") != settings.EMBED_DIMENSIONS:
        logger.warning("RAG: index สร้างด้วยโมเดล/มิติอื่น — ค้นแบบ lexical จนกว่าจะรัน build_index ใหม่")
        return None
    return index["vectors"]


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        chunks = build_chunks()
        _retriever = Retriever(chunks, _load_vectors(chunks))
        logger.info("RAG: พร้อมใช้ %d chunks (โหมด %s)", len(chunks), _retriever.mode)
    return _retriever


def build_query(history: list[dict[str, str]], message: str) -> str:
    """ต่อคำถามก่อนหน้า 1 ข้อความ ให้คำถามต่อเนื่อง เช่น "แล้วแมวล่ะ" ยังค้นเจอเรื่องเดิม"""
    prev = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
    return f"{prev}\n{message}".strip()


async def retrieve(history: list[dict[str, str]], message: str) -> list[Hit]:
    return await get_retriever().search(build_query(history, message))


def as_context_block(hits: list[Hit]) -> str:
    """จัดรูปแบบชิ้นความรู้ที่ค้นได้ สำหรับส่งให้ LLM เป็น system message"""
    return "\n\n".join(f"[{i}] {h.chunk.title}\n{h.chunk.text}" for i, h in enumerate(hits, 1))


def sources_payload(hits: list[Hit]) -> list[dict]:
    """ข้อมูลอ้างอิงสำหรับส่งให้หน้าเว็บ/เก็บ log (ไม่มีเนื้อหาเต็ม)"""
    return [{"id": h.chunk.id, "title": h.chunk.title, "score": round(h.score, 3)} for h in hits]

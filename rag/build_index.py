"""สร้าง rag/index.json — embedding ของทุกชิ้นความรู้ในร้าน

รันใหม่ทุกครั้งที่แก้ไฟล์ใน shop/ (ถ้าไม่รัน ระบบจะรู้เองว่า index เก่า แล้วค้นแบบ lexical แทน):

    python -m rag.build_index

สร้างไว้ล่วงหน้าแล้ว commit ไฟล์ขึ้น git เพราะบน Vercel แต่ละ instance เริ่มใหม่บ่อย ถ้าสร้างตอน
รันจะเสียเวลาและโควตา API ทุกครั้ง — ตอนรับคำถามจริงจึงเรียก embedding แค่ 1 ครั้งต่อคำถาม
"""

import asyncio
import datetime
import json

from config import settings
from rag import embedder
from rag.chunker import build_chunks, chunks_hash
from rag.retriever import INDEX_PATH


async def main() -> None:
    chunks = build_chunks()
    vectors = await embedder.embed([c.text for c in chunks])
    index = {
        "model": settings.EMBED_MODEL,
        "dimensions": settings.EMBED_DIMENSIONS,
        "hash": chunks_hash(chunks),
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "chunks": [{"id": c.id, "title": c.title, "source": c.source} for c in chunks],
        "vectors": [[round(x, 6) for x in v] for v in vectors],
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    kb = INDEX_PATH.stat().st_size / 1024
    print(f"สร้าง {INDEX_PATH.name} แล้ว: {len(chunks)} chunks, {settings.EMBED_DIMENSIONS} มิติ, {kb:.0f} KB")


if __name__ == "__main__":
    asyncio.run(main())

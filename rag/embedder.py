"""เรียกโมเดล embedding ผ่าน endpoint แบบ OpenAI-compatible (POST {base}/embeddings)

ค่าเริ่มต้นใช้ Gemini (gemini-embedding-001) ด้วย key เดียวกับ Vision จึงไม่ต้องสมัครบริการเพิ่ม
ขอ vector 768 มิติ (โมเดลรองรับถึง 3072) เพื่อให้ไฟล์ index เล็กพอจะ commit และโหลดเร็วบน serverless
"""

import math

import httpx

from chatbot.llm_client import _post_with_retry
from config import settings

_TIMEOUT = httpx.Timeout(connect=5.0, write=10.0, read=30.0, pool=5.0)
_BATCH = 50  # จำนวนข้อความต่อ 1 request


class EmbeddingError(Exception):
    pass


def normalize(vec: list[float]) -> list[float]:
    """ทำให้ยาว 1 — cosine similarity จะเหลือแค่ dot product (และ vector ที่ตัดมิติแล้วต้อง normalize ใหม่)"""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def embed(texts: list[str]) -> list[list[float]]:
    if not settings.embeddings_enabled:
        raise EmbeddingError("ยังไม่ได้ตั้งค่า EMBED_* หรือ VISION_* สำหรับ embedding")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for i in range(0, len(texts), _BATCH):
            payload = {
                "model": settings.EMBED_MODEL,
                "input": texts[i : i + _BATCH],
                "dimensions": settings.EMBED_DIMENSIONS,
            }
            try:
                resp = await _post_with_retry(
                    client,
                    f"{settings.embed_base_url}/embeddings",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.embed_api_key}"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"เรียก embedding ไม่สำเร็จ: {exc}") from exc
            # OpenAI ส่ง "index" มาให้เรียงเอง แต่ Gemini ไม่ส่ง (เรียงตาม input อยู่แล้ว)
            data = resp.json()["data"]
            data = sorted(data, key=lambda d: d.get("index", 0)) if "index" in data[0] else data
            if len(data) != len(payload["input"]):
                raise EmbeddingError(f"ได้ vector {len(data)} ตัว แต่ส่งไป {len(payload['input'])} ข้อความ")
            out += [normalize(d["embedding"]) for d in data]
    return out

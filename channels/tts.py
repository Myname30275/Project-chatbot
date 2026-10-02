"""Cartesia PCM streaming proxy. Credentials stay on the server."""
import logging
import re
import ssl

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import settings
from shop import pricing

router = APIRouter(prefix="/api/v1/tts")
logger = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # เลือกเสียงโคลนจากรายการใน voice.js (เผื่อมีหลายเสียงในอนาคต) — ไม่ส่งมา = ใช้ค่า default ของเซิร์ฟเวอร์
    voice_id: str | None = Field(default=None, max_length=100)


# Cartesia อ่านชื่ออังกฤษ "Hom Hom Grooming" เพี้ยนเมื่ออยู่ในประโยคไทย → เปลี่ยนเป็นชื่อไทยก่อนส่งเสมอ
# (prompt สั่งให้บอทใช้ชื่อไทยอยู่แล้ว ตรงนี้กันกรณีที่บอทยังเขียนเป็นอังกฤษ)
_SHOP_NAME_RE = re.compile(r"hom\s*-?\s*hom(\s*grooming)?", re.IGNORECASE)


def speakable(text: str) -> str:
    name_th = pricing.load_catalog()["shop"].get("name_th") or "หอมหอม กรูมมิ่ง"
    short = name_th.split()[0]
    return _SHOP_NAME_RE.sub(lambda m: name_th if m.group(1) else short, text)


@router.get("/config")
def config():
    return {"enabled": bool(settings.CARTESIA_API_KEY)}


@router.post("/stream")
async def stream(req: SpeechRequest):
    if not settings.CARTESIA_API_KEY:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่า Cartesia")
    if not req.text.strip():
        raise HTTPException(422, "กรุณาใส่ข้อความ")
    text = speakable(req.text)
    language = "th" if any("฀" <= c <= "๿" for c in text) else "en"
    client = httpx.AsyncClient(timeout=30, verify=ssl.create_default_context())
    try:
        response = await client.send(client.build_request(
            "POST", "https://api.cartesia.ai/tts/bytes",
            headers={"Authorization": f"Bearer {settings.CARTESIA_API_KEY}",
                     "Cartesia-Version": "2026-08-14"},
            json={"model_id": settings.CARTESIA_MODEL,
                  "transcript": text,
                  "voice": req.voice_id or settings.CARTESIA_VOICE_ID,
                  "language": language,
                  "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}},
        ), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, "เชื่อมต่อ Cartesia ไม่สำเร็จ") from None
    if not response.is_success:
        status = response.status_code
        body = await response.aread()
        await response.aclose()
        await client.aclose()
        # เก็บ error body จริงจาก Cartesia ไว้ใน log — ตอนก่อนหน้านี้ทิ้งไปเลย ทำให้ debug ไม่ได้ว่า
        # ทำไม request ถึงถูกปฏิเสธ (เช่น ตอนพูดภาษาอังกฤษแล้วมี fallback ไปเสียง browser)
        logger.warning("Cartesia TTS rejected request: HTTP %s body=%r text=%r voice=%r language=%r",
                        status, body[:500], req.text[:200], req.voice_id, language)
        raise HTTPException(502, f"Cartesia ปฏิเสธคำขอ (HTTP {status})")

    async def audio():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(audio(), media_type="application/octet-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

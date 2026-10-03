"""ช่องทาง LINE OA (Messaging API) — แชท + ส่งรูปน้อง/สลิป

ไฟล์นี้ทำแค่รับ/ส่งในรูปแบบของ LINE · การตอบทั้งหมด (guardrails, RAG, LLM, ตัวกันนอกเรื่อง,
บันทึกประวัติ) ใช้ chatbot/assistant.py ตัวเดียวกับหน้าเว็บ · รูปใช้ vision/documents.py ตัวเดียวกัน

- ตรวจลายเซ็น X-Line-Signature (HMAC-SHA256 ด้วย Channel secret) ก่อนทำอะไรทั้งนั้น
- 1 ผู้ใช้ LINE = 1 session (`line:<userId>`) ประวัติจึงแยกตามคนเหมือนเว็บแยกตาม cookie
- ตอบด้วย reply token (ฟรีไม่จำกัด) · ระหว่างรอขึ้นจุด "กำลังพิมพ์" ด้วย loading animation
- ทำงานให้เสร็จก่อนตอบ 200 เพราะ Vercel serverless หยุดโปรเซสทันทีหลังส่ง response
"""

import base64
import hashlib
import hmac
import json
import logging
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from chatbot import assistant, prompt_builder
from chatbot.conversation_store import get_store
from config import settings
from vision import documents
from vision.documents import DocumentError

logger = logging.getLogger(__name__)
router = APIRouter()

API = "https://api.line.me/v2/bot"
DATA_API = "https://api-data.line.me/v2/bot"
MAX_TEXT = 4900  # LINE จำกัด 5000 ตัวอักษรต่อข้อความ
_TIMEOUT = httpx.Timeout(10.0, read=20.0)


def verify_signature(body: bytes, signature: str | None) -> bool:
    if not settings.LINE_CHANNEL_SECRET or not signature:
        return False
    digest = hmac.new(settings.LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def plain_text(markdown: str) -> str:
    """LINE ไม่แสดงมาร์กดาวน์ — ตัดเครื่องหมายที่โมเดลเผลอใส่ (หัวข้อ ตัวหนา ลิสต์แบบ *)"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", markdown)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[*•]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT] or "ขออภัยค่ะ ระบบขัดข้องชั่วคราว รบกวนลองใหม่อีกครั้งนะคะ"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}


async def _reply(client: httpx.AsyncClient, reply_token: str, text: str) -> None:
    r = await client.post(
        f"{API}/message/reply",
        headers=_headers(),
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": plain_text(text)}]},
    )
    if r.status_code != 200:
        logger.warning("LINE reply ไม่สำเร็จ HTTP %s: %s", r.status_code, r.text[:200])


async def _show_loading(client: httpx.AsyncClient, user_id: str, seconds: int = 20) -> None:
    """จุด ... กำลังพิมพ์ในห้องแชท LINE (ไม่สำเร็จก็ไม่เป็นไร)"""
    try:
        await client.post(f"{API}/chat/loading/start", headers=_headers(),
                          json={"chatId": user_id, "loadingSeconds": seconds})
    except httpx.HTTPError:
        pass


async def _handle_text(client, session_id: str, text: str) -> str:
    reply = await assistant.respond(session_id, text, extra_system=prompt_builder.line_hint())
    return reply.text or reply.error or prompt_builder.fallback_message()


async def _handle_image(client, session_id: str, message_id: str) -> str:
    r = await client.get(f"{DATA_API}/message/{message_id}/content", headers=_headers())
    if r.status_code != 200 or not r.content:
        return "ขออภัยค่ะ เปิดรูปไม่สำเร็จ รบกวนส่งรูปใหม่อีกครั้งนะคะ"
    mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
    ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
    try:
        item = await documents.extract(f"line-{message_id}.{ext}", mime, r.content)
    except DocumentError as exc:
        return exc.message
    store = get_store()
    items = await store.get_attachments(session_id)
    await store.set_attachments(session_id, items + [item])
    answer = item.get("meta", {}).get("reply")
    if answer:
        await assistant.record_image_reply(session_id, answer)
        return answer
    return "ได้รับรูปแล้วค่ะ อยากสอบถามอะไรเกี่ยวกับรูปนี้ พิมพ์มาได้เลยนะคะ"


@router.post("/line/webhook")
async def line_webhook(request: Request):
    if not (settings.LINE_CHANNEL_SECRET and settings.LINE_CHANNEL_ACCESS_TOKEN):
        return JSONResponse(status_code=503, content={"error": "LINE ยังไม่ได้ตั้งค่า"})
    body = await request.body()
    if not verify_signature(body, request.headers.get("x-line-signature")):
        logger.warning("LINE webhook ลายเซ็นไม่ถูกต้อง — ปฏิเสธ")
        return JSONResponse(status_code=401, content={"error": "invalid signature"})
    try:
        events = json.loads(body).get("events", [])
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "bad body"})

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for ev in events:
            if ev.get("type") != "message" or not ev.get("replyToken"):
                continue  # follow / unfollow / postback ฯลฯ — ไม่ต้องตอบ
            source = ev.get("source", {})
            user_id = source.get("userId") or source.get("groupId") or "unknown"
            session_id = f"line:{user_id}"
            msg = ev.get("message", {})
            if source.get("userId"):
                await _show_loading(client, source["userId"])
            try:
                if msg.get("type") == "text":
                    answer = await _handle_text(client, session_id, msg.get("text", ""))
                elif msg.get("type") == "image":
                    answer = await _handle_image(client, session_id, msg["id"])
                else:
                    answer = "ตอนนี้น้องหอมอ่านได้แค่ข้อความกับรูปภาพนะคะ ลองพิมพ์คำถามหรือส่งรูปน้องมาได้เลยค่ะ"
            except Exception:  # noqa: BLE001 — ห้าม webhook ล้ม ลูกค้าต้องได้คำตอบเสมอ
                logger.exception("LINE ตอบไม่สำเร็จ session=%s", session_id)
                answer = "ขออภัยค่ะ ระบบขัดข้องชั่วคราว รบกวนลองใหม่อีกครั้ง หรือโทร 02-000-0000 ได้เลยค่ะ"
            await _reply(client, ev["replyToken"], answer)
    return {"ok": True}

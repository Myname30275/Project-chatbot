import json
import logging
import uuid

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import settings
from chatbot import assistant, llm_client, prompt_builder, search
from chatbot.conversation_store import get_store
from chatbot.llm_client import LLMConnectionError
from chatbot.search import SearchError
from vision import documents
from vision.documents import DocumentError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# ไฟล์นี้คือ "ช่องทางหน้าเว็บ" เท่านั้น: session cookie, History, ไฟล์แนบ, แปลง event เป็น SSE
# การตอบคำถามทั้งหมด (guardrails, RAG, LLM, บันทึกประวัติ) อยู่ที่ chatbot/assistant.py
#
# store ใช้ที่นี่สำหรับหน้า History/ไฟล์แนบ — เลือก backend อัตโนมัติจาก env:
# ตั้งค่า Redis/Vercel KV ไว้ = เก็บที่ Redis (จำข้ามรอบ/ข้าม instance ได้จริง),
# ไม่ตั้ง = เก็บในหน่วยความจำ process (พอสำหรับรันในเครื่อง)
store = get_store()

SESSION_COOKIE = "session_id"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 วัน

# ผู้ใช้ฟังคำตอบเป็นเสียง ไม่ได้อ่าน — ตอบยาวๆ มีลิสต์/หัวข้อ ฟังแล้วงงและ (สำหรับเสียงโคลน)
# ต้องรอสังเคราะห์นานขึ้นด้วย ส่ง prompts/voice_hint.txt เป็น system message แยกต่างหาก
# ไม่ปนกับ system prompt หลักของร้าน
# (เคยลองบังคับเพดาน max_tokens ทับสำหรับโหมดเสียงเพื่อกันดีเลย์ — ตัดคำตอบยาวกลาง
# ประโยค ผู้ใช้ไม่เอา จึงเอาออก ไม่จำกัดความยาวคำตอบ; แก้ดีเลย์ด้วยการสตรีม/prefetch
# ฝั่ง voice.js แทน — ดู pumpSpeakQueue())


def _resolve_session(request: Request) -> tuple[str, bool]:
    """คืนค่า (session_id, is_new) — ถ้ามี cookie อยู่แล้วใช้ค่าเดิม ไม่งั้นสร้าง id ใหม่
    ไม่แตะ store ตรงนี้: session ที่ยังไม่มีประวัติจะได้ history ว่างเปล่าเองตอนอ่าน"""
    existing = request.cookies.get(SESSION_COOKIE)
    if existing:
        return existing, False
    return str(uuid.uuid4()), True


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


class ChatRequest(BaseModel):
    message: str
    # ค่าที่ผู้ใช้ปรับในหน้า Settings (ไม่บังคับ) — clamp ในโค้ดก่อนใช้จริง
    temperature: float | None = None
    max_tokens: int | None = None
    # toggle "ค้นเว็บอัตโนมัติ" ในหน้า Settings (ค่าเริ่มต้น = เปิด)
    web_search: bool = True
    # true = ส่งมาจากโหมดสนทนาด้วยเสียง (voice.js) — ให้โมเดลตอบสั้นลง เหมาะกับการฟัง
    voice: bool = False


class ChatResponse(BaseModel):
    reply: str


def _chat_overrides(req: ChatRequest) -> dict:
    """clamp ค่าจาก request ให้อยู่ในกรอบปลอดภัย (ไม่เชื่อ client)"""
    out: dict = {}
    if req.temperature is not None:
        out["temperature"] = min(max(req.temperature, 0.0), 2.0)
    if req.max_tokens is not None:
        out["max_tokens"] = min(max(int(req.max_tokens), 1), 16384)
    if req.voice:
        out["extra_system"] = prompt_builder.voice_hint()
    return out


def _attachment_summary(item: dict) -> dict:
    """ตัด field "text" (ยาว) ออกก่อนส่งให้ frontend — ส่งแค่ metadata พอโชว์ชิป"""
    return {
        "name": item["name"],
        "kind": item["kind"],
        "chars": len(item.get("text", "")),
        "meta": item.get("meta", {}),
    }


def _search_should_try(message: str, want_search: bool, has_attachments: bool) -> bool:
    """เช็คแบบทันที (regex เท่านั้น ไม่เรียก API) ว่าคำถามนี้ 'มีโอกาส' ต้องค้นเว็บไหม
    ใช้ให้ฝั่งสตรีมโชว์สถานะ 'กำลังตรวจสอบข้อมูล…' ได้ทันทีก่อนเริ่มงานหนัก"""
    return bool(
        settings.search_enabled
        and want_search
        and search.maybe_needs_search(message, has_attachments)
    )


async def _search_run(
    session_id: str, history: list[dict], message: str
) -> tuple[list[str], dict | None]:
    """วางแผนคำค้น + ยิง Tavily — คืน (context_blocks, meta)
    เรียกเมื่อ _search_should_try() ผ่านแล้วเท่านั้น · error ถูกกลืนทั้งหมด"""
    try:
        query = await search.plan_query(history, message)
        if not query:
            return [], None
        answer, results = await search.run(query)
    except SearchError as exc:
        logger.warning("ค้นเว็บล้มเหลว session=%s: %s", session_id, exc.message)
        return [], None
    except Exception:  # noqa: BLE001
        logger.exception("ค้นเว็บล้มเหลวโดยไม่คาดคิด session=%s", session_id)
        return [], None
    if not results:
        return [], None
    block = search.as_context_block(query, answer, results)
    return [block], {"query": query, "sources": search.sources_payload(results)}


@router.get("/config")
async def get_config():
    """ค่าเริ่มต้นให้หน้า Settings ตั้ง slider — ไม่หลุด API key"""
    return {
        "temperature": settings.LLM_TEMPERATURE if settings.LLM_TEMPERATURE is not None else 0.7,
        "max_tokens": settings.LLM_MAX_TOKENS or 16384,
        "model": settings.LLM_MODEL,
        "kv": bool(settings.redis_rest_url and settings.redis_rest_token),
        "web_search": settings.search_enabled,
    }


# ---------- ประวัติ / หลายบทสนทนา (History) ----------


@router.get("/history")
async def get_active_history(request: Request, response: Response):
    """ข้อความของบทสนทนาที่ active — frontend เรียกตอนโหลดหน้าเพื่อ render ต่อ"""
    session_id, is_new = _resolve_session(request)
    if is_new:
        _set_session_cookie(response, session_id)
    return {"messages": await store.get_history(session_id)}


@router.get("/conversations")
async def list_conversations(request: Request):
    session_id, _ = _resolve_session(request)
    return {"conversations": await store.list_conversations(session_id)}


@router.post("/conversations")
async def create_conversation(request: Request, response: Response):
    """ปุ่ม "เริ่มแชตใหม่" — สร้างบทสนทนาใหม่ อันเก่ายังอยู่ใน History"""
    session_id, is_new = _resolve_session(request)
    if is_new:
        _set_session_cookie(response, session_id)
    return {"id": await store.new_conversation(session_id)}


@router.post("/conversations/{cid}/activate")
async def switch_conversation(cid: str, request: Request):
    session_id, _ = _resolve_session(request)
    if not await store.activate_conversation(session_id, cid):
        return JSONResponse(status_code=404, content={"error": True, "message": "ไม่พบบทสนทนานี้"})
    items = await store.get_attachments(session_id)
    return {
        "ok": True,
        "messages": await store.get_history(session_id),
        "attachments": [_attachment_summary(it) for it in items],
    }


@router.delete("/conversations/{cid}")
async def remove_conversation(cid: str, request: Request):
    session_id, _ = _resolve_session(request)
    await store.delete_conversation(session_id, cid)
    return {"ok": True, "conversations": await store.list_conversations(session_id)}


@router.get("/models")
async def get_models():
    # เลียนแบบ proxy pattern: ไม่ส่ง API key ออกไปให้ frontend เห็นเด็ดขาด และตอน
    # error ก็ตอบ 200 พร้อม {"error": ...} แทนการโยน HTTPException ตรงๆ
    try:
        models = await llm_client.list_models()
        return {"models": models}
    except LLMConnectionError as exc:
        logger.warning("ไม่สามารถดึงรายชื่อโมเดลได้: %s", exc.message)
        return JSONResponse(status_code=200, content={"error": True, "message": exc.message})


@router.post("/chat/reset")
async def post_chat_reset(request: Request, response: Response):
    """ล้างประวัติบทสนทนา + ไฟล์แนบของ session นี้ โดยไม่ออก session_id ใหม่ —
    เบื้องหลังปุ่ม "เริ่มใหม่" (Usability Heuristic: User Control & Freedom)"""
    session_id, is_new = _resolve_session(request)
    if is_new:
        _set_session_cookie(response, session_id)
    await store.reset(session_id)
    return {"ok": True}


# ---------- ไฟล์แนบ (PDF / รูปภาพ / ข้อความ) ----------

_ALLOWED_HINT = "รองรับ PDF, รูปภาพ (PNG/JPG/WEBP) และไฟล์ข้อความ (TXT/MD/CSV)"


@router.get("/attachments")
async def get_attachments(request: Request):
    session_id, _ = _resolve_session(request)
    items = await store.get_attachments(session_id)
    return {"attachments": [_attachment_summary(it) for it in items]}


@router.post("/attachments")
async def post_attachment(request: Request, response: Response, file: UploadFile = File(...)):
    session_id, is_new = _resolve_session(request)
    if is_new:
        _set_session_cookie(response, session_id)

    if documents.kind_of(file.filename or "", file.content_type) is None:
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": f"ไฟล์ชนิดนี้ยังไม่รองรับ ({_ALLOWED_HINT})"},
        )

    data = await file.read()
    if len(data) > settings.ATTACHMENT_MAX_BYTES:
        mb = settings.ATTACHMENT_MAX_BYTES // (1024 * 1024)
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": f"ไฟล์ใหญ่เกิน {mb} MB"},
        )

    try:
        item = await documents.extract(file.filename or "file", file.content_type, data)
    except DocumentError as exc:
        logger.warning("อ่านไฟล์แนบไม่สำเร็จ session=%s: %s", session_id, exc.message)
        return JSONResponse(status_code=200, content={"error": True, "message": exc.message})
    except Exception as exc:  # noqa: BLE001 — กันทุกกรณีไม่ให้ 500
        logger.exception("อ่านไฟล์แนบล้มเหลวโดยไม่คาดคิด session=%s", session_id)
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}"},
        )

    items = await store.get_attachments(session_id)
    items.append(item)
    await store.set_attachments(session_id, items)

    # รูปสัตว์/สลิป: ระบบตอบลูกค้าทันทีด้วยข้อความที่สร้างจากโค้ด (ราคา/ยอดถูกต้องแน่นอน) และบันทึกลงประวัติ
    reply = item.get("meta", {}).get("reply")
    if reply:
        await assistant.record_image_reply(session_id, reply)
    return {"ok": True, "attachment": _attachment_summary(item), "reply": reply}


@router.delete("/attachments/{index}")
async def delete_attachment(index: int, request: Request):
    session_id, _ = _resolve_session(request)
    items = await store.get_attachments(session_id)
    if 0 <= index < len(items):
        items.pop(index)
        await store.set_attachments(session_id, items)
    return {"ok": True, "attachments": [_attachment_summary(it) for it in items]}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _web_search_blocks(session_id: str, chat_request: ChatRequest) -> list[str]:
    """ค้นเว็บแบบไม่สตรีม (ปิดเป็นค่าเริ่มต้น) — ผลลัพธ์ส่งต่อให้ assistant เป็นบล็อกอ้างอิงเพิ่ม"""
    has_attachments = bool(await assistant.attachment_blocks(session_id))
    if not _search_should_try(chat_request.message, chat_request.web_search, has_attachments):
        return []
    history = await store.get_history(session_id)
    blocks, _meta = await _search_run(session_id, history, chat_request.message)
    return blocks


@router.post("/chat", response_model=ChatResponse)
async def post_chat(chat_request: ChatRequest, request: Request, response: Response):
    session_id, is_new = _resolve_session(request)
    if is_new:
        _set_session_cookie(response, session_id)

    # guardrails + RAG + LLM + บันทึกประวัติ อยู่ใน chatbot/assistant.py ทั้งหมด
    reply = await assistant.respond(
        session_id,
        chat_request.message,
        extra_blocks=await _web_search_blocks(session_id, chat_request),
        **_chat_overrides(chat_request),
    )
    if reply.error and not reply.text:
        return JSONResponse(status_code=502, content={"error": True, "message": reply.error})
    return ChatResponse(reply=reply.text)


@router.post("/chat/stream")
async def post_chat_stream(chat_request: ChatRequest, request: Request):
    session_id, is_new = _resolve_session(request)
    message = chat_request.message
    overrides = _chat_overrides(chat_request)
    has_attachments = bool(await assistant.attachment_blocks(session_id))
    try_search = _search_should_try(message, chat_request.web_search, has_attachments)

    async def event_generator():
        extra_blocks: list[str] = []
        # ค้นเว็บ "ในสตรีม" เพื่อให้ผู้ใช้เห็นสถานะทันที (ไม่ต้องนั่งรอหน้าจอเงียบ
        # ระหว่างวางแผนคำค้น + ยิง Tavily ซึ่งกินเวลาหลายวินาที) — ปิดเป็นค่าเริ่มต้น
        if try_search:
            yield _sse({"search": ""})
            history = await store.get_history(session_id)
            extra_blocks, meta = await _search_run(session_id, history, message)
            if meta:
                yield _sse({"search": meta["query"]})
                yield _sse({"sources": meta["sources"]})
            else:
                # ไม่ได้ค้น (classifier บอก SKIP / ค้นล้มเหลว) — เคลียร์สถานะ
                yield _sse({"search_done": True})

        # guardrails + RAG + LLM + บันทึกประวัติ อยู่ใน chatbot/assistant.py ทั้งหมด
        # event ของ assistant มีรูปแบบเดียวกับ SSE ของหน้าเว็บอยู่แล้ว จึงส่งต่อตรง ๆ
        async for event in assistant.respond_stream(
            session_id, message, extra_blocks=extra_blocks, **overrides
        ):
            yield _sse(event)

    resp = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    if is_new:
        _set_session_cookie(resp, session_id)
    return resp

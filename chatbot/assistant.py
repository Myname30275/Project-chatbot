"""แกนกลางของแชทบอท — ทุกช่องทาง (หน้าแชท, โหมดเสียง) ตอบลูกค้าผ่านฟังก์ชันในไฟล์นี้

ขั้นตอนต่อ 1 ข้อความ:

    ด่าน 1 guardrails (กฎในโค้ด)            ไม่ผ่าน → ปฏิเสธ จบ (ไม่เรียก LLM ไม่บันทึกประวัติ)
    โหลดประวัติ + ไฟล์แนบของ session
    ด่าน 2 guardrails (LLM ตรวจเจตนา) ┐
    RAG ค้นข้อมูลร้าน                 ┘ รันพร้อมกัน    ไม่ผ่าน → ปฏิเสธ จบ
    LLM ตอบ (สตรีม)
    ด่าน 3 guardrails ตรวจทีละประโยค    ไม่ผ่าน → แทนทั้งคำตอบด้วย fallback
    บันทึกประวัติ (เฉพาะคำตอบที่จบสมบูรณ์ และเป็นข้อความที่ลูกค้าเห็นจริง)

ผลลัพธ์เป็นลำดับ event (dict) รูปแบบเดียวกับ SSE ที่หน้าเว็บใช้:
    {"blocked": code}      ข้อความถูกปฏิเสธ (ตามด้วย delta ข้อความปฏิเสธ)
    {"knowledge": [...]}   รายการชิ้นข้อมูลร้านที่ RAG ค้นได้ (ไว้โชว์แหล่งอ้างอิง)
    {"delta": text}        ข้อความที่ผ่านการตรวจแล้ว ส่งให้ลูกค้าได้เลย
    {"replace": text}      คำตอบถูกบล็อกที่ด่าน 3 — แทนข้อความทั้งหมดด้วยค่านี้
    {"error": True, "message": text}
    {"done": True}         จบเสมอด้วย event นี้

ช่องทางที่สตรีมได้ (เว็บ) ใช้ respond_stream() ส่วน /chat (ต้องได้คำตอบเต็มก้อน) ใช้ respond()
"""

import asyncio
import re
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from chatbot import llm_client
from chatbot.conversation_store import get_store
from guardrails import pipeline as guard
from rag import retriever

logger = logging.getLogger(__name__)

store = get_store()


@dataclass
class Reply:
    text: str = ""
    blocked: str | None = None               # รหัสหมวดถ้าถูกปฏิเสธที่ขาเข้า
    replaced: bool = False                   # คำตอบถูกแทนด้วย fallback ที่ขาออก
    error: str | None = None
    sources: list[dict] = field(default_factory=list)


async def attachment_blocks(session_id: str) -> list[str]:
    """ข้อความจากไฟล์แนบทั้งหมดของ session เป็นบล็อก ๆ ให้ LLM ใช้อ้างอิง"""
    return _blocks(await store.get_attachments(session_id))


_SHOP_ANALYSED = {"pet", "slip"}  # รูปที่ระบบของร้านวิเคราะห์เอง (ราคา/ยอดคำนวณด้วยโค้ด)


def _is_shop_analysis(item: dict) -> bool:
    return item.get("meta", {}).get("image_type") in _SHOP_ANALYSED


def _blocks(items: list[dict]) -> list[str]:
    """ไฟล์แนบทั่วไปของลูกค้า (PDF/ข้อความ/รูปอื่น ๆ) — ผลวิเคราะห์รูปสัตว์/สลิปแยกไปอยู่กับข้อมูลร้านแทน"""
    # รูปภาพไม่ส่งชื่อไฟล์ให้โมเดล: ทดสอบจริงแล้วโมเดลเดาชนิดสัตว์จากชื่อไฟล์ (เช่น "Chiwawa.jpg")
    # แทนที่จะใช้ผลวิเคราะห์รูป — ชื่อไฟล์จากมือถือจริง (IMG_1234) ไม่มีความหมายอยู่แล้ว
    return [
        f"[{'รูปที่ลูกค้าส่ง' if it.get('kind') == 'image' else 'ไฟล์: ' + it['name']}]\n{it['text']}"
        for it in items
        if it.get("text") and not _is_shop_analysis(it)
    ]


def _analysis_knowledge(items: list[dict]) -> str | None:
    """ผลวิเคราะห์รูปสัตว์/สลิป วางเป็นชิ้นแรกของ "ข้อมูลร้านที่ค้นได้" — ทดสอบจริงแล้วถ้าส่งแยกเป็น
    ไฟล์แนบ โมเดลเลือกใช้ตารางราคาเต็มจาก RAG แทนราคาที่ระบบคำนวณจากรูปของน้องตัวนั้น"""
    texts = [it["text"] for it in items if it.get("text") and _is_shop_analysis(it)]
    if not texts:
        return None
    # รูปล่าสุดสำคัญสุด (ลูกค้าเพิ่งส่ง) จึงเรียงจากใหม่ไปเก่า
    return "\n\n".join(f"[รูปที่ลูกค้าส่ง] {t}" for t in reversed(texts))


def _slip_amounts(items: list[dict]) -> set[float]:
    """ยอดเงินที่ vision อ่านได้จากสลิปของลูกค้า — ให้ output guard ยอมให้บอททวนตัวเลขนี้ได้"""
    return {it["meta"]["slip_amount"] for it in items if it.get("meta", {}).get("slip_amount") is not None}


# ตารางราคาแยกตามขนาด — ถ้าลูกค้าส่งรูปน้องมาแล้ว ระบบคำนวณราคาของตัวนั้นไว้ให้แล้ว
# ทดสอบจริง: ถ้ายังแนบตารางทุกขนาดไปด้วย Typhoon เลือกไล่ราคาทุกขนาดแทน (แก้ด้วย prompt ไม่หาย)
_SIZED_PRICE_CHUNKS = {"service:bath", "service:full_groom"}


async def _knowledge(
    session_id: str, history: list[dict], message: str, exclude: set[str] = frozenset()
) -> tuple[str | None, list[dict]]:
    """RAG: ค้นชิ้นข้อมูลร้านที่เกี่ยวกับคำถาม — คืน (ข้อความสำหรับ LLM, รายการอ้างอิง)
    error ถูกกลืนทั้งหมด: ค้นไม่ได้ก็ยังตอบต่อได้ (prompt สั่งให้ใช้ fallback ถ้าไม่มีข้อมูล)"""
    try:
        hits = [h for h in await retriever.retrieve(history, message) if h.chunk.id not in exclude]
    except Exception:  # noqa: BLE001
        logger.exception("RAG ล้มเหลวโดยไม่คาดคิด session=%s", session_id)
        return None, []
    sources = retriever.sources_payload(hits)
    logger.info("RAG session=%s hits=%s", session_id, [(s["id"], s["score"]) for s in sources])
    return (retriever.as_context_block(hits) if hits else None), sources


def _user_texts(history: list[dict], message: str) -> list[str]:
    """ข้อความทั้งหมดที่ลูกค้าคนนี้พิมพ์เอง — ให้ output guard ยอมให้บอททวนเบอร์/อีเมลของเจ้าตัวได้"""
    return [m["content"] for m in history if m.get("role") == "user"] + [message]


def _refusal(decision: guard.Decision) -> list[dict]:
    return [{"blocked": decision.code}, {"delta": decision.message}, {"done": True}]


_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(กิโลกรัม|กิโล|กก\.?|kg|กรัม|gram|g\b)", re.IGNORECASE)


def weight_check_note(message: str) -> str | None:
    """น้ำหนักผิดปกติในข้อความลูกค้า (กรัม / < 0.5 กก. / > 100 กก.) → โน้ตให้ LLM ทำตามกฎข้อ 12
    ตรวจด้วยโค้ด ไม่ปล่อยให้ LLM ตัดสินเอง — ทดสอบจริงแล้วบางรอบบอกราคา หรือแต่งกฎว่าร้านไม่รับตัวใหญ่"""
    for m in _WEIGHT_RE.finditer(message or ""):
        value = float(m.group(1).replace(",", "."))
        grams = m.group(2).lower() in ("กรัม", "g", "gram")
        kg = value / 1000 if grams else value
        if grams or kg < 0.5 or kg > 100:
            said = m.group(0).strip()
            # หน่วยกรัมมักพิมพ์ผิดจากกิโลกรัม → เสนอทางเลือกให้ · ค่าอื่นแค่ขอให้ตรวจอีกครั้ง
            ask = (f"น้องหนัก {said} จริงไหมคะ หรือหมายถึง {m.group(1)} กิโลกรัมคะ" if grams and value <= 100
                   else f"น้องหนัก {said} จริงไหมคะ รบกวนตรวจสอบน้ำหนักอีกครั้งนะคะ")
            return (
                f"[ตรวจโดยระบบ] ลูกค้าแจ้งน้ำหนัก {said} ซึ่งผิดปกติ — ทำตาม \"ต้องทำ\" ข้อ 12: "
                f"ถ้ายังไม่เคยถามยืนยันในบทสนทนานี้ ให้ตอบประโยคนี้ตรงตัวเท่านั้น: \"{ask}\" "
                "(ห้ามบอกราคา ห้ามบอกว่าร้านรับหรือไม่รับ) · ถ้าลูกค้ากำลังยืนยันค่าเดิม ให้แนะนำโทรหาร้าน"
            )
    return None


async def respond_stream(
    session_id: str,
    message: str,
    *,
    extra_blocks: list[str] | None = None,
    **llm_overrides,
) -> AsyncGenerator[dict, None]:
    """ตอบ 1 ข้อความแบบสตรีม — llm_overrides ส่งต่อให้ llm_client (temperature, max_tokens, extra_system)"""
    # ด่าน 1: กฎในโค้ด (ถูกและเร็วสุด ทำก่อนแม้แต่โหลดประวัติ)
    decision = guard.check_rules(message, session_id)
    if not decision.allowed:
        for event in _refusal(decision):
            yield event
        return

    history = await store.get_history(session_id)
    attachments = await store.get_attachments(session_id)
    blocks = _blocks(attachments) + (extra_blocks or [])
    from_images = _analysis_knowledge(attachments)
    has_pet_photo = any(it.get("meta", {}).get("image_type") == "pet" for it in attachments)

    # ด่าน 2 (LLM ตรวจเจตนา) + RAG รันพร้อมกัน จึงแทบไม่เพิ่มเวลาตอบ
    decision, (knowledge, sources) = await asyncio.gather(
        guard.check_judge(message, session_id),
        _knowledge(session_id, history, message, _SIZED_PRICE_CHUNKS if has_pet_photo else frozenset()),
    )
    if not decision.allowed:
        for event in _refusal(decision):
            yield event
        return
    yield {"knowledge": sources}
    if from_images:
        knowledge = from_images + ("\n\n" + knowledge if knowledge else "")
    weight_note = weight_check_note(message)
    if weight_note:
        knowledge = weight_note + ("\n\n" + knowledge if knowledge else "")

    # ด่าน 3: ปล่อยคำตอบทีละประโยคที่ตรวจผ่านแล้วเท่านั้น
    out_guard = guard.OutputGuard(_user_texts(history, message), _slip_amounts(attachments))
    shown = ""  # ข้อความที่ลูกค้าเห็นจริง — ใช้บันทึกประวัติ
    completed = False
    llm_stream = llm_client.chat_stream(history, message, blocks, knowledge=knowledge, **llm_overrides)
    try:
        async for event in llm_stream:
            if event["type"] == "delta":
                for sentence in out_guard.feed(event["content"]):
                    shown += sentence
                    yield {"delta": sentence}
                if out_guard.blocked:
                    break
            elif event["type"] == "error":
                logger.error("stream error session=%s: %s", session_id, event["message"])
                yield {"error": True, "message": event["message"]}
            elif event["type"] == "done":
                completed = True

        if completed:
            for sentence in out_guard.flush():
                shown += sentence
                yield {"delta": sentence}
        if out_guard.blocked:
            # ประโยคที่ไม่ผ่านไม่เคยถูกส่งออก — แทนคำตอบทั้งก้อนด้วย fallback
            shown = guard.output_fallback(out_guard.blocked_reason, session_id)
            completed = True
            yield {"replace": shown}
    except Exception as exc:  # noqa: BLE001 — ห้ามให้สตรีมพังกลางทางโดยไม่บอกลูกค้า
        logger.exception("ตอบล้มเหลวโดยไม่คาดคิด session=%s", session_id)
        yield {"error": True, "message": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}"}
        completed = False
    finally:
        await llm_stream.aclose()

    # บันทึกประวัติเฉพาะคำตอบที่จบสมบูรณ์ ถ้าโดนตัดกลางทาง/error จะไม่เก็บคำตอบครึ่ง ๆ
    # กลาง ๆ ไว้เป็น context รอบถัดไป · ถ้าลูกค้ากด "หยุด" สตรีมจะถูกปิดก่อนถึงบรรทัดนี้
    if completed and shown:
        await store.set_history(
            session_id,
            history + [{"role": "user", "content": message}, {"role": "assistant", "content": shown}],
        )
    yield {"done": True}


IMAGE_MARKER = "(ส่งรูปภาพ)"


async def record_image_reply(session_id: str, reply: str) -> None:
    """บันทึกคำตอบจากการวิเคราะห์รูปลงประวัติ เหมือนบอทตอบในแชตจริง — คำถามต่อจากนี้โมเดลแชตจะเห็น
    คำตอบที่ถูกต้องของตัวเองในบทสนทนา (ทดสอบแล้วทำตามได้สม่ำเสมอกว่าอ่านผลวิเคราะห์ดิบ)"""
    history = await store.get_history(session_id)
    await store.set_history(
        session_id,
        history + [{"role": "user", "content": IMAGE_MARKER}, {"role": "assistant", "content": reply}],
    )


async def respond(session_id: str, message: str, **kwargs) -> Reply:
    """ตอบ 1 ข้อความแบบรอคำตอบเต็ม — ผ่านด่านและบันทึกประวัติเหมือน respond_stream ทุกประการ"""
    reply = Reply()
    async for event in respond_stream(session_id, message, **kwargs):
        if "blocked" in event:
            reply.blocked = event["blocked"]
        elif "knowledge" in event:
            reply.sources = event["knowledge"]
        elif "delta" in event:
            reply.text += event["delta"]
        elif "replace" in event:
            reply.text, reply.replaced = event["replace"], True
        elif event.get("error"):
            reply.error = event["message"]
    return reply

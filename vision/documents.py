"""ดึงข้อความจากไฟล์ที่ผู้ใช้แนบ (PDF / รูปภาพ / ข้อความ)

แนวคิด: ไม่ทำ RAG/vector — แปลงไฟล์เป็น "ข้อความ" แล้วให้ router เอาไปยัดใน context
ของโมเดลแชตตรงๆ (ดู chatbot/llm_client.py::_build_payload)

- PDF ที่มีข้อความจริง  -> pymupdf ดึงตรงๆ (ฟรี ไม่เรียก AI)
- PDF หน้าที่เป็นสแกน    -> เรนเดอร์เป็นรูป -> typhoon-ocr
- รูปภาพ                 -> typhoon-ocr (ถอดข้อความ) + Gemini (บรรยายภาพ ถ้าตั้ง VISION_*)
- ข้อความ (txt/md/csv)  -> decode ตรงๆ

typhoon-ocr เรียกผ่าน endpoint OpenAI-compatible เดียวกับแชต (LLM_BASE_URL + LLM_API_KEY)
ต่างกันแค่ชื่อโมเดล ส่วน Gemini เป็นผู้ให้บริการแยก (VISION_BASE_URL + VISION_API_KEY)
"""

import asyncio
import base64
import logging
from typing import Any

import httpx
import pymupdf

from config import settings
from chatbot.llm_client import _post_with_retry

logger = logging.getLogger(__name__)

# OCR/vision ตอบช้ากว่าแชตปกติ (ประมวลผลรูป) ตั้ง read ไว้ยาว
_TIMEOUT = httpx.Timeout(connect=5.0, write=20.0, read=90.0, pool=5.0)

_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
_TEXT_EXT = {"txt", "md", "markdown", "csv", "log", "json"}
_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

# หน้า PDF ที่ดึงข้อความได้น้อยกว่านี้ ถือว่าเป็นสแกน -> ส่งเข้า OCR
_MIN_TEXT_PER_PAGE = 20
_OCR_CONCURRENCY = 2  # typhoon-ocr จำกัด 2 req/วินาที


class DocumentError(Exception):
    """อ่านไฟล์ไม่สำเร็จ — .message เป็นข้อความไทยที่ส่งให้ผู้ใช้เห็นได้เลย"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def kind_of(filename: str, content_type: str | None) -> str | None:
    """คืน 'pdf' | 'image' | 'text' หรือ None ถ้าไม่รองรับ"""
    ext = _ext(filename)
    ct = (content_type or "").lower()
    if ext == "pdf" or ct == "application/pdf":
        return "pdf"
    if ext in _IMAGE_EXT or ct.startswith("image/"):
        return "image"
    if ext in _TEXT_EXT or ct.startswith("text/"):
        return "text"
    return None


async def extract(filename: str, content_type: str | None, data: bytes) -> dict[str, Any]:
    """คืน {"name", "kind", "text", "meta": {...}}  — raise DocumentError ถ้าอ่านไม่ได้"""
    kind = kind_of(filename, content_type)
    if kind is None:
        raise DocumentError("ไฟล์ชนิดนี้ยังไม่รองรับ (รองรับ PDF, รูปภาพ, และไฟล์ข้อความ)")

    if kind == "pdf":
        text, meta = await _extract_pdf(data)
    elif kind == "image":
        text, meta = await _extract_image(data, _IMAGE_MIME.get(_ext(filename), "image/png"))
    else:
        text, meta = _extract_text(data)

    text = text.strip()
    if not text:
        raise DocumentError("อ่านไฟล์นี้ไม่พบข้อความหรือเนื้อหาที่ใช้ได้")

    truncated = False
    limit = settings.ATTACHMENT_CONTEXT_CHAR_LIMIT
    if len(text) > limit:
        text = text[:limit] + "\n\n…(เนื้อหาถูกตัดเพราะยาวเกินกำหนด)"
        truncated = True

    meta["truncated"] = truncated
    return {"name": filename, "kind": kind, "text": text, "meta": meta}


def _extract_text(data: bytes) -> tuple[str, dict[str, Any]]:
    return data.decode("utf-8", "replace"), {"pages": 1, "ocr_pages": 0, "vision_used": False}


async def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pymupdf โยน exception หลายชนิด
        raise DocumentError("เปิดไฟล์ PDF ไม่ได้ (ไฟล์อาจเสียหายหรือมีรหัสผ่าน)") from exc

    with doc:
        if doc.needs_pass:
            raise DocumentError("PDF นี้มีรหัสผ่าน กรุณาปลดรหัสก่อนอัปโหลด")

        total_pages = doc.page_count
        pages = list(range(min(total_pages, settings.ATTACHMENT_MAX_PDF_PAGES)))

        # แยกหน้าเป็น "มีข้อความ" กับ "ต้อง OCR"
        page_text: dict[int, str] = {}
        ocr_targets: list[int] = []
        for i in pages:
            t = doc[i].get_text().strip()
            if len(t) >= _MIN_TEXT_PER_PAGE:
                page_text[i] = t
            else:
                ocr_targets.append(i)

        # เรนเดอร์หน้าที่ต้อง OCR เป็น PNG (ทำใน sync ก่อน แล้วค่อยยิง OCR พร้อมกัน)
        ocr_pngs = {
            i: doc[i].get_pixmap(dpi=150).tobytes("png") for i in ocr_targets
        }

    ocr_results: dict[int, str] = {}
    if ocr_pngs:
        sem = asyncio.Semaphore(_OCR_CONCURRENCY)

        async def run(i: int) -> None:
            async with sem:
                ocr_results[i] = await _ocr(ocr_pngs[i], "image/png")

        await asyncio.gather(*(run(i) for i in ocr_pngs))

    parts: list[str] = []
    for i in pages:
        body = page_text.get(i) or ocr_results.get(i, "")
        if body.strip():
            parts.append(f"[หน้า {i + 1}]\n{body.strip()}")

    note = ""
    if total_pages > len(pages):
        note = f"\n\n…(อ่านเฉพาะ {len(pages)} หน้าแรกจากทั้งหมด {total_pages} หน้า)"

    meta = {
        "pages": len(pages),
        "ocr_pages": len([i for i in ocr_targets if ocr_results.get(i, "").strip()]),
        "vision_used": False,
    }
    return "\n\n".join(parts) + note, meta


async def _extract_image(data: bytes, mime: str) -> tuple[str, dict[str, Any]]:
    tasks = [_ocr(data, mime)]
    if settings.vision_enabled:
        tasks.append(_describe(data, mime))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ocr_text = results[0] if not isinstance(results[0], Exception) else ""
    desc = ""
    vision_used = False
    if settings.vision_enabled:
        if isinstance(results[1], Exception):
            logger.warning("บรรยายภาพ (vision) ล้มเหลว: %s", results[1])
        else:
            desc = results[1]
            vision_used = bool(desc.strip())

    if isinstance(results[0], Exception) and not desc:
        raise DocumentError("อ่านรูปภาพนี้ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")

    blocks = []
    if ocr_text.strip():
        blocks.append(f"ข้อความในรูป:\n{ocr_text.strip()}")
    if desc.strip():
        blocks.append(f"รายละเอียดภาพ:\n{desc.strip()}")
    return "\n\n".join(blocks), {"pages": 1, "ocr_pages": 0, "vision_used": vision_used}


def _data_uri(img_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(img_bytes).decode()}"


async def _vision_call(
    base_url: str, model: str, headers: dict[str, str] | None, prompt: str,
    img_bytes: bytes, mime: str, provider: str,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _data_uri(img_bytes, mime)}},
                ],
            }
        ],
        "max_tokens": 4096,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await _post_with_retry(
                client, f"{base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        logger.error("%s error %s: %s", provider, exc.response.status_code, detail or exc.response.text[:200])
        raise DocumentError(f"บริการ {provider} ตอบกลับด้วยข้อผิดพลาด ({exc.response.status_code})") from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise DocumentError(f"เชื่อมต่อบริการ {provider} ไม่ได้ หรือใช้เวลานานเกินไป") from exc

    data = resp.json()
    choices = data.get("choices", [])
    return choices[0].get("message", {}).get("content", "") if choices else ""


async def _ocr(img_bytes: bytes, mime: str) -> str:
    return await _vision_call(
        settings.LLM_BASE_URL,
        settings.OCR_MODEL,
        None,  # ใช้ Authorization ของ LLM_API_KEY
        "ถอดข้อความที่ปรากฏในภาพนี้ออกมาเป็น markdown รักษาโครงสร้างตาราง หัวข้อ และลำดับให้ครบ "
        "ถอดเฉพาะข้อความที่เห็นจริงเท่านั้น ห้ามแต่งเนื้อหา ตาราง หรือลิงก์รูปขึ้นมาเอง "
        "ถ้าเป็นรูปถ่าย/แผนภูมิ/ไดอะแกรมที่ไม่มีข้อความ ให้ตอบสั้น ๆ ว่า (ไม่มีข้อความ) เท่านั้น",
        img_bytes,
        mime,
        "OCR",
    )


async def _describe(img_bytes: bytes, mime: str) -> str:
    return await _vision_call(
        settings.VISION_BASE_URL,
        settings.VISION_MODEL,
        {"Authorization": f"Bearer {settings.VISION_API_KEY}"},
        "อธิบายภาพนี้อย่างละเอียดเป็นภาษาไทย: วัตถุ/บุคคล/ฉากที่เห็น, ข้อความที่ปรากฏ, "
        "ถ้าเป็นกราฟ/แผนภูมิ/ไดอะแกรม ให้ระบุชนิดและอ่านค่าตัวเลข/แกน/ป้ายกำกับ, สีหลัก, และเลย์เอาต์",
        img_bytes,
        mime,
        "vision",
    )

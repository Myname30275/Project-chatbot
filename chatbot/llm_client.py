import asyncio
import json
import logging
import random
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from chatbot import prompt_builder
from config import settings

logger = logging.getLogger(__name__)

# connect: เวลาผูก TCP handshake, write: เวลาส่ง request, read: เวลารอโทเค็นตอบกลับ
# (ตั้งไว้นานเพราะโมเดลบางตัว โดยเฉพาะที่รันในเครื่องเอง ตอบช้า), pool: เวลารอ
# connection ว่างจาก connection pool
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, write=10.0, read=120.0, pool=5.0)

# สถานะที่ลองใหม่ได้: 429 = โดน rate limit (Typhoon ฟรีจำกัด 5 RPS / 200 RPM),
# 5xx = ฝั่งผู้ให้บริการล่มชั่วคราว
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.0


class LLMConnectionError(Exception):
    """โยนทุกครั้งที่คุยกับผู้ให้บริการ LLM ไม่สำเร็จ พร้อมข้อความภาษาไทยที่ปลอดภัย
    พอจะส่งกลับไปแสดงให้ผู้ใช้เห็นตรงๆ ได้เลย (ไม่หลุด stack trace หรือรายละเอียดภายใน)"""

    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.LLM_API_KEY}"}


def _build_payload(
    history: list[dict[str, str]],
    message: str,
    *,
    stream: bool,
    context_blocks: list[str] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_system: str | None = None,
    knowledge: str | None = None,
) -> dict[str, Any]:
    """ประกอบ payload แบบ Chat Completions มาตรฐาน (messages: [{role, content}])
    เพราะ endpoint นี้เป็น endpoint เดียวที่ Typhoon / LM Studio / OpenRouter รองรับ
    เหมือนกันหมด

    API แบบนี้เป็น stateless คือผู้ให้บริการไม่จำบทสนทนาให้ ต้องส่ง history ทั้งหมด
    ที่คุยกันมาไปพร้อมกับข้อความใหม่ทุกครั้ง (history มาจาก conversation store ฝั่ง
    router ซึ่งเก็บแยกตาม session)

    temperature / max_tokens จะใส่ก็ต่อเมื่อผู้ใช้ตั้งค่าไว้ใน .env เท่านั้น ไม่งั้น
    ปล่อยให้ผู้ให้บริการใช้ค่า default ของตัวเอง

    context_blocks = ข้อความที่ดึงมาจากไฟล์ที่ผู้ใช้แนบ (PDF/รูป) ส่งเป็น system message
    เพิ่มก่อน history เพื่อให้โมเดลตอบโดยอ้างอิงไฟล์ได้ (ดู vision/documents.py)

    extra_system = system message เสริมเฉพาะ request นี้ (เช่น "ตอบสั้นสำหรับโหมดเสียง")
    แยกจาก context_blocks เพราะไม่ใช่เนื้อหาอ้างอิง แต่เป็นคำสั่งปรับพฤติกรรมการตอบ

    knowledge = ชิ้นข้อมูลร้านที่ RAG ค้นได้ตามคำถาม (ดู rag/retriever.py) — แยกจาก context_blocks
    เพราะเป็นข้อมูลทางการของร้าน (เชื่อถือได้) ไม่ใช่ไฟล์ที่ลูกค้าส่งมา (เชื่อถือไม่ได้)
    """
    # system prompt ของร้าน = prompts/chat_system.txt + ข้อมูลหลักใน shop/ (ดู chatbot/prompt_builder.py)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt_builder.system_prompt()}
    ]
    messages.append(
        {
            "role": "system",
            "content": (
                "ข้อมูลร้านที่ค้นได้ (จากคลังความรู้ของร้าน เรียงจากเกี่ยวข้องมากไปน้อย):\n\n" + knowledge
                if knowledge
                else "ข้อมูลร้านที่ค้นได้: (ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้ในคลังความรู้)"
            ),
        }
    )
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    if context_blocks:
        joined = "\n\n---\n\n".join(context_blocks)
        messages.append(
            {
                "role": "system",
                "content": (
                    "ผู้ใช้แนบไฟล์มาด้วย ต่อไปนี้คือเนื้อหาที่ดึงมาจากไฟล์ "
                    "ใช้ประกอบการตอบเมื่อเกี่ยวข้อง และถ้าอ้างอิงให้บอกชื่อไฟล์ด้วย:\n\n"
                    + joined
                ),
            }
        )
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    # ค่าที่ผู้ใช้ปรับในหน้า Settings (ต่อ request) มาก่อนค่า default ใน .env
    temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    mtok = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS

    payload: dict[str, Any] = {"model": settings.LLM_MODEL, "messages": messages}
    if temp is not None:
        payload["temperature"] = temp
    if mtok is not None:
        payload["max_tokens"] = mtok
    if stream:
        payload["stream"] = True
    return payload


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """เวลาหน่วงก่อน retry ครั้งถัดไป: เคารพ header Retry-After ถ้าผู้ให้บริการส่งมา
    ไม่งั้นใช้ exponential backoff + jitter เล็กน้อย กันหลาย request เด้งพร้อมกัน"""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
    return BACKOFF_BASE * (2**attempt) + random.uniform(0, 0.3)


def _friendly_error_from_response(exc: httpx.HTTPStatusError) -> LLMConnectionError:
    # แปลง error code มาตรฐานจาก HTTP ให้เป็นข้อความไทยที่เข้าใจง่าย แทนที่จะโชว์
    # JSON error ดิบๆ จากผู้ให้บริการให้ผู้ใช้เห็น
    status = exc.response.status_code
    try:
        body = exc.response.json()
        detail = body.get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = exc.response.text

    if status == 401:
        message = "เชื่อมต่อไม่สำเร็จ: API key ไม่ถูกต้องหรือหมดอายุ กรุณาตรวจสอบค่า LLM_API_KEY"
    elif status == 400:
        message = f"คำขอไม่ถูกต้อง: {detail}" if detail else "คำขอไม่ถูกต้อง"
    elif status == 404:
        message = f"ไม่พบโมเดลนี้: {detail}" if detail else "ไม่พบโมเดลที่ระบุ กรุณาตรวจสอบค่า LLM_MODEL"
    elif status == 429:
        message = "ถูกจำกัดอัตราการเรียกใช้งาน (rate limit) กรุณาลองใหม่อีกครั้งภายหลัง"
    elif status == 503:
        message = "ผู้ให้บริการ AI ไม่พร้อมให้บริการตอนนี้"
    else:
        message = f"ผู้ให้บริการ AI ตอบกลับด้วยข้อผิดพลาด ({status})"
    return LLMConnectionError(message, status_code=502)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST ที่ลองใหม่อัตโนมัติเมื่อโดน rate limit (429) หรือ 5xx หรือเชื่อมต่อสะดุด
    คืน response ดิบ ให้ผู้เรียกไปทำ raise_for_status() + _friendly_error_from_response() เอง
    headers=None = ใช้ Authorization ของ LLM_API_KEY (ปรับได้เผื่อเรียกผู้ให้บริการอื่น เช่น OCR/vision)"""
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            response = await client.post(
                url, headers=headers or _auth_headers(), json=json
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            if last:
                raise
            await asyncio.sleep(_retry_delay(None, attempt))
            continue

        if response.status_code in RETRYABLE_STATUS and not last:
            delay = _retry_delay(response, attempt)
            logger.warning(
                "LLM ตอบ %s — ลองใหม่ในอีก %.1f วิ (ครั้งที่ %d/%d)",
                response.status_code,
                delay,
                attempt + 1,
                MAX_ATTEMPTS,
            )
            await response.aclose()
            await asyncio.sleep(delay)
            continue

        return response

    raise LLMConnectionError("เรียกผู้ให้บริการ AI ไม่สำเร็จหลังจากลองหลายครั้ง")


async def list_models() -> list[dict[str, Any]]:
    """ดึงรายชื่อโมเดลจาก endpoint /models แบบ OpenAI-compatible

    ผู้ให้บริการบางราย (เช่น Typhoon) ไม่มี endpoint นี้ กรณีนั้นจะ fallback ไปคืน
    โมเดลตัวเดียวที่ตั้งไว้ใน LLM_MODEL แทน เพื่อไม่ให้หน้าเว็บพังทั้งหน้า
    """
    fallback = [
        {"id": settings.LLM_MODEL, "object": "model", "owned_by": "configured"}
    ]
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.get(
                f"{settings.LLM_BASE_URL}/models", headers=_auth_headers()
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError("ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise _friendly_error_from_response(exc) from exc
            if status == 404:
                logger.info("ผู้ให้บริการไม่มี endpoint /models — ใช้รายชื่อจาก LLM_MODEL แทน")
            else:
                logger.warning("ดึง /models ไม่สำเร็จ (%s) — ใช้รายชื่อจาก LLM_MODEL แทน", status)
            return fallback

        # OpenAI-compatible จะคืน {"data": [...]} แต่บางเจ้า (เช่น Typhoon) คืน list ตรงๆ
        body = response.json()
        if isinstance(body, dict):
            models = body.get("data", [])
        elif isinstance(body, list):
            models = body
        else:
            models = []
        return models or fallback


async def chat(
    history: list[dict[str, str]],
    message: str,
    context_blocks: list[str] | None = None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_system: str | None = None,
    knowledge: str | None = None,
) -> str:
    """ส่งข้อความคุยหนึ่งรอบแบบไม่สตรีม คืนค่าข้อความตอบกลับ (reply_text) เพียงอย่างเดียว"""
    payload = _build_payload(
        history,
        message,
        stream=False,
        context_blocks=context_blocks,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_system=extra_system,
        knowledge=knowledge,
    )
    return await _complete(payload)


async def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: httpx.Timeout | None = None,
) -> str:
    """เรียกโมเดลแชตด้วย messages ที่ผู้เรียกประกอบเอง — ไม่แนบ system prompt ของร้าน
    ใช้กับงานเบื้องหลังที่มีคำสั่งของตัวเอง เช่น ตัวตรวจความปลอดภัย (guardrails/judge.py)"""
    payload: dict[str, Any] = {"model": settings.LLM_MODEL, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return await _complete(payload, timeout)


async def _complete(payload: dict[str, Any], timeout: httpx.Timeout | None = None) -> str:
    url = f"{settings.LLM_BASE_URL}/chat/completions"

    async with httpx.AsyncClient(timeout=timeout or REQUEST_TIMEOUT) as client:
        try:
            response = await _post_with_retry(client, url, json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError("ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)") from exc
        except httpx.HTTPStatusError as exc:
            raise _friendly_error_from_response(exc) from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")


async def chat_stream(
    history: list[dict[str, str]],
    message: str,
    context_blocks: list[str] | None = None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_system: str | None = None,
    knowledge: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """สตรีมคำตอบทีละชิ้นตามฟอร์แมต SSE มาตรฐานของ Chat Completions
    ส่งออกเป็น dict รูปแบบ:
    {"type": "delta", "content": str} | {"type": "error", "message": str} | {"type": "done"}

    จะ retry เฉพาะ "ก่อน" เริ่มส่ง delta ตัวแรก (ตอนเปิดสตรีมแล้วโดน 429/5xx หรือ
    เชื่อมต่อสะดุด) — พอเริ่มสตรีมเนื้อหาแล้วจะไม่ retry เพื่อไม่ให้คำตอบซ้ำท่อน
    """
    payload = _build_payload(
        history,
        message,
        stream=True,
        context_blocks=context_blocks,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_system=extra_system,
        knowledge=knowledge,
    )
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    started = False

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for attempt in range(MAX_ATTEMPTS):
                last = attempt == MAX_ATTEMPTS - 1
                try:
                    async with client.stream(
                        "POST", url, headers=_auth_headers(), json=payload
                    ) as response_llm:
                        if (
                            response_llm.status_code in RETRYABLE_STATUS
                            and not last
                        ):
                            await response_llm.aread()
                            delay = _retry_delay(response_llm, attempt)
                            logger.warning(
                                "สตรีม: LLM ตอบ %s — ลองใหม่ในอีก %.1f วิ (ครั้งที่ %d/%d)",
                                response_llm.status_code,
                                delay,
                                attempt + 1,
                                MAX_ATTEMPTS,
                            )
                            await asyncio.sleep(delay)
                            continue

                        if response_llm.status_code >= 400:
                            body = await response_llm.aread()
                            try:
                                detail = json.loads(body).get("error", {}).get("message", "")
                            except (ValueError, AttributeError):
                                detail = body.decode("utf-8", errors="ignore")
                            yield {
                                "type": "error",
                                "message": f"ผู้ให้บริการ AI ตอบกลับด้วยข้อผิดพลาด: {detail or response_llm.status_code}",
                            }
                            return

                        async for line in response_llm.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[len("data:"):].strip()
                            if not raw:
                                continue
                            # สตรีมแบบ OpenAI-compatible จบด้วย "data: [DONE]" ที่ไม่ใช่ JSON
                            if raw == "[DONE]":
                                yield {"type": "done"}
                                return
                            try:
                                event = json.loads(raw)
                            except ValueError:
                                logger.warning("ข้าม SSE data ที่ parse ไม่ได้: %r", raw)
                                continue

                            choices = event.get("choices", [])
                            if not choices:
                                continue
                            content = choices[0].get("delta", {}).get("content")
                            if content:
                                started = True
                                yield {"type": "delta", "content": content}
                        # สตรีมจบปกติ — ผู้ให้บริการบางราย (เช่น Typhoon) ไม่ส่ง "data: [DONE]"
                        # แค่ปิด connection เฉยๆ จึงต้อง yield done เองเมื่อ loop จบ
                        yield {"type": "done"}
                        return
                except (httpx.ConnectError, httpx.TimeoutException):
                    if started or last:
                        raise
                    await asyncio.sleep(_retry_delay(None, attempt))
                    continue
    except httpx.ConnectError:
        yield {
            "type": "error",
            "message": "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง",
        }
    except httpx.TimeoutException:
        yield {"type": "error", "message": "ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)"}
    except httpx.HTTPError as exc:
        logger.exception("ข้อผิดพลาด httpx ที่ไม่คาดคิดระหว่างสตรีม")
        yield {"type": "error", "message": f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {exc}"}
    except Exception as exc:
        logger.exception("ข้อผิดพลาดที่ไม่คาดคิดระหว่างสตรีม")
        yield {"type": "error", "message": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}"}

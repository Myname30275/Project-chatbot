"""ค้นเว็บอัตโนมัติ — เวลาผู้ใช้ถามข้อมูลล่าสุด ให้ไปค้นมาก่อนตอบ

flow (ดู routers/chat.py::_search_context):
1. maybe_needs_search()  — heuristic กรองข้อความที่ชัดว่าไม่ต้องค้นทิ้งก่อน (เร็ว ไม่เรียก API)
2. plan_query()          — เรียก LLM สั้นๆ 1 ครั้งให้ตัดสินใจ + สร้าง search query (หรือ NONE)
3. run()                 — ยิง Tavily
4. as_context_block()    — จัดผลลัพธ์เป็นข้อความแปะใน context ของโมเดลแชต (กลไกเดียวกับไฟล์แนบ)

ทุกจุดออกแบบให้ "ไม่ล้ม": ถ้าค้นไม่ได้ ก็ตอบแบบไม่มีข้อมูลสด
"""

import datetime
import logging
import re
from typing import Any

import httpx

from config import settings
from services import llm_client

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"

# ข้อความที่ไม่ต้องค้นแน่ๆ
_SKIP_RE = re.compile(
    r"^\s*(สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|ขอบคุณ|ขอบใจ|โอเค|ตกลง|ครับ|ค่ะ|hello|hi|hey|thanks|thank you|ok)\b",
    re.IGNORECASE,
)
_CREATIVE_RE = re.compile(
    r"^\s*(เขียน|แต่ง|ช่วยแต่ง|แปล|สรุป|ย่อ|ปรับ|เกลา|แก้|ตรวจ|จัดรูปแบบ|เขียนโค้ด|โค้ด|code|"
    r"write|translate|summari|rewrite|refactor|fix|explain the code)",
    re.IGNORECASE,
)
_MATH_RE = re.compile(r"^[\d\s+\-*/×÷=().,%^]+\??$")

# "สัญญาณ" ที่บอกว่าคำถามอาจต้องใช้ข้อมูลสด — ต้องเจออย่างน้อย 1 อย่างถึงจะพิจารณาค้น
# (ทำให้คำถามทั่วไปตอบจากความรู้ของโมเดลตามปกติ ไม่ค้นทุกครั้ง)
_SIGNAL_RE = re.compile(
    r"("
    r"วันนี้|เมื่อวาน|เมื่อคืน|คืนนี้|ตอนนี้|ขณะนี้|เดี๋ยวนี้|ปัจจุบัน|ล่าสุด|เพิ่ง|พึ่ง|"
    r"สัปดาห์นี้|อาทิตย์นี้|เดือนนี้|ปีนี้|ช่วงนี้|เร็ว ?ๆ ?นี้|"
    r"ข่าว|ราคา|หุ้น|ทองคำ|น้ำมัน|ค่าเงิน|อัตราแลกเปลี่ยน|ดอกเบี้ย|เงินเฟ้อ|คริปโท|bitcoin|"
    r"อากาศ|พยากรณ์|ฝนตก|แผ่นดินไหว|พายุ|น้ำท่วม|"
    r"ผลบอล|ผลการแข่ง|สกอร์|ตารางแข่ง|นัดล่าสุด|"
    r"เลือกตั้ง|นายกรัฐมนตรี|ประธานาธิบดี|รัฐบาล|"
    r"เปิดตัว|ออกใหม่|วางจำหน่าย|วางขาย|อัปเดต|อัพเดท|เวอร์ชัน|รุ่นใหม่|"
    r"ค้นหา|ค้นเว็บ|หาข้อมูล|เสิร์ช|เช็คให้|ตรวจสอบข้อมูล|"
    r"\b25[6-9]\d\b|\b20[2-9]\d\b|"
    r"today|yesterday|tonight|tomorrow|right now|currently|current|latest|recent|nowadays|"
    r"this (week|month|year)|as of|"
    r"news|price|stock|crypto|weather|forecast|score|standings|"
    r"released?|launch(ed|es)?|announce(d|ment)?|update[ds]?|version|newest"
    r")",
    re.IGNORECASE,
)

# คำสุภาพ/คำถามหางประโยคที่ตัดทิ้งได้เวลาจะใช้ข้อความเป็นคำค้นตรงๆ
_POLITE_RE = re.compile(
    r"\s*(หน่อย|ครับ|ค่ะ|คะ|จ้า|ด้วย|บ้าง|ไหม|มั้ย|อ่ะ|อะ|ที|สิ|นะ|\?)+\s*$"
)
_LEAD_RE = re.compile(r"^\s*(ขอ|ขอดู|อยากรู้|อยากทราบ|ช่วย|เช็ค|บอก|แจ้ง)\s*")
# ข้อความที่ 'เป็นคำค้นอยู่แล้ว' — ข้าม plan_query (LLM) ไปค้นเลย ลดดีเลย์ ~3 วิ
_DIRECT_RE = re.compile(
    r"^(ข่าว|ราคา|พยากรณ์อากาศ|สภาพอากาศ|ผลบอล|ผลการแข่งขัน|ผลการแข่ง|ตารางแข่ง|"
    r"อัตราแลกเปลี่ยน|ค่าเงิน)"
)


def _direct_query(message: str) -> str | None:
    """ถ้าข้อความสั้นและขึ้นต้นแบบ 'คำค้น' ชัดเจน คืนคำค้นที่เกลาแล้ว (ข้าม LLM classify)"""
    q = _POLITE_RE.sub("", message.strip())
    q = _LEAD_RE.sub("", q).strip()
    if 4 <= len(q) <= 50 and _DIRECT_RE.match(q):
        return q
    return None


_PLAN_SYSTEM = (
    "หน้าที่ของคุณ: ตัดสินว่า 'คำถามล่าสุด' ต้องเปิดเว็บหาข้อมูลจริงๆ หรือไม่\n"
    "ผู้ช่วยหลักมีความรู้ทั่วไปครบถ้วนอยู่แล้ว (ประวัติศาสตร์ วิทยาศาสตร์ คณิต โปรแกรมมิ่ง "
    "นิยาม วิธีทำ คำแนะนำ การเขียน/แปล/สรุป) — พวกนี้ตอบเองได้ ไม่ต้องค้น\n"
    "ค้นเว็บ 'เฉพาะ' เมื่อคำตอบขึ้นกับข้อมูลที่เปลี่ยนตามเวลา/เพิ่งเกิด และความรู้ถึงต้นปี 2025 "
    "ไม่พอ เช่น ข่าววันนี้ ราคาปัจจุบัน ผลการแข่งล่าสุด สภาพอากาศ ใครดำรงตำแหน่งตอนนี้ "
    "สินค้าที่เพิ่งเปิดตัวหลังปี 2024 เหตุการณ์ปี 2025 เป็นต้นไป\n"
    "รูปแบบคำตอบ (บรรทัดเดียว ห้ามอธิบาย):\n"
    "- ต้องค้น: ขึ้นต้นด้วย 'SEARCH: ' ตามด้วยคำค้นสั้นๆ ภาษาเดียวกับคำถาม\n"
    "- ไม่ต้องค้น: ตอบ 'SKIP' คำเดียว\n"
    "ถ้าไม่แน่ใจ ให้ตอบ SKIP\n"
    "ตัวอย่าง:\n"
    "Q: ข่าว AI วันนี้มีอะไรบ้าง -> SEARCH: ข่าว AI ล่าสุด\n"
    "Q: ราคาทองตอนนี้เท่าไหร่ -> SEARCH: ราคาทองคำวันนี้\n"
    "Q: ตอนนี้ใครเป็นนายกรัฐมนตรีอังกฤษ -> SEARCH: นายกรัฐมนตรีอังกฤษคนปัจจุบัน\n"
    "Q: เมืองหลวงของฝรั่งเศสคือ -> SKIP\n"
    "Q: อธิบาย recursion หน่อย -> SKIP\n"
    "Q: สงครามโลกครั้งที่ 2 จบปีไหน -> SKIP\n"
    "Q: ตอนนี้ฉันควรเรียนภาษาอะไรดี -> SKIP\n"
    "Q: ช่วยเขียนอีเมลลางานให้หน่อย -> SKIP"
)


class SearchError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def maybe_needs_search(message: str, has_attachments: bool) -> bool:
    """เร็ว ไม่เรียก API — ผ่านเฉพาะข้อความที่ 'อาจ' ต้องใช้ข้อมูลสด
    (มีสัญญาณเวลา/ข่าว/ราคา/ปีล่าสุด ฯลฯ) แล้วค่อยให้ plan_query ตัดสินขั้นสุดท้าย
    คำถามทั่วไปจะไม่ผ่านด่านนี้ → ตอบจากความรู้ของโมเดลตามปกติ"""
    if has_attachments:
        return False
    text = message.strip()
    if len(text) < 6:
        return False
    if _SKIP_RE.match(text) or _CREATIVE_RE.match(text) or _MATH_RE.match(text):
        return False
    return bool(_SIGNAL_RE.search(text))


async def plan_query(history: list[dict[str, str]], message: str) -> str | None:
    """ให้โมเดลตัดสินใจ + สร้าง search query — คืน None ถ้าไม่ต้องค้น
    (ถ้าข้อความเป็นคำค้นชัดเจนอยู่แล้ว ข้ามการเรียก LLM ไปเลย)"""
    direct = _direct_query(message)
    if direct:
        return direct
    convo = ""
    for m in history[-4:]:
        who = "ผู้ใช้" if m.get("role") == "user" else "ผู้ช่วย"
        convo += f"{who}: {m.get('content', '')[:200]}\n"
    prompt = f"{convo}คำถามล่าสุด: {message}\n\nSEARCH: <คำค้น>  หรือ  SKIP :"
    try:
        out = await llm_client.chat(
            [{"role": "system", "content": _PLAN_SYSTEM}],
            prompt,
            temperature=0.0,
            max_tokens=24,
        )
    except llm_client.LLMConnectionError as exc:
        logger.warning("plan_query ล้มเหลว: %s", exc.message)
        return None
    except Exception:  # noqa: BLE001 — จัดคำค้นล้มก็แค่ไม่ค้น ไม่ให้แชตพัง
        logger.exception("plan_query ล้มเหลวโดยไม่คาดคิด")
        return None
    first = ((out or "").strip().splitlines() or [""])[0].strip().strip('"').strip()
    # ค้นเฉพาะเมื่อโมเดลตอบตามรูปแบบ "SEARCH: ..." เป๊ะๆ เท่านั้น — อย่างอื่นถือว่าไม่ค้น
    m = re.match(r"^\s*SEARCH\s*[:：]\s*(.+)$", first, re.IGNORECASE)
    if not m:
        return None
    query = m.group(1).strip().strip('"').strip()
    if len(query) < 2 or len(query) > 200 or query.upper() == "SKIP":
        return None
    return query


async def run(query: str) -> tuple[str, list[dict[str, Any]]]:
    """ยิง Tavily — คืน (answer, results[{title,url,content}])"""
    if not settings.SEARCH_API_KEY:
        raise SearchError("ยังไม่ได้ตั้งค่า SEARCH_API_KEY")
    payload = {
        "api_key": settings.SEARCH_API_KEY,
        "query": query,
        "max_results": settings.SEARCH_MAX_RESULTS,
        "search_depth": "basic",
        # include_answer=false — ให้ Tavily ข้ามการสรุปด้วย LLM ของมันเอง (เร็วขึ้น ~1-2 วิ)
        # โมเดลแชตสังเคราะห์คำตอบจาก snippet [1..n] ในบล็อก context ได้อยู่แล้ว
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.SEARCH_TIMEOUT) as client:
            r = await client.post(_TAVILY_URL, json=payload)
            r.raise_for_status()
    except httpx.TimeoutException as exc:
        raise SearchError("ค้นเว็บใช้เวลานานเกินไป") from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            raise SearchError("Tavily API key ไม่ถูกต้องหรือหมดโควตา") from exc
        raise SearchError(f"บริการค้นเว็บตอบกลับด้วยข้อผิดพลาด ({code})") from exc
    except httpx.HTTPError as exc:
        raise SearchError("เชื่อมต่อบริการค้นเว็บไม่ได้") from exc

    data = r.json()
    results = [
        {
            "title": it.get("title", "") or it.get("url", ""),
            "url": it.get("url", ""),
            "content": it.get("content", ""),
        }
        for it in (data.get("results") or [])
        if it.get("url")
    ]
    return data.get("answer") or "", results


def as_context_block(query: str, answer: str, results: list[dict[str, Any]]) -> str:
    today = datetime.date.today().isoformat()
    parts = [f"ผลค้นเว็บ (คำค้น: {query}) — ข้อมูล ณ วันที่ {today}"]
    if answer:
        parts.append(f"\nสรุปเบื้องต้นจากผลค้น: {answer}")
    parts.append("")
    for i, it in enumerate(results, 1):
        parts.append(f"[{i}] {it['title']}\n{it['url']}\n{it['content'][:600].strip()}\n")
    parts.append(
        "ตอบคำถามผู้ใช้โดยอ้างอิงจากผลค้นด้านบน ใส่เลข [n] กำกับหลังข้อความที่อ้างอิงแต่ละแหล่ง "
        "ถ้าผลค้นไม่พอหรือไม่ตรง ให้บอกผู้ใช้ตามตรงว่าข้อมูลอาจไม่อัปเดต"
    )
    return "\n".join(parts)


def sources_payload(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"title": it["title"], "url": it["url"]} for it in results]

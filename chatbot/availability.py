"""ลูกค้าถามคิวว่างในแชท — "มีคิวว่างวันไหนบ้าง" "พรุ่งนี้ว่างไหม" "เสาร์นี้มีคิวไหม"

เจ้าของร้านกำหนด (12 ต.ค. 2569): แชทไม่ไล่รายการเวลาว่างให้ ให้แจ้งลูกค้าว่า "ตรวจสอบคิวได้จากปุ่มจองคิว"
(ปุ่มจองคิวแสดงวันและเวลาที่ว่างจริงตามบริการและจำนวนน้องที่เลือก — รายการเวลาในแชทยาวและไม่ครอบคลุมเท่า)
คำตอบสร้างด้วยโค้ด ไม่ผ่าน LLM (LLM ไม่มีข้อมูลคิว ถ้าปล่อยให้ตอบเองจะเดาหรือคัดลอกเวลาจากคำตอบเก่า)

ยังอ่านวันที่จากข้อความอยู่ เพื่อบอกเรื่องที่ปุ่มจองช่วยไม่ได้: วันที่ผ่านมาแล้ว · เกินช่วงที่เปิดจอง · วันที่ร้านหยุด ·
วันนี้ (จองผ่านเว็บต้องล่วงหน้า) — ไม่ใช่คำถามคิวว่าง = คืน None ให้ LLM ตอบตามปกติ
"""

import logging
import re
from datetime import date, datetime, timedelta

from booking import slots
from chatbot import actions
from shop import pricing

logger = logging.getLogger(__name__)

_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
           "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]

# ---------- ลูกค้าถามคิวว่างหรือเปล่า ----------

_ASK_RE = re.compile(
    r"ว่าง|มีคิว|คิว\s*(เต็ม|เหลือ|ยังมี)|เต็ม\s*(ไหม|มั้ย|ยัง|หรือยัง|รึยัง|แล้วยัง)|จองได้|รับคิว(ได้)?\s*(ไหม|มั้ย)"
    r"|ได้ช่วงไหน|ช่วงไหนได้|กี่โมงได้|ได้กี่โมง|available|free",
    re.IGNORECASE,
)
_OTHER_INTENT_RE = re.compile(r"เลื่อน")  # เช็ค/ยกเลิก/เลื่อนคิวของตัวเอง ไม่ใช่ถามคิวว่าง


def asks_availability(message: str) -> bool:
    text = message or ""
    if actions.CHECK_WORDS.search(text) or actions.CANCEL_WORDS.search(text) or _OTHER_INTENT_RE.search(text):
        return False
    return bool(_ASK_RE.search(text))


# ---------- อ่านวันที่จากข้อความ ----------

_MONTH_STEMS = {
    "ม.ค": 1, "มกรา": 1, "ก.พ": 2, "กุมภา": 2, "มี.ค": 3, "มีนา": 3, "เม.ย": 4, "เมษา": 4,
    "พ.ค": 5, "พฤษภา": 5, "มิ.ย": 6, "มิถุนา": 6, "ก.ค": 7, "กรกฎา": 7, "ส.ค": 8, "สิงหา": 8,
    "ก.ย": 9, "กันยา": 9, "ต.ค": 10, "ตุลา": 10, "พ.ย": 11, "พฤศจิกา": 11, "ธ.ค": 12, "ธันวา": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAY_STEMS = {"จันทร์": 0, "อังคาร": 1, "พุธ": 2, "พฤหัส": 3, "ศุกร์": 4, "เสาร์": 5, "อาทิตย์": 6}
_WEEKDAY_ALT = r"จันทร์|อังคาร|พุธ|พฤหัส(?:บดี)?|ศุกร์|เสาร์|อาทิตย์"

# "15 ต.ค." "15 ตุลาคม 2569" "15 Oct"
_DAY_MONTH_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(" + "|".join(re.escape(k) for k in sorted(_MONTH_STEMS, key=len, reverse=True))
    + r")[ก-๙a-z.]*\s*(\d{4}|\d{2})?(?!\d)",
    re.IGNORECASE,
)
# "15/10" "15/10/2569" "15-10-69" — ขีดกลางต้องมีปีด้วย (กัน "หมา 3-5 กิโล" "9-10 โมง")
_NUMERIC_RE = re.compile(
    r"(?<![\d/.:-])(\d{1,2})\s*(?:/\s*(\d{1,2})(?:\s*/\s*(\d{4}|\d{2}))?|-\s*(\d{1,2})\s*-\s*(\d{4}|\d{2}))(?![\d/:-])"
)
# "วันที่ 15" "เสาร์ที่ 15" (ไม่บอกเดือน)
_DAY_ONLY_RE = re.compile(r"(?:วัน|" + _WEEKDAY_ALT + r")ที่\s*(\d{1,2})(?![\d/:.-])")
_RELATIVE = [
    (re.compile(r"มะรืน"), 2),
    (re.compile(r"พรุ่งนี้|พรุ้งนี้|tomorrow", re.IGNORECASE), 1),
    (re.compile(r"วันนี้|เช้านี้|เที่ยงนี้|บ่ายนี้|เย็นนี้|คืนนี้|today|tonight", re.IGNORECASE), 0),
]
# "ตอนนี้มีคิววันเสาร์ไหม" หมายถึงวันเสาร์ — คำกลุ่มนี้จึงนับเป็น "วันนี้" ก็ต่อเมื่อไม่ได้บอกวันอื่นไว้
_NOW_RE = re.compile(r"ตอนนี้|เดี๋ยวนี้|right now", re.IGNORECASE)
_WEEKDAY_RE = re.compile(r"(วัน)?\s*(" + _WEEKDAY_ALT + r")\s*(นี้|หน้า)?")


def _year(raw: str | None, today: date) -> int | None:
    """ปีที่ลูกค้าพิมพ์ (พ.ศ./ค.ศ. 2 หรือ 4 หลัก) → ค.ศ. · ตัวเลข 2 หลักที่ไม่ใช่ปีนี้/ปีหน้า = ไม่ใช่ปี"""
    if not raw:
        return None
    n = int(raw)
    if len(raw) == 4:
        return n - 543 if n > 2400 else n
    for year in (2500 + n - 543, 2000 + n):
        if today.year <= year <= today.year + 1:
            return year
    return None


def _make(day: int, month: int, year: int | None, today: date) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        d = date(today.year, month, day)
        # ไม่บอกปี: วันที่ผ่านไปนานแล้ว (เช่น ถาม "5 ม.ค." ตอนปลายธันวา) = หมายถึงปีหน้า
        return date(today.year + 1, month, day) if (today - d).days > 180 else d
    except ValueError:
        return None


def requested_day(message: str, today: date) -> date | None:
    """วันที่ลูกค้าพูดถึงในข้อความ — None ถ้าไม่ได้ระบุวัน (หรือระบุวันที่ที่ไม่มีจริง)"""
    text = message or ""

    m = _DAY_MONTH_RE.search(text)
    if m:
        return _make(int(m.group(1)), _MONTH_STEMS[m.group(2).lower()], _year(m.group(3), today), today)

    for m in _NUMERIC_RE.finditer(text):
        month, year = (m.group(2), m.group(3)) if m.group(2) else (m.group(4), m.group(5))
        d = _make(int(m.group(1)), int(month), _year(year, today), today) if 1 <= int(month) <= 12 else None
        if d:
            return d

    m = _DAY_ONLY_RE.search(text)
    if m:
        day = int(m.group(1))
        # ไม่บอกเดือน: วันที่ยังไม่ถึงในเดือนนี้ = เดือนนี้ · เลยมาแล้ว = เดือนหน้า
        first = today.replace(day=1) if day >= today.day else (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return _make(day, first.month, first.year, today)

    for pattern, offset in _RELATIVE:
        if pattern.search(text):
            return today + timedelta(days=offset)

    for m in _WEEKDAY_RE.finditer(text):
        name = m.group(2)[:5] if m.group(2).startswith("พฤหัส") else m.group(2)
        # "อาทิตย์นี้/อาทิตย์หน้า" แปลว่าสัปดาห์ — นับเป็นวันอาทิตย์เฉพาะเมื่อมีคำว่า "วัน" นำหน้า
        if name == "อาทิตย์" and not m.group(1):
            continue
        weekday = _WEEKDAY_STEMS[name]
        if m.group(3) == "หน้า":
            return today - timedelta(days=today.weekday()) + timedelta(days=7 + weekday)
        return today + timedelta(days=(weekday - today.weekday()) % 7)

    return today if _NOW_RE.search(text) else None


def is_day_question(message: str) -> bool:
    """ข้อความนี้จะถูกตอบด้วยคำตอบสำเร็จรูปเรื่องคิวว่าง — ช่องทางเว็บใช้ข้ามการค้นเว็บ
    เพราะคำว่า "วันนี้/พรุ่งนี้" ไปตรงกับสัญญาณ "ข้อมูลสด" ของ chatbot/search.py"""
    return asks_availability(message)


# ---------- สร้างคำตอบ ----------


def full_label(d: date) -> str:
    """เช่น "วันเสาร์ที่ 10 ตุลาคม 2569" — เขียนเต็มไม่ใช้ตัวย่อ ให้โหมดเสียงอ่านออกเสียงได้ถูก"""
    return f"วัน{_WEEKDAYS[d.weekday()]}ที่ {d.day} {_MONTHS[d.month - 1]} {d.year + 543}"


def _see_booking_button(channel: str) -> str:
    """ประโยคหลัก: ให้ดูคิวว่างจากปุ่มจองคิว (หน้าเว็บมีปุ่มใต้คำตอบ · LINE ไม่มีปุ่ม ส่งลิงก์แทน)"""
    if channel == "line":
        from config import settings

        return (f"ตรวจสอบคิวว่างได้ที่ {settings.PUBLIC_SITE_URL.rstrip('/')} ค่ะ "
                "กดปุ่มจองคิว เลือกบริการ แล้วจะเห็นวันและเวลาที่ว่างทั้งหมดค่ะ")
    if channel == "voice":
        return "ตรวจสอบคิวว่างได้จากปุ่มจองคิวที่ขึ้นบนหน้าจอเลยค่ะ เลือกบริการแล้วจะเห็นวันและเวลาที่ว่างทั้งหมดค่ะ"
    return 'ตรวจสอบคิวว่างได้จากปุ่ม "จองคิว" ด้านล่างเลยค่ะ เลือกบริการแล้วจะเห็นวันและเวลาที่ว่างทั้งหมดค่ะ'


async def reply(message: str, channel: str = "web", at: datetime | None = None) -> str | None:
    """คำตอบเมื่อลูกค้าถามคิวว่าง — None ถ้าข้อความนี้ไม่ได้ถามคิวว่าง"""
    if not asks_availability(message):
        return None
    at = (at or slots.now()).astimezone(slots.TZ)
    today = at.date()
    pointer = _see_booking_button(channel)
    day = requested_day(message, today)
    if day is None:
        return pointer

    cfg = slots.config()
    shop = pricing.load_catalog()["shop"]
    label = full_label(day)
    bookable = slots.bookable_days(at)
    sep = " " if channel == "voice" else "\n"

    if day < today:
        return f"{label} ผ่านมาแล้วค่ะ{sep}{pointer}"
    if bookable and day > bookable[-1]:
        return (f"ร้านเปิดให้จองล่วงหน้าได้ไม่เกิน {cfg['max_days_ahead']} วันค่ะ "
                f"ตอนนี้จองได้ถึง{full_label(bookable[-1])}{sep}{pointer}")
    if not slots.day_slots(day):
        return f"{label} ร้านหยุดค่ะ ({shop['hours']}){sep}{pointer}"
    if day not in bookable:
        # วันนี้ (หรือวันที่ใกล้กว่า min_days_ahead): ปุ่มจองไม่มีวันนี้ให้เลือก ต้องโทรถามร้าน
        when = "วันนี้" if day == today else label
        return (f"การจองผ่านเว็บต้องจองล่วงหน้าอย่างน้อย {cfg['min_days_ahead']} วันค่ะ "
                f"ถ้าจะมา{when} รบกวนโทร {shop['contacts']['phone']} สอบถามคิวกับร้านก่อนนะคะ{sep}"
                f"ส่วนคิววันถัดไป {pointer}")
    return pointer

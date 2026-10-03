"""ประกอบ system prompt จากไฟล์ใน prompts/ + ข้อมูลร้านใน shop/

แยก prompt ออกจากโค้ด (แนวเดียวกับ prompt.txt ของ Week 8 และ prompts/ ของ Week 10)
เพื่อให้ปรับถ้อยคำได้โดยไม่แตะ Python · system prompt มีแค่กฎ + ข้อมูลหลักของร้านที่ต้องรู้เสมอ
ส่วนราคา/นโยบาย/FAQ มาจาก RAG (rag/) แนบเป็นข้อความระบบแยกตามคำถาม — template ใช้ตัวแทน {{ชื่อ}} แทน str.format เพราะเนื้อหาภาษาไทย/JSON อาจมีปีกกา
"""

import re
from functools import lru_cache
from pathlib import Path

from shop import pricing

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_PLACEHOLDER_RE = re.compile(r"{{([A-Z_]+)}}")


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def render(template: str, values: dict[str, str]) -> str:
    """แทนที่ {{KEY}} ทุกตัว — ถ้าเหลือตัวไหนที่ไม่มีค่า ให้ error ทันที (กัน prompt หลุดไปแบบครึ่งๆ)"""
    missing = set(_PLACEHOLDER_RE.findall(template)) - values.keys()
    if missing:
        raise KeyError(f"prompt ขาดค่า: {sorted(missing)}")
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)


@lru_cache
def system_prompt() -> str:
    """system prompt หลักของบอทร้าน — cache ไว้เพราะข้อมูลไม่เปลี่ยนระหว่างรัน"""
    catalog = pricing.load_catalog()
    return render(
        load_prompt("chat_system.txt"),
        {
            "ASSISTANT_NAME": catalog["shop"]["assistant_name"],
            "SHOP_NAME": f'{catalog["shop"]["name_th"]} ({catalog["shop"]["name"]})',
            "SHOP_NAME_TH": catalog["shop"]["name_th"],
            "FALLBACK": catalog["fallback_message"],
            # ราคา/นโยบาย/FAQ ไม่อยู่ใน system prompt แล้ว — มาจาก RAG ตามคำถาม (ดู rag/)
            "SHOP_INFO": pricing.shop_info_text(),
        },
    )


@lru_cache
def line_hint() -> str:
    """system message เสริมสำหรับ LINE (ข้อความล้วน ไม่มีปุ่ม → ส่งลิงก์จอง/เช็คคิวของเว็บแทน)"""
    from config import settings

    site = settings.PUBLIC_SITE_URL.rstrip("/")
    return render(load_prompt("line_hint.txt"), {"BOOK_URL": f"{site}/?book=1", "CHECK_URL": f"{site}/check"})


def voice_hint() -> str:
    """system message เสริมสำหรับโหมดเสียง (ตอบสั้น ไม่มี markdown)"""
    return load_prompt("voice_hint.txt")


def fallback_message() -> str:
    return pricing.load_catalog()["fallback_message"]

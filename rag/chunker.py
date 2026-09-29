"""แบ่งคลังความรู้ของร้าน (shop/) เป็นชิ้นย่อย (chunk) สำหรับค้นคืนแบบ RAG

หลักการตัด: 1 chunk = 1 เรื่องที่ตอบคำถามได้ในตัวเอง ไม่ตัดตามจำนวนตัวอักษร เพราะคลังความรู้เล็ก
และมีโครงสร้างชัดอยู่แล้ว — ตัดตามความหมายทำให้ค้นเจอแม่นกว่าและราคาไม่ถูกหั่นกลางตาราง

- catalog.json → บริการละ 1 chunk (ราคาทุกขนาดอยู่ใน chunk เดียวกัน), บริการเสริม/รับ-ส่ง/แพ็กเกจ/
                 สินค้า กลุ่มละ 1 chunk, การชำระเงิน/มัดจำ 1 chunk
- policies.md  → หัวข้อ ## ละ 1 chunk
- faq.md       → คำถาม ## ละ 1 chunk

ข้อมูลที่ต้องรู้ทุกครั้ง (ชื่อร้าน เวลาเปิด ช่องทางติดต่อ บริการที่ไม่มี) ไม่อยู่ในนี้ แต่อยู่ใน
system prompt เสมอ (ดู shop/pricing.py::shop_info_text)
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from shop import pricing


@dataclass(frozen=True)
class Chunk:
    id: str        # รหัสคงที่ ใช้อ้างอิงใน log/ผลทดสอบ
    title: str     # ชื่อสั้นๆ ไว้โชว์เป็น "แหล่งอ้างอิง"
    source: str    # ไฟล์ต้นทาง
    text: str      # เนื้อหาที่ส่งให้ LLM และใช้ทำ embedding


def _baht(n: int) -> str:
    return f"{n:,} บาท"


def _catalog_chunks() -> list[Chunk]:
    c = pricing.load_catalog()
    sizes = c["sizes"]
    out: list[Chunk] = []

    for s in c["services"]:
        if "prices" in s:
            price = "\n".join(f"- {sizes[k]}: {_baht(v)}" for k, v in s["prices"].items())
        else:
            price = f"- ราคา {_baht(s['price'])}"
        extra = "\n".join(f"- {x}" for x in (s.get("duration"), s.get("note")) if x)
        out.append(Chunk(
            id=f"service:{s['id']}",
            title=s["name"],
            source="shop/catalog.json",
            text=f"บริการ: {s['name']}\n{price}" + (f"\n{extra}" if extra else ""),
        ))

    addon_lines = []
    for a in c["addons"]:
        price = (
            f"{_baht(a['price_min'])}–{_baht(a['price_max'])}" if "price_min" in a else _baht(a["price"])
        )
        addon_lines.append(f"- {a['name']}: {price}" + (f" ({a['note']})" if a.get("note") else ""))
    out.append(Chunk(
        id="addons",
        title="บริการเสริม",
        source="shop/catalog.json",
        text="บริการเสริม (บวกเพิ่มจากราคาบริการหลัก)\n" + "\n".join(addon_lines),
    ))

    out.append(Chunk(
        id="delivery",
        title="บริการรับ-ส่งถึงบ้าน",
        source="shop/catalog.json",
        text="บริการรับ-ส่งน้องถึงบ้าน (ไป-กลับ)\n"
        + "\n".join(f"- {d['name']}: {_baht(d['price'])}" for d in c["delivery"]),
    ))

    out.append(Chunk(
        id="packages",
        title="แพ็กเกจและส่วนลด",
        source="shop/catalog.json",
        text="แพ็กเกจและส่วนลด (ร้านมีเท่านี้เท่านั้น ไม่มีส่วนลดอื่น)\n"
        + "\n".join(
            f"- {p['name']}: ลด {p['discount_percent']}% — {p['note']}" for p in c["packages"]
        ),
    ))

    out.append(Chunk(
        id="products",
        title="สินค้าหน้าร้าน",
        source="shop/catalog.json",
        text="สินค้าที่ขายหน้าร้าน\n"
        + "\n".join(f"- {p['name']}: {_baht(p['price'])}" for p in c["products"]),
    ))

    pay = c["payment"]
    out.append(Chunk(
        id="payment",
        title="การชำระเงินและมัดจำ",
        source="shop/catalog.json",
        text=(
            "การชำระเงินและมัดจำการจองคิว\n"
            f"- ช่องทางชำระเงิน: {', '.join(pay['methods'])}\n"
            f"- ชื่อบัญชี: {pay['account_name']}\n"
            f"- มัดจำ: {_baht(pay['deposit'])} — {pay['deposit_note']}"
        ),
    ))
    return out


def _markdown_chunks(filename: str, prefix: str) -> list[Chunk]:
    """ตัดไฟล์ markdown ตามหัวข้อระดับ ## — ข้อความก่อนหัวข้อแรก (คำอธิบายไฟล์) ไม่นำมาใช้"""
    text = pricing.read_text(filename)
    out: list[Chunk] = []
    for i, section in enumerate(re.split(r"^## ", text, flags=re.MULTILINE)[1:], start=1):
        heading, _, body = section.partition("\n")
        heading = heading.strip()
        out.append(Chunk(
            id=f"{prefix}:{i}",
            title=re.sub(r"^\d+\.\s*", "", heading),
            source=f"shop/{filename}",
            text=f"{heading}\n{body.strip()}",
        ))
    return out


def build_chunks() -> list[Chunk]:
    return (
        _catalog_chunks()
        + _markdown_chunks("policies.md", "policy")
        + _markdown_chunks("faq.md", "faq")
    )


def chunks_hash(chunks: list[Chunk]) -> str:
    """ลายนิ้วมือของคลังความรู้ — ใช้เช็คว่า index ที่สร้างไว้ยังตรงกับข้อมูลร้านปัจจุบันไหม"""
    payload = json.dumps([asdict(c) for c in chunks], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

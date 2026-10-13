"""ข้อมูลร้านและการคำนวณราคา — อ่านจาก shop/catalog.json ที่เดียว

catalog.json คือแหล่งข้อมูลราคาเพียงแหล่งเดียวของระบบ: ใช้ทั้งสร้างชิ้นความรู้ของ RAG
(rag/chunker.py — ให้ LLM เล่า) และคำนวณราคาจริงด้วยโค้ด (quote) — ราคาที่บอทพูดกับราคาที่
ระบบคิดจึงไม่มีทางขัดกัน ร้านจะเปลี่ยนราคาก็แก้ไฟล์ JSON ไฟล์เดียว (แล้วรัน rag.build_index)

หลักการ: ตัวเลขเงินทุกตัวต้องมาจากโค้ดนี้ ไม่ให้ LLM คำนวณหรือแต่งราคาเอง
(กันเคส "ให้ส่วนลดเกินจริง" ตามเงื่อนไขของร้าน)
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

SHOP_DIR = Path(__file__).resolve().parent
CATALOG_PATH = SHOP_DIR / "catalog.json"

SIZES = ("small", "medium", "large", "cat")


@lru_cache
def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


_OFFER_SECTIONS = ("services", "addons", "delivery", "packages", "products")
_PAREN_RE = re.compile(r"\([^)]*\)")
_TAIL_SIZE_RE = re.compile(r"\s*\d[\d.,–-]*\s*(มล\.?|กรัม|กก\.?|กม\.?|ชิ้น)?.*$")


@lru_cache
def offer_names() -> tuple[str, ...]:
    """ชื่อบริการ บริการเสริม รับ-ส่ง แพ็กเกจ และสินค้าทุกรายการของร้าน ตามที่เขียนใน catalog"""
    catalog = load_catalog()
    return tuple(item["name"] for section in _OFFER_SECTIONS for item in catalog.get(section, []))


def _name_words(name: str) -> list[str]:
    """แตกชื่อรายการเป็นคำสำคัญ: ตัดวงเล็บและขนาดบรรจุออก แยกที่ + และ /
    เช่น "อาบน้ำ + เป่าขน" → อาบน้ำ, เป่าขน · "แชมพูสูตรอ่อนโยน 250 มล." → แชมพูสูตรอ่อนโยน"""
    words = []
    for part in re.split(r"[+/]", _PAREN_RE.sub(" ", name)):
        word = re.sub(r"\s*ระยะ.*$", "", _TAIL_SIZE_RE.sub("", part)).strip()
        if len(word) >= 3:
            words.append(word)
    return words


@lru_cache
def offer_keyword_chunks() -> dict[str, str]:
    """คำสำคัญของสิ่งที่ร้านมีให้บริการ/ขาย → id ของชิ้นข้อมูลใน RAG ที่มีราคาของรายการนั้น (ดู rag/chunker.py)
    ร้านเพิ่มบริการใน catalog คำสำคัญเพิ่มตามเอง"""
    catalog = load_catalog()
    out: dict[str, str] = {}
    for section in _OFFER_SECTIONS:
        for item in catalog.get(section, []):
            chunk_id = f"service:{item['id']}" if section == "services" else section
            for word in _name_words(item["name"]):
                out.setdefault(word, chunk_id)
    return out


def offer_keywords() -> tuple[str, ...]:
    return tuple(offer_keyword_chunks())


def _compact(text: str) -> str:
    return re.sub(r"[\s-]+", "", text or "")  # "รับ ส่ง" / "รับ-ส่ง" / "รับส่ง" นับเป็นคำเดียวกัน


def offer_chunk_ids(text: str) -> list[str]:
    """id ของชิ้นข้อมูลที่ต้องอยู่ในผลค้น เพราะข้อความพูดถึงรายการนั้นตรง ๆ (เรียงตามลำดับใน catalog ไม่ซ้ำ)"""
    compact = _compact(text)
    ids: list[str] = []
    for word, chunk_id in offer_keyword_chunks().items():
        if _compact(word) in compact and chunk_id not in ids:
            ids.append(chunk_id)
    return ids


def mentions_offer(text: str) -> bool:
    """ข้อความพูดถึงของที่ร้านมีจริงไหม — ใช้กันตัวตรวจขาเข้าตีเป็นนอกเรื่อง (guardrails/pipeline.py)"""
    return bool(offer_chunk_ids(text))


def _baht(n: int) -> str:
    return f"{n:,} บาท"


def _index(section: str) -> dict[str, dict]:
    return {item["id"]: item for item in load_catalog()[section]}


@dataclass
class Quote:
    """ผลประเมินราคา — min/max ต่างกันเมื่อมีรายการที่ประเมินหน้างาน (เช่น ขนพัน)"""

    lines: list[tuple[str, int, int]] = field(default_factory=list)  # (ชื่อ, min, max)

    @property
    def min(self) -> int:
        return sum(lo for _, lo, _ in self.lines)

    @property
    def max(self) -> int:
        return sum(hi for _, _, hi in self.lines)

    def text(self) -> str:
        rows = [
            f"- {name}: {_baht(lo)}" if lo == hi else f"- {name}: {_baht(lo)}–{_baht(hi)}"
            for name, lo, hi in self.lines
        ]
        total = _baht(self.min) if self.min == self.max else f"{_baht(self.min)}–{_baht(self.max)}"
        return "\n".join(rows + [f"รวมประมาณ {total}"])


def quote(service_id: str, size: str | None = None, addons: tuple[str, ...] = ()) -> Quote:
    """ประเมินราคาบริการหลัก + รายการเสริม ด้วยข้อมูลจาก catalog เท่านั้น
    raise ValueError ถ้ารหัสบริการ/ขนาดไม่ถูกต้อง (ผู้เรียกต้องจัดการเอง ห้ามเดาราคา)"""
    services = _index("services")
    if service_id not in services:
        raise ValueError(f"ไม่รู้จักบริการ: {service_id}")
    svc = services[service_id]

    q = Quote()
    if "prices" in svc:
        if size not in svc["prices"]:
            raise ValueError(f"บริการ {service_id} ต้องระบุขนาดเป็นหนึ่งใน {sorted(svc['prices'])}")
        price = svc["prices"][size]
        q.lines.append((f"{svc['name']} ({load_catalog()['sizes'][size]})", price, price))
    else:
        q.lines.append((svc["name"], svc["price"], svc["price"]))

    all_addons = _index("addons")
    for addon_id in addons:
        if addon_id not in all_addons:
            raise ValueError(f"ไม่รู้จักบริการเสริม: {addon_id}")
        a = all_addons[addon_id]
        lo = a.get("price_min", a.get("price"))
        hi = a.get("price_max", a.get("price"))
        q.lines.append((a["name"], lo, hi))
    return q


def shop_info_text() -> str:
    """ข้อมูลพื้นฐานร้าน + การชำระเงิน + บริการที่ร้านไม่มี สำหรับใส่ใน system prompt"""
    c = load_catalog()
    s, pay = c["shop"], c["payment"]
    name = f"{s['name_th']} ({s['name']})" if s.get("name_th") else s["name"]
    lines = [
        f"- ชื่อร้าน: {name}",
        f"- เกี่ยวกับร้าน: {s['description']}",
        f"- ที่ตั้ง: {s['address']}",
        f"- เวลาทำการ: {s['hours']} ({s['last_queue']})",
        f"- ติดต่อ: LINE {s['contacts']['line']} / โทร {s['contacts']['phone']}",
        f"- ช่องทางจองคิว: {', '.join(s['booking_channels'])}",
        f"- ขนาดสัตว์ที่ใช้คิดราคา: {', '.join(c['sizes'].values())}",
        f"- ชำระเงินได้ทาง: {', '.join(pay['methods'])} (ชื่อบัญชี {pay['account_name']})",
        f"- มัดจำการจอง: {_baht(pay['deposit'])} — {pay['deposit_note']}",
        "- บริการที่ร้าน **ไม่มี**: " + ", ".join(c["not_offered"]),
    ]
    return "\n".join(lines)


def read_text(name: str) -> str:
    """อ่านไฟล์ความรู้ข้อความของร้าน (policies.md / faq.md)"""
    return (SHOP_DIR / name).read_text(encoding="utf-8").strip()

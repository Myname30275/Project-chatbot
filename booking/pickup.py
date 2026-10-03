"""บริการรับ-ส่งน้อง: วัดระยะจากร้านถึงหมุดที่ลูกค้าปัก → ค่ารับส่งตามตาราง delivery ใน catalog

วัดแบบไม่ต้องใช้ API ภายนอก: ระยะเส้นตรง (haversine) × road_factor ให้ใกล้ระยะถนนจริง
ค่ารับส่งคำนวณที่เซิร์ฟเวอร์เสมอ (ไม่เชื่อตัวเลขจากหน้าเว็บ) แล้วใช้ตรวจยอดในสลิป
"""

import math
import re
import unicodedata

from shop import pricing

EARTH_KM = 6371.0
ADDRESS_MAX = 200


class PickupError(Exception):
    """ข้อมูลรับส่งใช้ไม่ได้ — message แสดงให้ลูกค้าเห็นได้"""


def config() -> dict:
    return pricing.load_catalog()["booking"]["pickup"]


def zones() -> list[dict]:
    """ตารางค่ารับส่ง เรียงจากใกล้ไปไกล: [{"max_km": 5, "price": 150, ...}, ...]"""
    return sorted(pricing.load_catalog()["delivery"], key=lambda z: z["max_km"])


def max_km() -> float:
    return zones()[-1]["max_km"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _coord(value, low: float, high: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise PickupError("กรุณาปักหมุดจุดรับน้องบนแผนที่") from None
    if not math.isfinite(x) or not low <= x <= high:
        raise PickupError("กรุณาปักหมุดจุดรับน้องบนแผนที่")
    return x


def quote(lat, lng) -> dict:
    """{"lat", "lng", "km", "fee"} — ไกลเกินระยะให้บริการ raise PickupError"""
    lat, lng = _coord(lat, -90, 90), _coord(lng, -180, 180)
    c = config()
    km = round(haversine_km(c["shop_lat"], c["shop_lng"], lat, lng) * c["road_factor"], 1)
    for zone in zones():
        if km <= zone["max_km"]:
            return {"lat": round(lat, 6), "lng": round(lng, 6), "km": km, "fee": zone["price"]}
    raise PickupError(f"จุดนี้ห่างจากร้านประมาณ {km:g} กม. ร้านรับ-ส่งได้ไม่เกิน {max_km():g} กม. ค่ะ")


def clean_address(value: str | None) -> str:
    """ที่อยู่/จุดสังเกตให้คนขับ — ตัดอักขระควบคุม คงการขึ้นบรรทัดใหม่ไว้"""
    text = "".join(ch for ch in (value or "") if ch == "\n" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise PickupError("กรุณากรอกที่อยู่หรือจุดสังเกตให้คนขับ")
    if len(text) > ADDRESS_MAX:
        raise PickupError(f"ที่อยู่ยาวได้ไม่เกิน {ADDRESS_MAX} ตัวอักษร")
    return text


def public_config() -> dict:
    """สิ่งที่หน้าเว็บต้องใช้วาดแผนที่และตารางราคา"""
    c = config()
    return {
        "shop": {"lat": c["shop_lat"], "lng": c["shop_lng"]},
        "zones": [{"max_km": z["max_km"], "fee": z["price"]} for z in zones()],
        "road_factor": c["road_factor"],
        "lead_minutes": c["lead_minutes"],
    }

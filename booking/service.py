"""ขั้นตอนการจองคิว: ตรวจฟอร์ม → กันช่องเวลา (atomic) → ตรวจสลิป → ออกเลขจอง → บันทึก

ข้อตกลงของร้าน (docs/booking-plan.md §1)
- ฟอร์มมีแค่ชื่อน้อง ชื่อเจ้าของ เบอร์โทร + ช่องเวลา + รูปน้อง + สลิป
- **ไม่มีราคา** ในข้อมูลการจอง — ราคาในแชทเป็นราคาประเมิน ร้านชั่งน้ำหนักจริงหน้าร้าน
- บอทไม่ยืนยันการชำระเงินเอง: จองสำเร็จ = สถานะ "รอร้านยืนยัน" เจ้าของร้านเป็นคนยืนยัน
"""

import logging
import re
import unicodedata

from booking import slots
from booking.store import StoreError, get_store
from shop import pricing
from vision import image_analyzer, slip_check
from vision.image_analyzer import VisionError

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 1_500_000  # หน้าเว็บย่อรูปเหลือ ≤ 800 px ก่อนส่ง (~100 KB) เผื่อไว้พอ
NAME_MAX = 40
_PHONE_RE = re.compile(r"^0\d{9}$")

STATUS_LABEL = {
    "pending": "รอร้านยืนยัน",
    "confirmed": "ยืนยันแล้ว",
    "done": "มาใช้บริการแล้ว",
    "cancelled": "ยกเลิกแล้ว",
}


class BookingError(Exception):
    """จองไม่สำเร็จ — message แสดงให้ลูกค้าเห็นได้ · field บอกหน้าเว็บว่าช่องไหนต้องแก้"""

    def __init__(self, message: str, status: int = 422, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field


def clean_name(value: str | None, label: str, field: str) -> str:
    """ตัดอักขระควบคุม/ช่องว่างซ้อน (ชื่อไปอยู่บนใบจองและหลังบ้าน ไม่ใช่ข้อความให้ LLM)"""
    text = "".join(ch for ch in (value or "") if unicodedata.category(ch)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise BookingError(f"กรุณากรอก{label}", field=field)
    if len(text) > NAME_MAX:
        raise BookingError(f"{label}ยาวได้ไม่เกิน {NAME_MAX} ตัวอักษร", field=field)
    return text


def clean_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not _PHONE_RE.match(digits):
        raise BookingError("เบอร์โทรต้องเป็นตัวเลข 10 หลัก ขึ้นต้นด้วย 0", field="phone")
    return digits


def sniff_image(data: bytes) -> str | None:
    """ดูชนิดรูปจาก byte แรกของไฟล์ (ไม่เชื่อนามสกุล/Content-Type ที่ส่งมา)"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _check_image(data: bytes | None, label: str, field: str) -> str:
    if not data:
        raise BookingError(f"กรุณาแนบ{label}", field=field)
    if len(data) > MAX_IMAGE_BYTES:
        raise BookingError(f"{label}ใหญ่เกินไป ลองเลือกรูปใหม่อีกครั้ง", field=field)
    mime = sniff_image(data)
    if not mime:
        raise BookingError(f"{label}ต้องเป็นไฟล์ JPG, PNG หรือ WebP", field=field)
    return mime


async def check_slip(data: bytes, mime: str) -> dict:
    """ตรวจสลิปด้วย Vision ตัวเดิม — ไม่ผ่านชัดเจนแล้ว raise · อ่านไม่ได้ = รับไว้ให้ร้านตรวจเอง"""
    deposit = pricing.load_catalog()["payment"]["deposit"]
    try:
        analysis = await image_analyzer.analyze(data, mime)
    except VisionError as exc:
        logger.warning("อ่านสลิปตอนจองไม่ได้ ให้ร้านตรวจเอง: %s", exc)
        return {"auto_ok": False, "amount": None, "receiver_ok": None, "reference": None}

    if analysis.image_type != "slip":
        raise BookingError("รูปนี้ไม่ใช่สลิปโอนเงิน รบกวนแนบรูปสลิปมัดจำอีกครั้ง", field="slip")
    slip = analysis.slip
    if slip.amount is not None and slip.amount != deposit:
        raise BookingError(
            f"ยอดในสลิปคือ {slip.amount:,.0f} บาท แต่ค่ามัดจำคือ {deposit} บาท รบกวนตรวจสอบสลิปอีกครั้ง",
            field="slip",
        )
    receiver = slip_check.receiver_matches(slip.receiver_name)
    if receiver is False:
        raise BookingError(
            f"ชื่อผู้รับเงินในสลิป ({slip.receiver_name}) ไม่ใช่บัญชีของร้าน รบกวนตรวจสอบว่าโอนถูกบัญชีไหม",
            field="slip",
        )
    return {
        "auto_ok": slip.amount == deposit and receiver is True,
        "amount": slip.amount,
        "receiver_ok": receiver,
        "reference": slip.reference or None,
    }


async def create(
    session_id: str,
    *,
    pet_name: str | None,
    owner_name: str | None,
    phone: str | None,
    slot: str | None,
    pet_photo: bytes | None,
    slip: bytes | None,
    at=None,
) -> dict:
    """คืนข้อมูลการจอง (dict) — raise BookingError / StoreError ถ้าไม่สำเร็จ"""
    pet_name = clean_name(pet_name, "ชื่อน้อง", "pet_name")
    owner_name = clean_name(owner_name, "ชื่อเจ้าของ", "owner_name")
    phone = clean_phone(phone)
    dt = slots.parse_slot(slot or "", at)
    if dt is None:
        raise BookingError("ช่องเวลานี้จองไม่ได้แล้ว รบกวนเลือกช่องใหม่", status=409, field="slot")
    _check_image(pet_photo, "รูปน้อง", "pet_photo")
    slip_mime = _check_image(slip, "รูปสลิป", "slip")

    store = get_store()
    key = slots.slot_key(dt)
    if not await store.reserve_slot(key, slots.config()["capacity_per_slot"]):
        raise BookingError("ช่องเวลานี้เพิ่งเต็ม รบกวนเลือกช่องใหม่", status=409, field="slot")

    reference = None
    try:
        slip_info = await check_slip(slip, slip_mime)
        seq = await store.next_seq(dt.strftime("%Y%m%d"))
        booking_id = f"HH-{dt:%m%d}-{seq:02d}"
        if slip_info["reference"]:
            if not await store.claim_slip_ref(slip_info["reference"], booking_id):
                raise BookingError("สลิปใบนี้ถูกใช้จองคิวไปแล้ว รบกวนแนบสลิปของการโอนครั้งนี้", status=409, field="slip")
            reference = slip_info["reference"]

        created = slots.now().isoformat(timespec="seconds")
        booking = {
            "id": booking_id,
            "session_id": session_id,
            "pet_name": pet_name,
            "owner_name": owner_name,
            "phone": phone,
            "slot": key,
            "slot_ts": dt.timestamp(),
            "status": "pending",
            "slip": slip_info,
            "created_at": created,
            "updated_at": created,
        }
        await store.save_image(booking_id, "pet", pet_photo)
        await store.save_image(booking_id, "slip", slip)
        await store.save(booking)
        await store.index(booking)
        logger.info("จองคิวใหม่ %s ช่อง %s (สลิปตรวจอัตโนมัติ=%s)", booking_id, key, slip_info["auto_ok"])
        return booking
    except BaseException:
        # ไม่สำเร็จที่ขั้นไหนก็ตาม → คืนช่องเวลา/เลขสลิปที่กันไว้ ลูกค้าเลือกใหม่หรือแนบสลิปใหม่ได้ทันที
        try:
            await store.release_slot(key)
            if reference:
                await store.release_slip_ref(reference)
        except StoreError:
            logger.error("คืนช่องเวลา %s ไม่สำเร็จ", key)
        raise


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}-xxx-{phone[6:]}" if len(phone) == 10 else "xxx"


def public_view(b: dict) -> dict:
    """ข้อมูลบนใบจองที่ส่งให้หน้าเว็บลูกค้า — ไม่มีราคา, ไม่มี session_id, เบอร์ปิดกลาง"""
    return {
        "id": b["id"],
        "pet_name": b["pet_name"],
        "owner_name": b["owner_name"],
        "phone": mask_phone(b["phone"]),
        "slot": b["slot"],
        "slot_label": slots.slot_label(slots.parse_key(b["slot"])),
        "status": b["status"],
        "status_label": STATUS_LABEL.get(b["status"], b["status"]),
        "pet_image": f"/api/v1/booking/{b['id']}/image/pet",
        # สลิปไม่อยู่บนใบจองของลูกค้า — ร้านดูได้ในหลังบ้าน (/api/v1/admin/bookings/{id}/image/slip)
    }


async def list_for_session(session_id: str) -> list[dict]:
    store = get_store()
    out = []
    for booking_id in await store.session_ids(session_id):
        b = await store.get(booking_id)
        if b and b.get("session_id") == session_id:
            out.append(public_view(b))
    return out


async def get_owned(booking_id: str, session_id: str) -> dict | None:
    """การจองนี้เป็นของ session นี้ไหม — ไม่ใช่ = None (API ตอบ 404 เหมือนไม่มีอยู่จริง)"""
    b = await get_store().get(booking_id)
    return b if b and b.get("session_id") == session_id else None


# ---------------- หลังบ้านเจ้าของร้าน ----------------

# เปลี่ยนสถานะได้เฉพาะทางเดินนี้ — กันกดพลาดย้อนสถานะ (เช่น ยกเลิกแล้วกลับมายืนยัน)
TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"done", "cancelled"},
    "done": set(),
    "cancelled": set(),
}


def admin_view(b: dict) -> dict:
    """ข้อมูลเต็มสำหรับเจ้าของร้าน — เบอร์เต็ม + ผลตรวจสลิป (ยังไม่มีราคาเหมือนเดิม)"""
    view = public_view(b)
    view.update(
        phone=b["phone"],
        slip=b.get("slip", {}),
        created_at=b.get("created_at"),
        updated_at=b.get("updated_at"),
        next_status=sorted(TRANSITIONS.get(b["status"], set())),
    )
    return view


async def list_between(start, end) -> list[dict]:
    """การจองที่นัดอยู่ในช่วง [start, end) เรียงตามเวลานัด"""
    store = get_store()
    out = []
    for booking_id in await store.ids_between(start.timestamp(), end.timestamp()):
        b = await store.get(booking_id)
        if b:
            out.append(admin_view(b))
    return sorted(out, key=lambda v: (v["slot"], v["id"]))


async def set_status(booking_id: str, status: str) -> dict:
    store = get_store()
    b = await store.get(booking_id)
    if not b:
        raise BookingError("ไม่พบการจองนี้", status=404)
    if status not in TRANSITIONS.get(b["status"], set()):
        raise BookingError(
            f"เปลี่ยนจาก “{STATUS_LABEL.get(b['status'], b['status'])}” เป็น “{STATUS_LABEL.get(status, status)}” ไม่ได้",
            status=409,
        )
    b["status"] = status
    b["updated_at"] = slots.now().isoformat(timespec="seconds")
    await store.save(b)
    if status == "cancelled":
        # คืนช่องเวลาให้ลูกค้าคนอื่นจองได้ทันที (เลขสลิปยังถือว่าใช้แล้ว — มัดจำตามนโยบายร้าน)
        await store.release_slot(b["slot"])
    logger.info("เปลี่ยนสถานะ %s → %s", booking_id, status)
    return admin_view(b)


# ---------------- หน้าเช็คคิว (/check) ----------------

STATUS_HINT = {
    "pending": "ร้านกำลังตรวจยอดมัดจำ จะยืนยันคิวให้เร็ว ๆ นี้",
    "confirmed": "ร้านยืนยันคิวแล้ว แสดงใบจองที่หน้าร้านได้เลย",
    "done": "มาใช้บริการแล้ว ขอบคุณที่ไว้ใจ Hom Hom Grooming",
    "cancelled": "คิวนี้ถูกยกเลิก สอบถามร้านทาง LINE หรือโทรได้เลย",
}


def check_view(b: dict) -> dict:
    """ข้อมูลที่หน้าเช็คคิวแสดงได้ — ค้นด้วยเบอร์โทรอย่างเดียว จึงไม่แสดงชื่อเจ้าของ/รูป/สลิป"""
    return {
        "id": b["id"],
        "pet_name": b["pet_name"],
        "slot": b["slot"],
        "slot_label": slots.slot_label(slots.parse_key(b["slot"])),
        "status": b["status"],
        "status_label": STATUS_LABEL.get(b["status"], b["status"]),
        "status_hint": STATUS_HINT.get(b["status"], ""),
    }


async def lookup_by_phone(phone: str | None, limit: int = 10) -> list[dict]:
    """คิวของเบอร์นี้: ที่ยังไม่ถึงวันนัดขึ้นก่อน (ใกล้สุดก่อน) ตามด้วยที่ผ่านมาแล้ว (ล่าสุดก่อน)"""
    phone = clean_phone(phone)
    store = get_store()
    found = []
    for booking_id in await store.phone_ids(phone):
        b = await store.get(booking_id)
        if b and b.get("phone") == phone:
            found.append(check_view(b))
    today = slots.slot_key(slots.now())[:10]
    upcoming = sorted((v for v in found if v["slot"][:10] >= today), key=lambda v: v["slot"])
    past = sorted((v for v in found if v["slot"][:10] < today), key=lambda v: v["slot"], reverse=True)
    return (upcoming + past)[:limit]

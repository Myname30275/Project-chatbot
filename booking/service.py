"""ขั้นตอนการจองคิว: ตรวจฟอร์ม → กันช่องเวลา (atomic) → ตรวจสลิป → ออกเลขจอง → บันทึก

ข้อตกลงของร้าน (docs/booking-plan.md §1)
- ฟอร์มมีแค่ชื่อน้อง ชื่อเจ้าของ เบอร์โทร + ช่องเวลา + รูปน้อง (ไม่บังคับ) + สลิป (+ จุดรับน้อง ถ้าติ๊กรับ-ส่ง)
- **ไม่มีราคา** ในข้อมูลการจอง — ราคาในแชทเป็นราคาประเมิน ร้านชั่งน้ำหนักจริงหน้าร้าน
  (ยอดที่ต้องโอน = มัดจำ + ค่ารับส่ง ถ้ามี — จ่ายล่วงหน้า ไม่ใช่ราคาบริการ)
- บอทไม่ยืนยันการชำระเงินเอง: จองสำเร็จ = สถานะ "รอร้านยืนยัน" เจ้าของร้านเป็นคนยืนยัน
"""

import logging
import re
import unicodedata
from datetime import timedelta

from booking import pickup as pickup_zone
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


def clean_pets(value) -> int:
    """จำนวนน้องในการจองครั้งนี้ (1 ถึง booking.max_pets)"""
    limit = slots.config()["max_pets"]
    try:
        n = int(str(1 if value in (None, "") else value).strip())
    except ValueError:
        n = 0
    if not 1 <= n <= limit:
        raise BookingError(f"จองได้ครั้งละ 1–{limit} ตัว ถ้ามากกว่านี้รบกวนจองแยกอีกคิวค่ะ", field="pets")
    return n


def clean_service(value) -> dict:
    """บริการหลักที่ลูกค้าเลือก — กำหนดว่าคิวนี้กันเวลาช่างกี่ชั่วโมงต่อน้อง 1 ตัว (booking.services)"""
    found = slots.service(str(value or "").strip())
    if not found:
        raise BookingError("กรุณาเลือกบริการที่ต้องการ", field="service")
    return found


def slots_used(b: dict) -> list[tuple[str, int]]:
    """ช่องเวลาที่การจองนี้กันไว้ — การจองรุ่นก่อนมีจำนวนน้อง (ไม่มี slots_used) = 1 ช่างในช่องที่จอง"""
    return [(k, u) for k, u in b.get("slots_used") or [(b["slot"], 1)]]


async def _release(store, used: list[tuple[str, int]]) -> None:
    for key, units in used:
        await store.release_slot(key, units)


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


def deposit() -> int:
    return pricing.load_catalog()["payment"]["deposit"]


def amount_due(pets: int = 1, fee: int = 0) -> int:
    """ยอดที่ลูกค้าต้องโอนตอนจอง = มัดจำต่อตัว × จำนวนน้อง + ค่ารับส่ง (เจ้าของร้านกำหนด 4 ต.ค. 2569)"""
    return deposit() * pets + fee


def _due_text(pets: int, fee: int) -> str:
    due = amount_due(pets, fee)
    if pets == 1 and not fee:
        return f"ค่ามัดจำคือ {due:,} บาท"
    parts = f"มัดจำ {deposit()} × {pets} ตัว" if pets > 1 else f"มัดจำ {deposit()}"
    return f"ยอดที่ต้องโอนคือ {due:,} บาท ({parts}{f' + ค่ารับส่ง {fee}' if fee else ''})"


async def check_slip(data: bytes, mime: str, fee: int = 0, pets: int = 1) -> dict:
    """ตรวจสลิปด้วย Vision ตัวเดิม — ไม่ผ่านชัดเจนแล้ว raise · อ่านไม่ได้ = รับไว้ให้ร้านตรวจเอง
    ยอดที่ต้องตรงกับสลิป = มัดจำ × จำนวนน้อง + ค่ารับส่ง (0 ถ้าไม่ได้ติ๊กรับ-ส่ง)"""
    due = amount_due(pets, fee)
    try:
        analysis = await image_analyzer.analyze(data, mime)
    except VisionError as exc:
        logger.warning("อ่านสลิปตอนจองไม่ได้ ให้ร้านตรวจเอง: %s", exc)
        return {"auto_ok": False, "amount": None, "receiver_ok": None, "reference": None, "sender_name": None}

    if analysis.image_type != "slip":
        raise BookingError("รูปนี้ไม่ใช่สลิปโอนเงิน รบกวนแนบรูปสลิปมัดจำอีกครั้ง", field="slip")
    slip = analysis.slip
    if slip.amount is not None and slip.amount != due:
        raise BookingError(
            f"ยอดในสลิปคือ {slip.amount:,.0f} บาท แต่{_due_text(pets, fee)} รบกวนตรวจสอบสลิปอีกครั้ง",
            field="slip",
        )
    receiver = slip_check.receiver_matches(slip.receiver_name)
    if receiver is False:
        raise BookingError(
            f"ชื่อผู้รับเงินในสลิป ({slip.receiver_name}) ไม่ใช่บัญชีของร้าน รบกวนตรวจสอบว่าโอนถูกบัญชีไหม",
            field="slip",
        )
    return {
        "auto_ok": slip.amount == due and receiver is True,
        "amount": slip.amount,
        "receiver_ok": receiver,
        "reference": slip.reference or None,
        "sender_name": slip.sender_name or None,
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
    pickup: dict | None = None,
    pets=1,
    service=None,
    at=None,
) -> dict:
    """คืนข้อมูลการจอง (dict) — raise BookingError / StoreError ถ้าไม่สำเร็จ
    pickup = {"lat", "lng", "address"} จากฟอร์มเมื่อลูกค้าติ๊กรับ-ส่ง (None = มาที่ร้านเอง)
    service = บริการหลักที่เลือก: กันเวลาช่างตามชั่วโมงของบริการ (อาบน้ำ 2 ชม. ตัดขน 3 ชม.)
    pets = จำนวนน้อง: ไม่เกินจำนวนช่าง = ทำพร้อมกัน, ตัวที่ 3 ขึ้นไป = ทำรอบถัดไปต่อจากรอบแรก (slots.plan)"""
    chosen = clean_service(service)
    pets = clean_pets(pets)
    pet_name = clean_name(pet_name, "ชื่อน้อง", "pet_name")
    owner_name = clean_name(owner_name, "ชื่อเจ้าของ", "owner_name")
    phone = clean_phone(phone)
    dt = slots.parse_slot(slot or "", at)
    if dt is None:
        raise BookingError("ช่องเวลานี้จองไม่ได้แล้ว รบกวนเลือกช่องใหม่", status=409, field="slot")
    ride = _pickup(pickup, dt)
    if pet_photo:  # รูปน้องไม่บังคับ (เจ้าของอาจไม่มีรูป) — ถ้าแนบมาก็ยังตรวจชนิด/ขนาดเหมือนเดิม
        _check_image(pet_photo, "รูปน้อง", "pet_photo")
    slip_mime = _check_image(slip, "รูปสลิป", "slip")

    store = get_store()
    key = slots.slot_key(dt)
    wanted = slots.plan(dt, pets, chosen["hours"])
    if wanted is None:
        raise BookingError(
            f"เริ่มเวลานี้ดูแลน้อง {pets} ตัวไม่ทันก่อนร้านปิด (ใช้เวลา {_span(pets, chosen)} ชั่วโมง) รบกวนเลือกเวลาที่เร็วขึ้น",
            status=409, field="slot")
    held: list[tuple[str, int]] = []
    for slot_k, units in wanted:
        if not await store.reserve_slot(slot_k, slots.config()["capacity_per_slot"], units):
            await _release(store, held)
            raise BookingError(
                "ช่องเวลานี้เพิ่งเต็ม รบกวนเลือกช่องใหม่" if len(wanted) == 1
                else f"ช่วงเวลานี้คิวว่างไม่พอ (บริการนี้ใช้เวลา {len(wanted)} ชั่วโมง) รบกวนเลือกช่องใหม่",
                status=409, field="slot")
        held.append((slot_k, units))

    reference = None
    try:
        slip_info = await check_slip(slip, slip_mime, ride["fee"] if ride else 0, pets)
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
            "pets": pets,
            "service": chosen["id"],
            "slots_used": [list(x) for x in held],
            "has_pet_photo": bool(pet_photo),
            "status": "pending",
            "slip": slip_info,
            "pickup": ride,
            "amount_due": amount_due(pets, ride["fee"] if ride else 0),
            "created_at": created,
            "updated_at": created,
        }
        if pet_photo:
            await store.save_image(booking_id, "pet", pet_photo)
        await store.save_image(booking_id, "slip", slip)
        await store.save(booking)
        await store.index(booking)
        logger.info("จองคิวใหม่ %s ช่อง %s (สลิปตรวจอัตโนมัติ=%s)", booking_id, key, slip_info["auto_ok"])
        return booking
    except BaseException:
        # ไม่สำเร็จที่ขั้นไหนก็ตาม → คืนช่องเวลา/เลขสลิปที่กันไว้ ลูกค้าเลือกใหม่หรือแนบสลิปใหม่ได้ทันที
        try:
            await _release(store, held)
            if reference:
                await store.release_slip_ref(reference)
        except StoreError:
            logger.error("คืนช่องเวลา %s ไม่สำเร็จ", key)
        raise


def _pickup(raw: dict | None, dt) -> dict | None:
    """ตรวจจุดรับ + คิดค่ารับส่งที่เซิร์ฟเวอร์ · เวลารับ = ก่อนเวลานัด lead_minutes นาที"""
    if not raw:
        return None
    try:
        ride = pickup_zone.quote(raw.get("lat"), raw.get("lng"))
        ride["address"] = pickup_zone.clean_address(raw.get("address"))
    except pickup_zone.PickupError as exc:
        raise BookingError(str(exc), field="pickup") from None
    ride["time"] = (dt - timedelta(minutes=pickup_zone.config()["lead_minutes"])).strftime("%H:%M")
    return ride


def _when(b: dict) -> str:
    """วันเวลานัด — จองหลายตัวจนกินมากกว่า 1 ชั่วโมง แสดงเป็นช่วง เช่น 10:00–12:00 น."""
    return slots.range_label(slots.parse_key(b["slot"]), len(slots_used(b)))


def _span(pets: int, chosen: dict) -> int:
    """จำนวนชั่วโมงรวมที่การจองนี้ใช้ = ชั่วโมงของบริการ × จำนวนรอบ (รอบละไม่เกินจำนวนช่าง)"""
    cap = slots.config()["capacity_per_slot"]
    return chosen["hours"] * -(-pets // cap)


def service_label(b: dict) -> str:
    """ชื่อบริการที่เลือกตอนจอง — การจองรุ่นก่อนมีช่องเลือกบริการ = ว่าง"""
    found = slots.service(b.get("service"))
    return found["label"].split(" เช่น")[0] if found else ""


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
        "slot_label": _when(b),
        "pets": b.get("pets", 1),
        "service_label": service_label(b),
        "status": b["status"],
        "status_label": STATUS_LABEL.get(b["status"], b["status"]),
        # การจองที่ไม่ได้แนบรูปน้อง = None (หน้าเว็บใช้โลโก้ร้านแทน) · การจองรุ่นก่อนมีตัวเลือกนี้มีรูปทุกใบ
        "pet_image": f"/api/v1/booking/{b['id']}/image/pet" if b.get("has_pet_photo", True) else None,
        # ใบจองบอกแค่ว่ามีรับ-ส่งกี่โมง — ที่อยู่/พิกัดอยู่เฉพาะหลังบ้าน
        "pickup_time": (b.get("pickup") or {}).get("time"),
        **cancel_view(b),
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

# ---------------- ลูกค้ายกเลิกคิวเอง (ฟังก์ชันยกเลิกคิวในแชท / หน้าเช็คคิว) ----------------
#
# ไม่ผูกกับประวัติแชท — ยกเลิกจากเครื่องไหนก็ได้ แต่ต้องยืนยันตัวตนให้ตรงทั้ง 3 อย่าง:
# เลขจอง + เบอร์โทร + ชื่อเจ้าของ (ชื่อเจ้าของไม่แสดงบนหน้าเช็คคิว จึงเดาจากเบอร์โทรอย่างเดียวไม่ได้)
# กันสวมรอยเอาเงินคืน:
#   1) ยืนยันผิดครบ MAX_VERIFY_FAILS ครั้ง → ล็อกการยกเลิกออนไลน์ของคิวนั้น 24 ชม. (นับใน Redis)
#   2) ร้านโอนคืนเข้าบัญชีชื่อเดียวกับผู้โอนมัดจำเท่านั้น — ระบบเทียบชื่อจากสลิปให้ หลังบ้านเตือนถ้าไม่ตรง
# ยกเลิกได้ถึง cancel_hours_before ชั่วโมงก่อนนัด → คืนยอดที่ลูกค้าโอนมา (มัดจำ + ค่ารับส่ง)

BANKS = [
    "กสิกรไทย", "กรุงเทพ", "ไทยพาณิชย์", "กรุงไทย", "กรุงศรีอยุธยา", "ทหารไทยธนชาต (ttb)",
    "ออมสิน", "ธ.ก.ส.", "ยูโอบี", "ซีไอเอ็มบี ไทย", "เกียรตินาคินภัทร", "แลนด์ แอนด์ เฮ้าส์",
]
ACTIVE = {"pending", "confirmed"}
MAX_VERIFY_FAILS = 5
_BOOKING_ID_RE = re.compile(r"^HH-\d{4}-\d{2,3}$")
_NOT_MATCH = "ข้อมูลไม่ตรงกับการจอง ตรวจเลขจอง เบอร์โทร และชื่อเจ้าของให้ตรงกับใบจองนะคะ"
_LOCKED = "ยืนยันตัวตนผิดหลายครั้ง ระบบล็อกการยกเลิกออนไลน์ของคิวนี้ไว้ 24 ชั่วโมง รบกวนติดต่อร้านทาง LINE หรือโทรค่ะ"


def cancel_hours() -> int:
    return slots.config()["cancel_hours_before"]


def cancel_deadline(b: dict):
    return slots.parse_key(b["slot"]) - timedelta(hours=cancel_hours())


def can_cancel(b: dict, at=None) -> bool:
    return b["status"] in ACTIVE and (at or slots.now()) <= cancel_deadline(b)


def cancel_view(b: dict, at=None) -> dict:
    """ส่วนของใบจองที่ปุ่มยกเลิกใช้ — ยอดคืน = ยอดที่ลูกค้าโอนมา (ไม่ใช่ราคาบริการ)"""
    active = b["status"] in ACTIVE and (at or slots.now()) < slots.parse_key(b["slot"])
    ok = can_cancel(b, at)
    return {
        "can_cancel": ok,
        "refund_amount": b.get("amount_due", deposit()) if ok else None,
        # ยังไม่ถึงเวลานัดแต่เลยกำหนดยกเลิกแล้ว → บอกเหตุผลแทนการซ่อนปุ่มเฉย ๆ
        "cancel_note": None if ok or not active else
        f"เหลือไม่ถึง {cancel_hours()} ชั่วโมงก่อนนัด ยกเลิกออนไลน์ไม่ได้ ติดต่อร้านทาง LINE หรือโทรได้เลยค่ะ",
    }


def clean_refund(method: str | None, bank: str | None, account: str | None, account_name: str | None) -> dict:
    """ช่องทางรับเงินคืน — พร้อมเพย์ (เบอร์ 10 หลัก / เลขบัตร 13 หลัก) หรือบัญชีธนาคาร (10–15 หลัก)"""
    digits = re.sub(r"\D", "", account or "")
    if method == "promptpay":
        if not (_PHONE_RE.match(digits) or len(digits) == 13):
            raise BookingError("พร้อมเพย์ต้องเป็นเบอร์โทร 10 หลัก หรือเลขบัตรประชาชน 13 หลัก", field="account")
        bank = None
    elif method == "bank":
        if bank not in BANKS:
            raise BookingError("กรุณาเลือกธนาคาร", field="bank")
        if not 10 <= len(digits) <= 15:
            raise BookingError("เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก", field="account")
    else:
        raise BookingError("กรุณาเลือกช่องทางรับเงินคืน", field="method")
    name = clean_name(account_name, "ชื่อบัญชี", "account_name")
    return {"method": method, "bank": bank, "account": digits, "account_name": name}


def _name_key(name: str | None) -> str:
    """เทียบชื่อเจ้าของแบบไม่สนช่องว่าง/ตัวพิมพ์/คำว่า "คุณ" นำหน้า"""
    text = re.sub(r"\s+", "", (name or "")).casefold()
    return text[3:] if text.startswith("คุณ") else text


async def verify_owner(booking_id: str | None, phone: str | None, owner_name: str | None) -> dict:
    """ยืนยันว่าเป็นเจ้าของคิวจริง — ไม่บอกว่าช่องไหนผิด (กันไล่เดาทีละช่อง)"""
    bid = (booking_id or "").strip().upper()
    if not _BOOKING_ID_RE.match(bid):
        raise BookingError("เลขจองดูได้บนใบจอง เช่น HH-1004-01", field="booking_id")
    phone = clean_phone(phone)
    if not (owner_name or "").strip():
        raise BookingError("กรุณากรอกชื่อเจ้าของตามที่กรอกตอนจอง", field="owner_name")
    store = get_store()
    if await store.cancel_fails(bid) >= MAX_VERIFY_FAILS:
        raise BookingError(_LOCKED, status=423)
    b = await store.get(bid)
    if not b or b.get("phone") != phone or _name_key(b.get("owner_name")) != _name_key(owner_name):
        if b and await store.add_cancel_fail(bid) >= MAX_VERIFY_FAILS:
            logger.warning("ล็อกการยกเลิกออนไลน์ %s (ยืนยันตัวตนผิดครบ %d ครั้ง)", bid, MAX_VERIFY_FAILS)
            raise BookingError(_LOCKED, status=423)
        raise BookingError(_NOT_MATCH, status=404)
    return b


def verify_view(b: dict) -> dict:
    """สิ่งที่แสดงหลังยืนยันตัวตนผ่าน ให้ลูกค้าเช็คว่าเป็นคิวที่ตั้งใจจะยกเลิก"""
    return {
        "id": b["id"],
        "pet_name": b["pet_name"],
        "pets": b.get("pets", 1),
        "service_label": service_label(b),
        "slot_label": _when(b),
        "status": b["status"],
        "status_label": STATUS_LABEL.get(b["status"], b["status"]),
        "pickup_time": (b.get("pickup") or {}).get("time"),
        **cancel_view(b),
    }


async def cancel_by_owner(booking_id, phone, owner_name, refund: dict, at=None) -> dict:
    """ยกเลิกคิวหลังยืนยันตัวตน → สถานะยกเลิก + คำขอคืนเงินให้ร้านโอน"""
    b = await verify_owner(booking_id, phone, owner_name)
    if b["status"] == "cancelled":
        raise BookingError("คิวนี้ถูกยกเลิกไปแล้ว", status=409)
    if not can_cancel(b, at):
        raise BookingError(cancel_view(b, at)["cancel_note"] or "คิวนี้ยกเลิกไม่ได้แล้ว", status=409)
    info = clean_refund(**refund)
    payer = (b.get("slip") or {}).get("sender_name")
    info.update(payer_name=payer, payer_match=slip_check.payer_matches(payer, info["account_name"]))
    store = get_store()
    if not await store.claim_cancel(b["id"]):
        raise BookingError("คิวนี้ถูกยกเลิกไปแล้ว", status=409)
    stamp = (at or slots.now()).isoformat(timespec="seconds")
    b.update(
        status="cancelled",
        cancelled_by="customer",
        updated_at=stamp,
        # payment_verified = ร้านเคยยืนยันยอดเข้าบัญชีของคิวนี้แล้วหรือยัง
        # ยัง (ยกเลิกตอน "รอร้านยืนยัน") = สลิปอาจถูกแก้ชื่อผู้รับ/เป็นสลิปปลอม → ร้านต้องตรวจบัญชีก่อนโอนคืน
        refund={**info, "amount": b.get("amount_due", deposit()), "status": "pending", "requested_at": stamp,
                "payment_verified": bool(b.get("confirmed_at"))},
    )
    await store.save(b)
    await _release(store, slots_used(b))
    logger.info("ลูกค้ายกเลิก %s ขอคืน %s บาท", b["id"], b["refund"]["amount"])
    return b


def payment_verified(refund: dict) -> bool:
    """คำขอคืนเงินรุ่นก่อนมีฟิลด์นี้ ถือว่ายังไม่ได้ตรวจ (ปลอดภัยไว้ก่อน)"""
    return bool(refund.get("payment_verified"))


async def _pending_refund(booking_id: str):
    store = get_store()
    b = await store.get(booking_id)
    if not b:
        raise BookingError("ไม่พบการจองนี้", status=404)
    refund = b.get("refund")
    if not refund or refund.get("status") != "pending":
        raise BookingError("คิวนี้ไม่มีรายการรอโอนคืน", status=409)
    return store, b, refund


async def mark_refunded(booking_id: str, proof: bytes | None, payment_checked: bool = False) -> dict:
    """หลังบ้าน: ร้านโอนคืนให้ลูกค้าแล้ว — ต้องแนบสลิปโอนคืน (ลูกค้าดูได้ที่หน้าเช็คคิวหลังยืนยันตัวตน)

    คิวที่ถูกยกเลิกก่อนร้านยืนยันยอด: ต้องยืนยันมาด้วยว่าตรวจบัญชีแล้วเงินเข้าจริง (payment_checked)
    กันกรณีจองด้วยสลิปแก้ชื่อ/สลิปปลอม แล้วรีบยกเลิกเพื่อขอ "เงินคืน" ที่ไม่เคยโอนมา"""
    store, b, refund = await _pending_refund(booking_id)
    if not payment_verified(refund) and not payment_checked:
        raise BookingError(
            "คิวนี้ถูกยกเลิกก่อนร้านยืนยันยอดมัดจำ กรุณาตรวจว่าเงินเข้าบัญชีจริงก่อนโอนคืน แล้วติ๊กยืนยัน",
            status=409, field="payment_checked")
    _check_image(proof, "สลิปโอนคืน", "proof")
    if not payment_verified(refund):
        refund.update(payment_verified=True, payment_checked_at=slots.now().isoformat(timespec="seconds"))
    await store.save_image(booking_id, "refund", proof)
    stamp = slots.now().isoformat(timespec="seconds")
    refund.update(status="done", refunded_at=stamp, proof=True)
    b["updated_at"] = stamp
    await store.save(b)
    logger.info("โอนคืนแล้ว %s", booking_id)
    return admin_view(b)


async def reject_refund(booking_id: str) -> dict:
    """หลังบ้าน: ตรวจบัญชีแล้วไม่พบยอดมัดจำของคิวนี้ → ไม่คืนเงิน (ลูกค้าเห็นที่หน้าเช็คคิวให้ติดต่อร้าน)
    ใช้ได้เฉพาะคิวที่ร้านยังไม่เคยยืนยันยอด — คิวที่ยืนยันแล้วต้องคืนตามนโยบาย"""
    store, b, refund = await _pending_refund(booking_id)
    if payment_verified(refund):
        raise BookingError("คิวนี้ร้านยืนยันยอดมัดจำไปแล้ว ปฏิเสธการคืนเงินไม่ได้", status=409)
    stamp = slots.now().isoformat(timespec="seconds")
    refund.update(status="rejected", rejected_at=stamp)
    b["updated_at"] = stamp
    await store.save(b)
    logger.warning("ปฏิเสธการคืนเงิน %s: ไม่พบยอดมัดจำเข้าบัญชี", booking_id)
    return admin_view(b)


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
        pickup=b.get("pickup"),
        amount_due=b.get("amount_due", deposit()),
        refund=b.get("refund"),
        cancelled_by=b.get("cancelled_by"),
        slots_used=[list(x) for x in slots_used(b)],
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
    if status == "cancelled" and not await store.claim_cancel(booking_id):
        raise BookingError("คิวนี้ถูกยกเลิกไปแล้ว", status=409)
    b["status"] = status
    b["updated_at"] = slots.now().isoformat(timespec="seconds")
    if status == "confirmed":
        # ร้านกดยืนยัน = ตรวจแล้วว่ายอดมัดจำเข้าบัญชีจริง (ใช้ตัดสินตอนคืนเงินว่าเงินเคยเข้าหรือยัง)
        b["confirmed_at"] = b["updated_at"]
    if status == "cancelled":
        b["cancelled_by"] = "shop"
    await store.save(b)
    if status == "cancelled":
        # คืนช่องเวลาให้ลูกค้าคนอื่นจองได้ทันที (เลขสลิปยังถือว่าใช้แล้ว — มัดจำตามนโยบายร้าน)
        await _release(store, slots_used(b))
    logger.info("เปลี่ยนสถานะ %s → %s", booking_id, status)
    return admin_view(b)


# ---------------- หน้าเช็คคิว (/check) ----------------

STATUS_HINT = {
    "pending": "ร้านกำลังตรวจยอดมัดจำ จะยืนยันคิวให้เร็ว ๆ นี้",
    "confirmed": "ร้านยืนยันคิวแล้ว แสดงใบจองที่หน้าร้านได้เลย",
    "done": "มาใช้บริการแล้ว ขอบคุณที่ไว้ใจ Hom Hom Grooming",
    "cancelled": "คิวนี้ถูกยกเลิก สอบถามร้านทาง LINE หรือโทรได้เลย",
}


def _hint(b: dict) -> str:
    refund = b.get("refund")
    if refund:
        amount = f"{refund['amount']:,} บาท"
        if refund["status"] == "done":
            return f"ยกเลิกแล้ว ร้านโอนคืน {amount} แล้ว"
        if refund["status"] == "rejected":
            return "ยกเลิกแล้ว ร้านตรวจไม่พบยอดมัดจำของคิวนี้ จึงยังไม่มีการคืนเงิน รบกวนติดต่อร้านทาง LINE หรือโทรค่ะ"
        if not payment_verified(refund):
            return f"ยกเลิกแล้ว ร้านจะตรวจยอดมัดจำเข้าบัญชีก่อน แล้วโอนคืน {amount} เข้าบัญชีที่แจ้งไว้"
        return f"ยกเลิกแล้ว ร้านจะโอนคืน {amount} เข้าบัญชีที่แจ้งไว้"
    return STATUS_HINT.get(b["status"], "")


def refund_view(b: dict) -> dict:
    """สถานะคืนเงินบนหน้าเช็คคิว — ไม่มีเลขบัญชี/ชื่อบัญชี (ค้นด้วยเบอร์โทรอย่างเดียว)"""
    refund = b.get("refund")
    if not refund:
        return {"refund_status": None}
    return {
        "refund_status": refund["status"],
        "refund_status_label": {"done": "โอนคืนแล้ว", "rejected": "ไม่พบยอดมัดจำ ยังไม่คืนเงิน"}.get(
            refund["status"], "รอร้านโอนคืน" if payment_verified(refund) else "รอร้านตรวจยอดก่อนโอนคืน"),
        "refund_amount": refund["amount"],
        "refunded_at": refund.get("refunded_at"),
        "refund_proof": bool(refund.get("proof")),
    }


async def refund_proof(booking_id, phone, owner_name) -> bytes:
    """สลิปโอนคืนให้ลูกค้าดู — ยืนยันตัวตนซ้ำ (สลิปมีชื่อ/เลขบัญชีของลูกค้า ห้ามเห็นแค่เพราะรู้เบอร์)"""
    b = await verify_owner(booking_id, phone, owner_name)
    refund = b.get("refund") or {}
    if refund.get("status") != "done" or not refund.get("proof"):
        raise BookingError("ร้านยังไม่ได้แนบสลิปโอนคืนของคิวนี้", status=404)
    data = await get_store().get_image(b["id"], "refund")
    if not data:
        raise BookingError("ร้านยังไม่ได้แนบสลิปโอนคืนของคิวนี้", status=404)
    return data


def check_view(b: dict) -> dict:
    """ข้อมูลที่หน้าเช็คคิวแสดงได้ — ค้นด้วยเบอร์โทรอย่างเดียว จึงไม่แสดงชื่อเจ้าของ/รูป/สลิป"""
    return {
        "id": b["id"],
        "pet_name": b["pet_name"],
        "pets": b.get("pets", 1),
        "service_label": service_label(b),
        "slot": b["slot"],
        "slot_label": _when(b),
        "status": b["status"],
        "status_label": STATUS_LABEL.get(b["status"], b["status"]),
        "status_hint": _hint(b),
        "pickup_time": (b.get("pickup") or {}).get("time"),
        "can_cancel": can_cancel(b),
        **refund_view(b),
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

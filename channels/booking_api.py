"""API จองคิวฝั่งลูกค้า (หน้าต่างแชทบนเว็บ) — ใช้ session cookie ตัวเดียวกับแชท

ตรรกะการจองทั้งหมดอยู่ที่ booking/service.py ไฟล์นี้แค่รับ/ส่งข้อมูลแบบ HTTP
"""

import logging

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from booking import pickup, service, slots
from booking.service import BookingError
from booking.store import StoreError, get_store
from channels.web_chat import _resolve_session, _set_session_cookie
from guardrails.input_rules import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/booking")

# จองแต่ละครั้งส่งสลิปไปให้ Gemini อ่าน — จำกัดถี่กว่าแชทเพื่อกันยิงรัว ๆ จนโควตาหมด
# นับ 2 ชั้น: ต่อ session (ลูกค้าทั่วไป) และต่อ IP (กันคนที่ไม่ส่ง cookie กลับมาเพื่อได้ session ใหม่ทุกครั้ง)
_attempts = RateLimiter(limit=5)
_attempts_ip = RateLimiter(limit=20)
# หน้าเช็คคิวค้นด้วยเบอร์โทร — จำกัดถี่กันไล่เดาเบอร์คนอื่น
_checks = RateLimiter(limit=10)
_checks_ip = RateLimiter(limit=10)
_IMAGE_KINDS = {"pet"}  # สลิปให้ดูเฉพาะหลังบ้าน (channels/admin.py)


def _error(status: int, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": True, "message": message, "field": field})


def _client_ip(request: Request) -> str:
    # บน Vercel IP จริงอยู่ใน x-forwarded-for ตัวแรก
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


async def _read(upload: UploadFile | None) -> bytes | None:
    if upload is None:
        return None
    # อ่านเกินเพดานมา 1 byte พอรู้ว่าใหญ่เกิน ไม่ต้องอ่านทั้งไฟล์ลงหน่วยความจำ
    return await upload.read(service.MAX_IMAGE_BYTES + 1)


@router.get("/slots")
async def get_slots():
    """ช่องเวลาที่จองได้ + จำนวนที่ว่าง (หน้าเว็บวาดปฏิทินจากตรงนี้)"""
    try:
        counts = await get_store().slot_counts(slots.all_keys())
    except StoreError as exc:
        return _error(503, str(exc))
    return {"days": slots.availability(counts), "capacity": slots.config()["capacity_per_slot"]}


@router.get("/pickup")
async def get_pickup(lat: float | None = None, lng: float | None = None):
    """ไม่มีพิกัด = ข้อมูลวาดแผนที่ (ตำแหน่งร้าน + ตารางค่ารับส่ง) · มีพิกัด = ระยะทาง + ค่ารับส่งของจุดนั้น
    หน้าเว็บใช้แสดงผลเท่านั้น ตอนจองจริงเซิร์ฟเวอร์คิดใหม่เองทุกครั้ง"""
    if lat is None or lng is None:
        return pickup.public_config()
    try:
        q = pickup.quote(lat, lng)
    except pickup.PickupError as exc:
        return _error(422, str(exc), "pickup")
    return {"km": q["km"], "fee": q["fee"], "deposit": service.deposit(), "total": service.deposit() + q["fee"]}


@router.post("")
async def post_booking(
    request: Request,
    pet_name: str = Form(""),
    owner_name: str = Form(""),
    phone: str = Form(""),
    slot: str = Form(""),
    pet_photo: UploadFile | None = File(None),
    slip: UploadFile | None = File(None),
    want_pickup: str = Form(""),
    pickup_lat: str = Form(""),
    pickup_lng: str = Form(""),
    pickup_address: str = Form(""),
):
    session_id, is_new = _resolve_session(request)
    ride = {"lat": pickup_lat, "lng": pickup_lng, "address": pickup_address} if want_pickup else None
    resp = await _create(request, session_id, pet_name, owner_name, phone, slot, pet_photo, slip, ride)
    if is_new:
        # ส่ง cookie กลับทุกกรณี (รวมตอน error) — ไม่งั้นคนที่จองไม่ผ่านจะได้ session ใหม่ทุกครั้งและหลุด rate limit
        _set_session_cookie(resp, session_id)
    return resp


async def _create(request, session_id, pet_name, owner_name, phone, slot, pet_photo, slip, ride) -> JSONResponse:
    if not _attempts.allow(session_id) or not _attempts_ip.allow(_client_ip(request)):
        return _error(429, "ส่งคำขอจองถี่เกินไป รอสักครู่แล้วลองใหม่นะคะ")
    try:
        booking = await service.create(
            session_id,
            pet_name=pet_name,
            owner_name=owner_name,
            phone=phone,
            slot=slot,
            pet_photo=await _read(pet_photo),
            slip=await _read(slip),
            pickup=ride,
        )
    except BookingError as exc:
        return _error(exc.status, exc.message, exc.field)
    except StoreError as exc:
        return _error(503, str(exc))

    return JSONResponse(status_code=201, content={"ok": True, "booking": service.public_view(booking)})


class CheckRequest(BaseModel):
    phone: str = ""


@router.post("/check")
async def check_by_phone(body: CheckRequest, request: Request):
    """หน้าเช็คคิว: ใส่เบอร์ที่ใช้จอง → ชื่อน้อง วันเวลา เลขจอง สถานะ (ไม่มีชื่อเจ้าของ/รูป/สลิป)
    ใช้ POST เพื่อไม่ให้เบอร์โทรไปอยู่ใน URL / log ของเซิร์ฟเวอร์"""
    session_id, is_new = _resolve_session(request)
    if not _checks.allow(session_id) or not _checks_ip.allow(_client_ip(request)):
        resp = _error(429, "ค้นหาถี่เกินไป รอสักครู่แล้วลองใหม่นะคะ")
    else:
        try:
            resp = JSONResponse({"bookings": await service.lookup_by_phone(body.phone)})
        except BookingError as exc:
            resp = _error(exc.status, exc.message, exc.field)
        except StoreError as exc:
            resp = _error(503, str(exc))
    if is_new:
        _set_session_cookie(resp, session_id)
    return resp


@router.get("/mine")
async def get_mine(request: Request):
    session_id, _ = _resolve_session(request)
    try:
        return {"bookings": await service.list_for_session(session_id)}
    except StoreError as exc:
        return _error(503, str(exc))


@router.get("/{booking_id}/image/{kind}")
async def get_image(booking_id: str, kind: str, request: Request):
    """รูปน้องบนใบจอง — เฉพาะเจ้าของการจอง (คนอื่นได้ 404 เหมือนไม่มีการจองนี้)"""
    session_id, _ = _resolve_session(request)
    if kind not in _IMAGE_KINDS:
        return _error(404, "ไม่พบรูป")
    try:
        if not await service.get_owned(booking_id, session_id):
            return _error(404, "ไม่พบการจองนี้")
        data = await get_store().get_image(booking_id, kind)
    except StoreError as exc:
        return _error(503, str(exc))
    if not data:
        return _error(404, "ไม่พบรูป")
    return Response(
        content=data,
        media_type=service.sniff_image(data) or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=86400"},
    )

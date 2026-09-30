"""หลังบ้านเจ้าของร้าน: login ด้วยรหัสผ่าน + API ดู/เปลี่ยนสถานะการจอง

- รหัสผ่านอยู่ใน env (ADMIN_PASSWORD) · ไม่ตั้ง = ปิดหลังบ้านทั้งหมด
- cookie เก็บแค่ "เวลาหมดอายุ.ลายเซ็น HMAC" ไม่มีข้อมูลลับ · SameSite=Strict กันเว็บอื่นยิงคำสั่งแทน
- login ผิดถูกจำกัด 5 ครั้ง/นาที/IP กันเดารหัสผ่าน
- หน้า /admin (HTML) อยู่ใน main.py เหมือนหน้าอื่น ไฟล์นี้มีแค่ login/logout + API
"""

import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from booking import service, slots
from booking.service import BookingError
from booking.store import StoreError, get_store
from config import settings
from guardrails.input_rules import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()

COOKIE = "hh_admin"
MAX_RANGE_DAYS = 62  # ดูได้ทีละไม่เกิน ~2 เดือน (มุมมองรายเดือน + เผื่อขอบปฏิทิน)
_login_attempts = RateLimiter(limit=5)


# ---------------- ยืนยันตัวตน ----------------

def _key() -> bytes | None:
    if not settings.ADMIN_PASSWORD:
        return None
    base = settings.ADMIN_SECRET or f"hh-admin:{settings.ADMIN_PASSWORD}"
    return hashlib.sha256(base.encode()).digest()


def _sign(exp: str) -> str:
    return hmac.new(_key(), exp.encode(), hashlib.sha256).hexdigest()


def make_token(now: float | None = None) -> str:
    exp = str(int((now or time.time()) + settings.ADMIN_SESSION_HOURS * 3600))
    return f"{exp}.{_sign(exp)}"


def is_admin(request: Request) -> bool:
    if not _key():
        return False
    exp, _, sig = request.cookies.get(COOKIE, "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(exp))


def enabled() -> bool:
    return _key() is not None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@router.post("/admin/login")
async def login(request: Request, password: str = Form("")):
    if not enabled():
        return RedirectResponse("/admin?e=off", status_code=303)
    if not _login_attempts.allow(_client_ip(request)):
        return RedirectResponse("/admin?e=wait", status_code=303)
    if not hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode()):
        logger.warning("login หลังบ้านไม่สำเร็จจาก %s", _client_ip(request))
        return RedirectResponse("/admin?e=wrong", status_code=303)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        COOKIE,
        make_token(),
        httponly=True,
        samesite="strict",
        secure=_is_https(request),
        max_age=settings.ADMIN_SESSION_HOURS * 3600,
    )
    return resp


@router.post("/admin/logout")
async def logout():
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------------- API ----------------

def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": True, "message": message})


def _denied() -> JSONResponse:
    return _error(401, "กรุณาเข้าสู่ระบบหลังบ้านอีกครั้ง")


def _day(value: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(value) if value else fallback
    except ValueError:
        return fallback


@router.get("/api/v1/admin/bookings")
async def list_bookings(request: Request, start: str | None = None, end: str | None = None):
    """การจองที่นัดอยู่ในช่วงวันที่ [start, end) — ค่าเริ่มต้นคือ 7 วันจากวันนี้"""
    if not is_admin(request):
        return _denied()
    today = slots.now().date()
    d1 = _day(start, today)
    d2 = _day(end, d1 + timedelta(days=7))
    if d2 <= d1 or (d2 - d1).days > MAX_RANGE_DAYS:
        return _error(422, f"ช่วงวันที่ต้องยาว 1–{MAX_RANGE_DAYS} วัน")
    t1 = datetime.combine(d1, datetime.min.time(), slots.TZ)
    t2 = datetime.combine(d2, datetime.min.time(), slots.TZ)
    try:
        bookings = await service.list_between(t1, t2)
    except StoreError as exc:
        return _error(503, str(exc))
    cfg = slots.config()
    return {
        "start": d1.isoformat(),
        "end": d2.isoformat(),
        "bookings": bookings,
        "hours": {"open": cfg["open"], "last_start": cfg["last_start"], "slot_minutes": cfg["slot_minutes"]},
        "closed_weekdays": cfg["closed_weekdays"],
        "capacity": cfg["capacity_per_slot"],
        "today": today.isoformat(),
    }


@router.get("/api/v1/admin/bookings/{booking_id}")
async def get_booking(booking_id: str, request: Request):
    if not is_admin(request):
        return _denied()
    try:
        b = await get_store().get(booking_id.strip().upper())
    except StoreError as exc:
        return _error(503, str(exc))
    if not b:
        return _error(404, "ไม่พบเลขจองนี้")
    return {"booking": service.admin_view(b)}


class StatusRequest(BaseModel):
    status: str


@router.post("/api/v1/admin/bookings/{booking_id}/status")
async def change_status(booking_id: str, body: StatusRequest, request: Request):
    if not is_admin(request):
        return _denied()
    try:
        return {"booking": await service.set_status(booking_id, body.status)}
    except BookingError as exc:
        return _error(exc.status, exc.message)
    except StoreError as exc:
        return _error(503, str(exc))


@router.get("/api/v1/admin/bookings/{booking_id}/image/{kind}")
async def admin_image(booking_id: str, kind: str, request: Request):
    if not is_admin(request):
        return _denied()
    if kind not in {"pet", "slip"}:
        return _error(404, "ไม่พบรูป")
    try:
        data = await get_store().get_image(booking_id, kind)
    except StoreError as exc:
        return _error(503, str(exc))
    if not data:
        return _error(404, "ไม่พบรูป")
    return Response(
        content=data,
        media_type=service.sniff_image(data) or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )

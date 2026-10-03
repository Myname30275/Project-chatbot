"""ที่เก็บข้อมูลการจอง — in-memory (รันในเครื่อง/เทส) หรือ Redis/Vercel KV (บน Vercel)

ต่างจาก conversation_store ตรงที่ Redis ล่มแล้ว "ต้อง error" ไม่ทำงานต่อเงียบ ๆ:
การจองที่ไม่ถูกบันทึกแต่ลูกค้าได้ใบจองไปแล้ว แย่กว่าบอกให้ลองใหม่

key ใน Redis (ดู docs/booking-plan.md §5)
  booking:<id>                 JSON ข้อมูลการจอง (ไม่มีราคา)
  booking_img:<id>:<kind>      รูป base64 (kind = pet | slip) ย่อมาจากเบราว์เซอร์แล้ว
  bookings:by_time             sorted set  score = เวลานัด (epoch)  member = id
  bookings:session:<sid>       list ของ id ของ session นั้น ("ใบจองของฉัน")
  bookings:phone:<phone>       list ของ id ตามเบอร์โทร (หน้าเช็คคิว /check)
  slotcount:<slot>             ตัวนับคิวในช่องเวลา (INCR แบบ atomic กันจองซ้อน)
  slipref:<reference>          id ของการจองที่ใช้สลิปใบนี้ (SET NX กันใช้สลิปซ้ำ)
  cancel:<id>                  ธงว่ายกเลิกแล้ว (SET NX กันกดยกเลิกซ้ำแล้วคืนช่องเวลา 2 ครั้ง)
  seq:<YYYYMMDD>               ตัวนับเลขจองรายวัน
"""

import base64
import json
import logging
from abc import ABC, abstractmethod

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TTL_BOOKING = 60 * 60 * 24 * 180   # เก็บการจอง 180 วัน
_TTL_COUNTER = 60 * 60 * 24 * 30    # ตัวนับช่องเวลา/เลขจอง — จองล่วงหน้าได้ไม่เกิน 14 วัน 30 วันจึงพอ
_REDIS_TIMEOUT = 10.0


class StoreError(Exception):
    """ที่เก็บข้อมูลใช้ไม่ได้ — ให้ API ตอบ 503 แทนการทำเหมือนจองสำเร็จ"""


class BookingStore(ABC):
    @abstractmethod
    async def reserve_slot(self, slot: str, capacity: int) -> bool:
        """กันที่ 1 คิวในช่องเวลา — เต็มแล้วคืน False (ไม่นับเพิ่ม)"""

    @abstractmethod
    async def release_slot(self, slot: str) -> None: ...

    @abstractmethod
    async def slot_counts(self, slots: list[str]) -> dict[str, int]: ...

    @abstractmethod
    async def claim_slip_ref(self, reference: str, booking_id: str) -> bool:
        """จองเลขอ้างอิงสลิป — เคยใช้แล้วคืน False"""

    @abstractmethod
    async def release_slip_ref(self, reference: str) -> None: ...

    @abstractmethod
    async def claim_cancel(self, booking_id: str) -> bool:
        """ปักธงยกเลิก — เคยยกเลิกไปแล้วคืน False (ลูกค้ากับร้านกดพร้อมกันก็คืนช่องเวลาแค่ครั้งเดียว)"""

    @abstractmethod
    async def next_seq(self, day: str) -> int: ...

    @abstractmethod
    async def save(self, booking: dict) -> None: ...

    @abstractmethod
    async def get(self, booking_id: str) -> dict | None: ...

    @abstractmethod
    async def index(self, booking: dict) -> None:
        """ลงดัชนีตามเวลานัด + ผูกกับ session (เรียกครั้งเดียวตอนสร้าง)"""

    @abstractmethod
    async def ids_between(self, start_ts: float, end_ts: float) -> list[str]: ...

    @abstractmethod
    async def session_ids(self, session_id: str) -> list[str]: ...

    @abstractmethod
    async def phone_ids(self, phone: str) -> list[str]: ...

    @abstractmethod
    async def save_image(self, booking_id: str, kind: str, data: bytes) -> None: ...

    @abstractmethod
    async def get_image(self, booking_id: str, kind: str) -> bytes | None: ...


class InMemoryBookingStore(BookingStore):
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._refs: dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._seq: dict[str, int] = {}
        self._bookings: dict[str, dict] = {}
        self._by_time: dict[str, float] = {}
        self._sessions: dict[str, list[str]] = {}
        self._phones: dict[str, list[str]] = {}
        self._images: dict[tuple[str, str], bytes] = {}

    async def reserve_slot(self, slot, capacity):
        if self._counts.get(slot, 0) >= capacity:
            return False
        self._counts[slot] = self._counts.get(slot, 0) + 1
        return True

    async def release_slot(self, slot):
        self._counts[slot] = max(0, self._counts.get(slot, 0) - 1)

    async def slot_counts(self, slots):
        return {s: self._counts.get(s, 0) for s in slots}

    async def claim_slip_ref(self, reference, booking_id):
        if reference in self._refs:
            return False
        self._refs[reference] = booking_id
        return True

    async def release_slip_ref(self, reference):
        self._refs.pop(reference, None)

    async def claim_cancel(self, booking_id):
        if booking_id in self._cancelled:
            return False
        self._cancelled.add(booking_id)
        return True

    async def next_seq(self, day):
        self._seq[day] = self._seq.get(day, 0) + 1
        return self._seq[day]

    async def save(self, booking):
        self._bookings[booking["id"]] = json.loads(json.dumps(booking))

    async def get(self, booking_id):
        b = self._bookings.get(booking_id)
        return json.loads(json.dumps(b)) if b else None

    async def index(self, booking):
        self._by_time[booking["id"]] = booking["slot_ts"]
        self._sessions.setdefault(booking["session_id"], []).insert(0, booking["id"])
        self._phones.setdefault(booking["phone"], []).insert(0, booking["id"])

    async def ids_between(self, start_ts, end_ts):
        return [i for i, ts in sorted(self._by_time.items(), key=lambda x: x[1]) if start_ts <= ts < end_ts]

    async def session_ids(self, session_id):
        return list(self._sessions.get(session_id, []))

    async def phone_ids(self, phone):
        return list(self._phones.get(phone, []))

    async def save_image(self, booking_id, kind, data):
        self._images[(booking_id, kind)] = data

    async def get_image(self, booking_id, kind):
        return self._images.get((booking_id, kind))


class RedisBookingStore(BookingStore):
    """Upstash Redis REST API (ตัวเดียวกับ Vercel KV) — POST คำสั่งเป็น JSON array"""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _cmd(self, *args) -> object:
        try:
            async with httpx.AsyncClient(timeout=_REDIS_TIMEOUT) as client:
                r = await client.post(self._base_url, headers=self._headers, json=[str(a) for a in args])
                r.raise_for_status()
                body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Redis (booking) ใช้ไม่ได้: %s", exc)
            raise StoreError("ระบบจองขัดข้องชั่วคราว รบกวนลองใหม่อีกครั้ง") from exc
        if "error" in body:
            logger.error("Redis (booking) error: %s", body["error"])
            raise StoreError("ระบบจองขัดข้องชั่วคราว รบกวนลองใหม่อีกครั้ง")
        return body.get("result")

    async def reserve_slot(self, slot, capacity):
        n = int(await self._cmd("INCR", f"slotcount:{slot}"))
        await self._cmd("EXPIRE", f"slotcount:{slot}", _TTL_COUNTER)
        if n > capacity:
            await self._cmd("DECR", f"slotcount:{slot}")
            return False
        return True

    async def release_slot(self, slot):
        n = int(await self._cmd("DECR", f"slotcount:{slot}"))
        if n < 0:  # กันตัวนับติดลบจากการคืนซ้ำ
            await self._cmd("SET", f"slotcount:{slot}", 0, "EX", _TTL_COUNTER)

    async def slot_counts(self, slots):
        if not slots:
            return {}
        values = await self._cmd("MGET", *[f"slotcount:{s}" for s in slots]) or []
        return {s: max(0, int(v or 0)) for s, v in zip(slots, values)}

    async def claim_slip_ref(self, reference, booking_id):
        return await self._cmd("SET", f"slipref:{reference}", booking_id, "NX", "EX", _TTL_BOOKING) == "OK"

    async def release_slip_ref(self, reference):
        await self._cmd("DEL", f"slipref:{reference}")

    async def claim_cancel(self, booking_id):
        return await self._cmd("SET", f"cancel:{booking_id}", "1", "NX", "EX", _TTL_BOOKING) == "OK"

    async def next_seq(self, day):
        n = int(await self._cmd("INCR", f"seq:{day}"))
        await self._cmd("EXPIRE", f"seq:{day}", _TTL_COUNTER)
        return n

    async def save(self, booking):
        await self._cmd("SET", f"booking:{booking['id']}", json.dumps(booking, ensure_ascii=False), "EX", _TTL_BOOKING)

    async def get(self, booking_id):
        raw = await self._cmd("GET", f"booking:{booking_id}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            logger.error("ข้อมูลการจองเสียรูป %s", booking_id)
            return None
        return data if isinstance(data, dict) else None

    async def index(self, booking):
        await self._cmd("ZADD", "bookings:by_time", booking["slot_ts"], booking["id"])
        key = f"bookings:session:{booking['session_id']}"
        await self._cmd("LPUSH", key, booking["id"])
        await self._cmd("EXPIRE", key, _TTL_BOOKING)
        pkey = f"bookings:phone:{booking['phone']}"
        await self._cmd("LPUSH", pkey, booking["id"])
        await self._cmd("EXPIRE", pkey, _TTL_BOOKING)

    async def ids_between(self, start_ts, end_ts):
        # "(" = ไม่รวมขอบบน — ช่วง [start, end)
        return list(await self._cmd("ZRANGEBYSCORE", "bookings:by_time", start_ts, f"({end_ts}") or [])

    async def session_ids(self, session_id):
        return list(await self._cmd("LRANGE", f"bookings:session:{session_id}", 0, 49) or [])

    async def phone_ids(self, phone):
        return list(await self._cmd("LRANGE", f"bookings:phone:{phone}", 0, 49) or [])

    async def save_image(self, booking_id, kind, data):
        await self._cmd("SET", f"booking_img:{booking_id}:{kind}", base64.b64encode(data).decode(), "EX", _TTL_BOOKING)

    async def get_image(self, booking_id, kind):
        raw = await self._cmd("GET", f"booking_img:{booking_id}:{kind}")
        return base64.b64decode(raw) if raw else None


_store: BookingStore | None = None


def get_store() -> BookingStore:
    """เลือก backend ครั้งเดียวจาก env — ตั้ง Redis/Vercel KV ไว้ = Redis, ไม่ตั้ง = หน่วยความจำ"""
    global _store
    if _store is None:
        url, token = settings.redis_rest_url, settings.redis_rest_token
        _store = RedisBookingStore(url, token) if url and token else InMemoryBookingStore()
    return _store

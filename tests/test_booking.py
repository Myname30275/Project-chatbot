"""เทสระบบจองคิว (ไม่เรียก API จริง — Gemini ถูกจำลอง, ที่เก็บเป็น in-memory)"""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from booking import service, slots
from booking import store as store_module
from booking.service import BookingError
from booking.store import InMemoryBookingStore, StoreError
from channels import booking_api
from guardrails.input_rules import RateLimiter
from vision import image_analyzer
from vision.image_analyzer import ImageAnalysis, Slip, VisionError

# พฤ. 1 ต.ค. 2569 (2026) 10:00 น. เวลาไทย
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=slots.TZ)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


def run(coro):
    return asyncio.run(coro)


def first_open_day():
    return next(d for d in slots.bookable_days(NOW) if slots.day_slots(d))


def slot_at(hour=10):
    return f"{first_open_day().isoformat()}T{hour:02d}:00"


def good_slip(**kw):
    fields = {"amount": 50.0, "receiver_name": "Hom Hom Grooming", "reference": "REF001"}
    fields.update(kw)
    return ImageAnalysis("slip", slip=Slip(**fields))


def contains_key(obj, word):
    if isinstance(obj, dict):
        return any(word in k or contains_key(v, word) for k, v in obj.items())
    if isinstance(obj, list):
        return any(contains_key(v, word) for v in obj)
    return False


class SlotTests(unittest.TestCase):
    def test_bookable_days_start_tomorrow_and_stop_at_14(self):
        days = slots.bookable_days(NOW)
        self.assertEqual(days[0], NOW.date() + timedelta(days=1))
        self.assertEqual(days[-1], NOW.date() + timedelta(days=14))

    def test_monday_closed_and_open_days_have_8_hourly_slots(self):
        monday = next(d for d in slots.bookable_days(NOW) if d.weekday() == 0)
        self.assertEqual(slots.day_slots(monday), [])
        times = [s.strftime("%H:%M") for s in slots.day_slots(first_open_day())]
        self.assertEqual(times, ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"])

    def test_parse_slot_rejects_anything_not_offered(self):
        monday = next(d for d in slots.bookable_days(NOW) if d.weekday() == 0)
        for bad in [
            f"{NOW.date().isoformat()}T11:00",       # วันนี้ (ต้องล่วงหน้า 1 วัน)
            f"{monday.isoformat()}T10:00",           # วันจันทร์ร้านปิด
            f"{first_open_day().isoformat()}T10:30",  # ไม่ตรงช่อง
            f"{first_open_day().isoformat()}T17:00",  # หลังคิวสุดท้าย
            (NOW + timedelta(days=15)).strftime("%Y-%m-%dT10:00"),
            "พรุ่งนี้บ่ายสอง",
            "",
        ]:
            with self.subTest(bad=bad):
                self.assertIsNone(slots.parse_slot(bad, NOW))
        self.assertIsNotNone(slots.parse_slot(slot_at(), NOW))

    def test_availability_counts_left_per_slot(self):
        days = slots.availability({slot_at(10): 2, slot_at(11): 1}, NOW)
        day = next(d for d in days if d["date"] == first_open_day().isoformat())
        left = {s["time"]: s["left"] for s in day["slots"]}
        self.assertEqual((left["10:00"], left["11:00"], left["12:00"]), (0, 1, 2))
        self.assertIn(False, [d["open"] for d in days])  # วันจันทร์ส่งมาเป็นวันปิด

    def test_thai_label(self):
        self.assertEqual(slots.slot_label(slots.parse_key("2026-10-03T10:00")), "ส. 3 ต.ค. 2569 10:00 น.")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryBookingStore()
        self.analysis = good_slip()

        async def fake_analyze(data, mime):
            if isinstance(self.analysis, Exception):
                raise self.analysis
            return self.analysis

        for target, attr, value in [
            (store_module, "_store", self.store),
            (image_analyzer, "analyze", fake_analyze),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def book(self, **kw):
        fields = dict(pet_name="ถั่วแดง", owner_name="สมใจ", phone="081-234-5678",
                      slot=slot_at(), pet_photo=JPEG, slip=PNG, at=NOW)
        fields.update(kw)
        return run(service.create("sess-1", **fields))

    def count(self, slot=None):
        return run(self.store.slot_counts([slot or slot_at()]))[slot or slot_at()]

    def test_booking_is_pending_with_code_and_no_price(self):
        b = self.book()
        self.assertEqual(b["status"], "pending")
        self.assertRegex(b["id"], r"^HH-\d{4}-01$")
        self.assertTrue(b["slip"]["auto_ok"])
        self.assertEqual(b["phone"], "0812345678")
        self.assertFalse(contains_key(b, "price"))
        self.assertFalse(contains_key(service.public_view(b), "price"))
        self.assertEqual(service.public_view(b)["phone"], "081-xxx-5678")

    def test_slot_capacity_is_two(self):
        self.book(slip=PNG)
        self.analysis = good_slip(reference="REF002")
        self.book()
        self.analysis = good_slip(reference="REF003")
        with self.assertRaises(BookingError) as ctx:
            self.book()
        self.assertEqual((ctx.exception.status, ctx.exception.field), (409, "slot"))
        self.assertEqual(self.count(), 2)

    def test_rejected_slips_release_the_slot(self):
        for analysis, word in [
            (good_slip(amount=500.0), "500 บาท"),
            (good_slip(receiver_name="นาย ทดสอบ ปลอม"), "ไม่ใช่บัญชีของร้าน"),
            (ImageAnalysis("pet"), "ไม่ใช่สลิป"),
        ]:
            with self.subTest(word=word):
                self.analysis = analysis
                with self.assertRaises(BookingError) as ctx:
                    self.book()
                self.assertIn(word, ctx.exception.message)
                self.assertEqual(ctx.exception.field, "slip")
                self.assertEqual(self.count(), 0)

    def test_same_slip_cannot_book_twice(self):
        self.book()
        with self.assertRaises(BookingError) as ctx:
            self.book(slot=slot_at(11))
        self.assertIn("ถูกใช้จองคิวไปแล้ว", ctx.exception.message)
        self.assertEqual(self.count(slot_at(11)), 0)  # ช่องที่กันไว้ถูกคืน

    def test_vision_down_still_books_but_flags_for_owner(self):
        self.analysis = VisionError("down")
        b = self.book()
        self.assertFalse(b["slip"]["auto_ok"])
        self.assertEqual(b["status"], "pending")

    def test_unreadable_amount_is_accepted_for_manual_check(self):
        self.analysis = good_slip(amount=None, receiver_name=None)
        self.assertFalse(self.book()["slip"]["auto_ok"])

    def test_form_validation(self):
        for kw, field in [
            ({"phone": "12345"}, "phone"),
            ({"phone": "1812345678"}, "phone"),
            ({"pet_name": "   "}, "pet_name"),
            ({"owner_name": "ก" * 41}, "owner_name"),
            ({"pet_photo": None}, "pet_photo"),
            ({"pet_photo": b"GIF89a" + b"0" * 50}, "pet_photo"),
            ({"slip": JPEG + b"0" * service.MAX_IMAGE_BYTES}, "slip"),
            ({"slot": "2026-10-01T10:00"}, "slot"),
        ]:
            with self.subTest(kw=list(kw)):
                with self.assertRaises(BookingError) as ctx:
                    self.book(**kw)
                self.assertEqual(ctx.exception.field, field)
        self.assertEqual(self.count(), 0)

    def test_control_characters_are_stripped_from_names(self):
        b = self.book(pet_name="ถั่ว​แดง\n\n", owner_name="  สม   ใจ ")
        self.assertEqual((b["pet_name"], b["owner_name"]), ("ถั่วแดง", "สม ใจ"))


class ApiTests(unittest.TestCase):
    def setUp(self):
        from main import app

        async def fake_analyze(data, mime):
            return good_slip(reference=None)

        for target, attr, value in [
            (store_module, "_store", InMemoryBookingStore()),
            (image_analyzer, "analyze", fake_analyze),
            (slots, "now", lambda: NOW),
            (booking_api, "_attempts", RateLimiter(limit=5)),
            (booking_api, "_attempts_ip", RateLimiter(limit=20)),
            (booking_api, "_checks", RateLimiter(limit=10)),
            (booking_api, "_checks_ip", RateLimiter(limit=10)),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = app
        self.client = TestClient(app)

    def post(self, client=None, **fields):
        data = {"pet_name": "ถั่วแดง", "owner_name": "สมใจ", "phone": "0812345678", "slot": slot_at()}
        data.update(fields)
        files = {"pet_photo": ("pet.jpg", JPEG, "image/jpeg"), "slip": ("slip.png", PNG, "image/png")}
        return (client or self.client).post("/api/v1/booking", data=data, files=files)

    def test_slots_endpoint(self):
        body = self.client.get("/api/v1/booking/slots").json()
        self.assertEqual(body["capacity"], 2)
        self.assertEqual(len(body["days"]), 14)

    def test_book_then_see_own_ticket_and_images(self):
        r = self.post()
        self.assertEqual(r.status_code, 201)
        ticket = r.json()["booking"]
        self.assertEqual(ticket["status_label"], "รอร้านยืนยัน")
        self.assertFalse(contains_key(r.json(), "price"))
        self.assertNotIn("session_id", ticket)
        mine = self.client.get("/api/v1/booking/mine").json()["bookings"]
        self.assertEqual([b["id"] for b in mine], [ticket["id"]])
        img = self.client.get(ticket["pet_image"])
        self.assertEqual((img.status_code, img.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(img.content, JPEG)
        left = self.client.get("/api/v1/booking/slots").json()["days"]
        slot = next(s for d in left for s in d["slots"] if s["key"] == slot_at())
        self.assertEqual(slot["left"], 1)

    def test_ticket_has_no_slip_and_customer_cannot_fetch_slip(self):
        ticket = self.post().json()["booking"]
        self.assertFalse(contains_key(ticket, "slip"))  # สลิปอยู่เฉพาะหลังบ้าน
        own_slip = self.client.get(f"/api/v1/booking/{ticket['id']}/image/slip")
        self.assertEqual(own_slip.status_code, 404)

    def check(self, phone, client=None):
        return (client or self.client).post("/api/v1/booking/check", json={"phone": phone})

    def test_check_page_finds_bookings_by_phone_from_any_device(self):
        self.post(slot=slot_at(14))
        self.post(slot=slot_at(9), phone="081-234-5678")
        other_device = TestClient(self.app)  # ไม่มี cookie ของคนจอง — ค้นด้วยเบอร์อย่างเดียว
        r = self.check("081 234 5678", client=other_device)
        self.assertEqual(r.status_code, 200)
        found = r.json()["bookings"]
        self.assertEqual([b["slot"][11:] for b in found], ["09:00", "14:00"])  # นัดใกล้สุดก่อน
        self.assertEqual(found[0]["status_label"], "รอร้านยืนยัน")
        self.assertTrue(found[0]["status_hint"])
        # ค้นด้วยเบอร์อย่างเดียว จึงไม่ส่งชื่อเจ้าของ เบอร์ รูป สลิป หรือราคา
        for field in ("owner", "phone", "image", "slip", "price", "session"):
            self.assertFalse(contains_key(found, field), field)

    def test_check_other_phone_and_bad_input(self):
        self.post()
        self.assertEqual(self.check("0899999999").json()["bookings"], [])
        bad = self.check("12345")
        self.assertEqual((bad.status_code, bad.json()["field"]), (422, "phone"))

    def test_check_is_rate_limited(self):
        codes = [self.check("0899999999").status_code for _ in range(11)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10], 429)

    def test_check_page_renders(self):
        page = self.client.get("/check")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="check-form"', page.text)
        self.assertIn('href="/check"', self.client.get("/").text)  # มีเมนูบนหน้าแรก

    def test_other_customer_cannot_see_ticket_or_images(self):
        ticket = self.post().json()["booking"]
        stranger = TestClient(self.app)
        stranger.cookies.set("session_id", "someone-else")
        self.assertEqual(stranger.get(ticket["pet_image"]).status_code, 404)
        self.assertEqual(stranger.get("/api/v1/booking/mine").json()["bookings"], [])

    def test_validation_error_names_the_field(self):
        r = self.post(phone="08-1234")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["field"], "phone")

    def test_rate_limit_per_session_even_when_every_attempt_fails(self):
        first = self.post(phone="0")
        self.assertIn("session_id", first.cookies)  # error ก็ต้องได้ cookie ไม่งั้นหลุด limit
        codes = [self.post(phone="0").status_code for _ in range(5)]
        self.assertEqual(codes[-1], 429)

    def test_rate_limit_per_ip_for_clients_that_drop_cookies(self):
        codes = []
        for _ in range(21):
            fresh = TestClient(self.app)  # ไม่มี cookie ทุกครั้ง = session ใหม่ทุกครั้ง
            codes.append(self.post(client=fresh, phone="0").status_code)
        self.assertEqual(codes[:20], [422] * 20)
        self.assertEqual(codes[20], 429)

    def test_store_down_returns_503_not_success(self):
        async def broken(*a, **k):
            raise StoreError("ระบบจองขัดข้องชั่วคราว รบกวนลองใหม่อีกครั้ง")

        with patch.object(InMemoryBookingStore, "reserve_slot", broken):
            r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertIn("ขัดข้อง", r.json()["message"])


if __name__ == "__main__":
    unittest.main()

"""เทสหลังบ้านเจ้าของร้าน (/admin + /api/v1/admin/*) — ที่เก็บ in-memory, Gemini จำลอง"""

import asyncio
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from booking import service, slots
from booking import store as store_module
from booking.store import InMemoryBookingStore
from channels import admin, booking_api
from config import settings
from guardrails.input_rules import RateLimiter
from tests.test_booking import JPEG, NOW, PNG, good_slip, slot_at
from vision import image_analyzer

PASSWORD = "หอม-test-1234"


class AdminTests(unittest.TestCase):
    def setUp(self):
        from main import app

        self.store = InMemoryBookingStore()
        refs = iter(f"REF{i:03d}" for i in range(1, 100))

        self.payer = None  # ชื่อผู้โอนในสลิป (เทสเรื่องโอนคืนตั้งเอง)

        async def fake_analyze(data, mime):
            return good_slip(reference=next(refs), sender_name=self.payer)

        for target, attr, value in [
            (settings, "ADMIN_PASSWORD", PASSWORD),
            (settings, "ADMIN_SECRET", None),
            (store_module, "_store", self.store),
            (image_analyzer, "analyze", fake_analyze),
            (slots, "now", lambda: NOW),
            (booking_api, "_attempts", RateLimiter(limit=50)),
            (booking_api, "_attempts_ip", RateLimiter(limit=50)),
            (booking_api, "_cancels", RateLimiter(limit=50)),
            (admin, "_login_attempts", RateLimiter(limit=5)),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = app
        self.customer = TestClient(app)
        self.owner = TestClient(app)

    def book(self, hour=10):
        r = self.customer.post(
            "/api/v1/booking",
            data={"pet_name": "ถั่วแดง", "owner_name": "สมใจ", "phone": "0812345678", "slot": slot_at(hour)},
            files={"pet_photo": ("p.jpg", JPEG, "image/jpeg"), "slip": ("s.png", PNG, "image/png")},
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["booking"]

    def login(self, client=None, password=PASSWORD):
        return (client or self.owner).post("/admin/login", data={"password": password}, follow_redirects=False)

    def week(self):
        start = slots.parse_key(slot_at()).date().isoformat()
        return self.owner.get(f"/api/v1/admin/bookings?start={start}")

    # ---------- เข้าสู่ระบบ ----------

    def test_api_requires_login(self):
        b = self.book()
        for path in ["/api/v1/admin/bookings", f"/api/v1/admin/bookings/{b['id']}",
                     f"/api/v1/admin/bookings/{b['id']}/image/slip"]:
            with self.subTest(path=path):
                self.assertEqual(self.owner.get(path).status_code, 401)
        r = self.owner.post(f"/api/v1/admin/bookings/{b['id']}/status", json={"status": "confirmed"})
        self.assertEqual(r.status_code, 401)

    def test_page_shows_login_form_then_board(self):
        self.assertIn('action="/admin/login"', self.owner.get("/admin").text)
        r = self.login()
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/admin"))
        cookie = r.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        page = self.owner.get("/admin")
        self.assertIn('id="board"', page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")

    def test_wrong_password_and_login_rate_limit(self):
        self.assertEqual(self.login(password="ผิด").headers["location"], "/admin?e=wrong")
        for _ in range(4):
            self.login(password="ผิด")
        # ครั้งที่ 6 ภายในนาทีเดียว — แม้รหัสถูกก็ต้องรอ
        self.assertEqual(self.login().headers["location"], "/admin?e=wait")
        self.assertEqual(self.week().status_code, 401)

    def test_tampered_or_expired_cookie_is_rejected(self):
        self.login()
        token = self.owner.cookies.get(admin.COOKIE)
        exp, sig = token.split(".")
        for bad in [f"{int(exp) + 9999}.{sig}", f"{exp}.{'0' * len(sig)}", "garbage", ""]:
            with self.subTest(bad=bad):
                c = TestClient(self.app)
                c.cookies.set(admin.COOKIE, bad)
                self.assertEqual(c.get("/api/v1/admin/bookings").status_code, 401)
        old = admin.make_token(now=time.time() - settings.ADMIN_SESSION_HOURS * 3600 - 5)
        c = TestClient(self.app)
        c.cookies.set(admin.COOKIE, old)
        self.assertEqual(c.get("/api/v1/admin/bookings").status_code, 401)

    def test_disabled_without_password(self):
        with patch.object(settings, "ADMIN_PASSWORD", None):
            self.assertIn("ยังไม่ได้เปิดหลังบ้าน", self.owner.get("/admin").text)
            self.assertEqual(self.login().headers["location"], "/admin?e=off")
            self.assertEqual(self.week().status_code, 401)

    # ---------- ตารางคิว + สถานะ ----------

    def test_owner_sees_full_details_but_still_no_price(self):
        b = self.book()
        self.login()
        body = self.week().json()
        self.assertEqual(body["capacity"], 2)
        [row] = body["bookings"]
        self.assertEqual((row["id"], row["phone"], row["status"]), (b["id"], "0812345678", "pending"))
        self.assertTrue(row["slip"]["auto_ok"])
        self.assertEqual(row["next_status"], ["cancelled", "confirmed"])
        self.assertFalse(any("price" in k for k in row))
        img = self.owner.get(f"/api/v1/admin/bookings/{b['id']}/image/slip")
        self.assertEqual((img.status_code, img.content), (200, PNG))

    def test_confirm_updates_customer_ticket(self):
        b = self.book()
        self.login()
        r = self.owner.post(f"/api/v1/admin/bookings/{b['id']}/status", json={"status": "confirmed"})
        self.assertEqual(r.json()["booking"]["status_label"], "ยืนยันแล้ว")
        mine = self.customer.get("/api/v1/booking/mine").json()["bookings"]
        self.assertEqual(mine[0]["status_label"], "ยืนยันแล้ว")
        checked = TestClient(self.app).post("/api/v1/booking/check", json={"phone": "0812345678"}).json()
        self.assertEqual(checked["bookings"][0]["status_label"], "ยืนยันแล้ว")  # หน้าเช็คคิวเห็นสถานะใหม่

    def test_illegal_transitions_are_refused(self):
        b = self.book()
        self.login()
        url = f"/api/v1/admin/bookings/{b['id']}/status"
        self.assertEqual(self.owner.post(url, json={"status": "done"}).status_code, 409)  # ยังไม่ยืนยัน
        self.assertEqual(self.owner.post(url, json={"status": "cancelled"}).status_code, 200)
        r = self.owner.post(url, json={"status": "confirmed"})  # ยกเลิกแล้วห้ามกลับมา
        self.assertEqual(r.status_code, 409)
        self.assertIn("ไม่ได้", r.json()["message"])
        self.assertEqual(self.owner.post(url, json={"status": "hacked"}).status_code, 409)
        self.assertEqual(self.owner.post("/api/v1/admin/bookings/HH-0000-99/status", json={"status": "confirmed"}).status_code, 404)

    def test_cancel_frees_the_slot(self):
        first = self.book()
        self.book()
        slot_state = lambda: next(
            s for d in self.customer.get("/api/v1/booking/slots").json()["days"] for s in d["slots"] if s["key"] == slot_at()
        )
        self.assertEqual(slot_state()["left"], 0)
        self.login()
        self.owner.post(f"/api/v1/admin/bookings/{first['id']}/status", json={"status": "cancelled"})
        self.assertEqual(slot_state()["left"], 1)
        self.book()  # จองแทนที่ได้จริง

    def test_search_by_code_and_range_limits(self):
        b = self.book()
        self.login()
        found = self.owner.get(f"/api/v1/admin/bookings/{b['id'].lower()}").json()["booking"]
        self.assertEqual(found["id"], b["id"])
        self.assertEqual(self.owner.get("/api/v1/admin/bookings/HH-9999-01").status_code, 404)
        self.assertEqual(self.owner.get("/api/v1/admin/bookings?start=2026-10-01&end=2027-01-01").status_code, 422)
        self.assertEqual(self.owner.get("/api/v1/admin/bookings?start=2026-10-05&end=2026-10-01").status_code, 422)

    def test_list_is_sorted_by_slot(self):
        self.book(hour=14)
        self.book(hour=9)
        self.login()
        slots_seen = [b["slot"][11:] for b in self.week().json()["bookings"]]
        self.assertEqual(slots_seen, ["09:00", "14:00"])

    # ---------- ลูกค้ายกเลิกคิวเอง (ยืนยันตัวตน ไม่ผูกกับแชท) + ร้านโอนคืน ----------

    OWNER = {"phone": "081-234-5678", "owner_name": "สมใจ"}
    PROMPTPAY = {"method": "promptpay", "account": "0812345678", "account_name": "สมใจ ใจดี"}

    def verify(self, booking_id, client=None, **who):
        body = {"booking_id": booking_id, **self.OWNER, **who}
        return (client or self.customer).post("/api/v1/booking/cancel/verify", json=body)

    def cancel(self, booking_id, client=None, **body):
        payload = {"booking_id": booking_id, **self.OWNER, **self.PROMPTPAY, **body}
        return (client or self.customer).post("/api/v1/booking/cancel", json=payload)

    def left(self, hour=10):
        days = self.customer.get("/api/v1/booking/slots").json()["days"]
        return next(s["left"] for d in days for s in d["slots"] if s["key"] == slot_at(hour))

    def check_hint(self):
        r = self.customer.post("/api/v1/booking/check", json={"phone": "0812345678"})
        return r.json()["bookings"][0]["status_hint"]

    def test_cancel_from_another_device_after_verifying_owner(self):
        b = self.book()
        other_device = TestClient(self.app)  # ไม่มีประวัติแชทของคนจอง — ยืนยันตัวตนแทน
        v = self.verify(b["id"].lower(), client=other_device, owner_name=" คุณ สมใจ ")
        self.assertEqual(v.status_code, 200, v.text)
        self.assertEqual((v.json()["booking"]["pet_name"], v.json()["booking"]["refund_amount"]), ("ถั่วแดง", 50))
        self.assertNotIn("phone", v.json()["booking"])

        r = self.cancel(b["id"], client=other_device)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["booking"]["status"], r.json()["refund_amount"]), ("cancelled", 50))
        self.assertNotIn("0812345678", r.text)  # เลขบัญชี/เบอร์ไม่ย้อนกลับไปหน้าลูกค้า
        self.assertEqual(self.left(), 2)  # ช่องเวลาว่างให้คนอื่นจองทันที
        self.assertIn("จะโอนคืน 50 บาท", self.check_hint())
        self.assertEqual(self.cancel(b["id"]).status_code, 409)  # กดซ้ำไม่คืนช่องซ้ำ
        self.assertEqual(self.left(), 2)

        self.login()
        refund = self.owner.get(f"/api/v1/admin/bookings/{b['id']}").json()["booking"]["refund"]
        self.assertEqual((refund["status"], refund["account"], refund["amount"]), ("pending", "0812345678", 50))
        self.assertEqual(self.check_item()["refund_status"], "pending")
        self.assertEqual(self.proof(b["id"]).status_code, 404)  # ร้านยังไม่ได้โอน/แนบสลิป

        # ต้องแนบสลิปโอนคืนก่อน ถึงจะกดยืนยันโอนคืนได้
        no_proof = self.owner.post(f"/api/v1/admin/bookings/{b['id']}/refunded")
        self.assertEqual(no_proof.status_code, 422)
        self.assertIn("สลิปโอนคืน", no_proof.json()["message"])
        bad = self.refunded(b["id"], data=b"GIF89a" + b"0" * 50)
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.refunded(b["id"]).status_code, 200)
        self.assertEqual(self.refunded(b["id"]).status_code, 409)
        self.assertEqual(self.refunded(b["id"], client=self.customer).status_code, 401)
        self.assertIn("โอนคืน 50 บาท แล้ว", self.check_hint())
        admin_img = self.owner.get(f"/api/v1/admin/bookings/{b['id']}/image/refund")
        self.assertEqual(admin_img.content, JPEG)

        # หน้าเช็คคิว: เห็นสถานะ + มีสลิป แต่ไม่มีเลขบัญชี · ดูรูปสลิปต้องยืนยันชื่อเจ้าของ
        item = self.check_item()
        self.assertEqual((item["refund_status"], item["refund_amount"], item["refund_proof"]), ("done", 50, True))
        self.assertTrue(item["refunded_at"])
        self.assertNotIn("0812345678", str(item))
        self.assertEqual(self.proof(b["id"], owner_name="คนอื่น").status_code, 404)
        r = self.proof(b["id"], client=TestClient(self.app))
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "image/jpeg", JPEG))

    def refunded(self, booking_id, data=JPEG, client=None):
        return (client or self.owner).post(
            f"/api/v1/admin/bookings/{booking_id}/refunded", files={"proof": ("refund.jpg", data, "image/jpeg")})

    def proof(self, booking_id, client=None, **who):
        body = {"booking_id": booking_id, **self.OWNER, **who}
        return (client or self.customer).post("/api/v1/booking/refund-proof", json=body)

    def check_item(self):
        r = self.customer.post("/api/v1/booking/check", json={"phone": "0812345678"})
        return r.json()["bookings"][0]

    def test_wrong_identity_is_rejected_without_saying_which_field(self):
        b = self.book()
        for who in [{"phone": "0899999999"}, {"owner_name": "สมชาย"}]:
            with self.subTest(who=who):
                r = self.verify(b["id"], **who)
                self.assertEqual(r.status_code, 404)
                self.assertIn("ไม่ตรงกับการจอง", r.json()["message"])
                self.assertEqual(self.cancel(b["id"], **who).status_code, 404)
        self.assertEqual(self.verify("HH-9999-01").status_code, 404)  # เลขจองที่ไม่มีจริง
        self.assertEqual(self.verify("abc").json()["field"], "booking_id")
        self.assertEqual(self.left(), 1)  # ยังไม่ถูกยกเลิก

    def test_five_wrong_tries_lock_online_cancel(self):
        b = self.book()
        codes = [self.verify(b["id"], owner_name=f"คนอื่น{i}").status_code for i in range(5)]
        self.assertEqual(codes, [404, 404, 404, 404, 423])
        # ล็อกแล้ว ต่อให้กรอกถูกก็ยกเลิกออนไลน์ไม่ได้ (นับใน store ไม่ใช่ต่อเครื่อง)
        right = self.verify(b["id"], client=TestClient(self.app))
        self.assertEqual(right.status_code, 423)
        self.assertIn("24 ชั่วโมง", right.json()["message"])
        self.assertEqual(self.cancel(b["id"]).status_code, 423)
        self.assertEqual(self.left(), 1)

    def test_refund_details_are_validated(self):
        b = self.book()
        for body, field in [
            ({"account": "12345"}, "account"),
            ({"method": "bank", "bank": None, "account": "1234567890"}, "bank"),
            ({"method": "bank", "bank": "กสิกรไทย", "account": "123"}, "account"),
            ({"method": "cash"}, "method"),
            ({"account_name": "  "}, "account_name"),
        ]:
            with self.subTest(field=field, body=body):
                r = self.cancel(b["id"], **body)
                self.assertEqual((r.status_code, r.json()["field"]), (422, field))
        self.assertEqual(self.left(), 1)
        ok = self.cancel(b["id"], method="bank", bank="กสิกรไทย", account="123-4-56789-0")
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_refund_name_is_checked_against_deposit_payer(self):
        self.payer = "นาย สมใจ ใ***"
        b1 = self.book(hour=10)
        b2 = self.book(hour=11)
        self.assertEqual(self.cancel(b1["id"]).status_code, 200)  # ชื่อบัญชี "สมใจ ใจดี" ตรงกับผู้โอน
        self.assertEqual(self.cancel(b2["id"], account_name="มิจฉา ชีพ").status_code, 200)
        self.login()
        r1 = self.owner.get(f"/api/v1/admin/bookings/{b1['id']}").json()["booking"]["refund"]
        r2 = self.owner.get(f"/api/v1/admin/bookings/{b2['id']}").json()["booking"]["refund"]
        self.assertEqual((r1["payer_name"], r1["payer_match"]), ("นาย สมใจ ใ***", True))
        self.assertFalse(r2["payer_match"])  # หลังบ้านเตือน: อย่าเพิ่งโอนคืน

    def test_cannot_cancel_within_3_hours(self):
        b = self.book()
        late = slots.parse_key(slot_at()) - service.timedelta(hours=2)
        with patch.object(slots, "now", lambda: late):
            mine = self.customer.get("/api/v1/booking/mine").json()["bookings"][0]
            self.assertFalse(mine["can_cancel"])
            self.assertIn("3 ชั่วโมง", mine["cancel_note"])
            v = self.verify(b["id"]).json()["booking"]
            self.assertFalse(v["can_cancel"])
            r = self.cancel(b["id"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.left(), 1)

    def test_shop_cancel_then_customer_cancel_releases_slot_once(self):
        b = self.book()
        self.login()
        r = self.owner.post(f"/api/v1/admin/bookings/{b['id']}/status", json={"status": "cancelled"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.cancel(b["id"]).status_code, 409)
        self.assertEqual(self.left(), 2)

if __name__ == "__main__":
    unittest.main()

"""ทดสอบทุก endpoint ในแผนภาพสถาปัตยกรรมกับระบบที่รันอยู่จริง แล้วบันทึกผล + เวลาตอบ

ใช้:  python tests/run_endpoint_check.py                      เว็บจริงบน Vercel — โหมดปลอดภัย (ไม่สร้างการจอง)
      python tests/run_endpoint_check.py http://127.0.0.1:8000 --full
          เครื่องตัวเอง — เส้นทางเต็ม: จอง (Gemini อ่านสลิปจริง) → ร้านยืนยัน → ลูกค้ายกเลิก → ร้านแนบสลิปโอนคืน
          ต้องตั้ง env ADMIN_PASSWORD ให้ตรงกับเซิร์ฟเวอร์ (ที่เก็บข้อมูลในเครื่องเป็นหน่วยความจำ ปิดแล้วหาย)

โหมดปลอดภัย: endpoint ที่แก้ข้อมูลการจอง/หลังบ้าน ทดสอบว่า "ปฏิเสธถูกต้อง" (422 / 404 / 401)
ผล:   docs/test-endpoints[-full].json + ตาราง Markdown พิมพ์ออกหน้าจอ
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = ARGS[0].rstrip("/") if ARGS else "https://hom-hom-grooming.vercel.app"
FULL = "--full" in sys.argv
OUT = ROOT / "docs" / ("test-endpoints-full.json" if FULL else "test-endpoints.json")
IMG = ROOT / "tests" / "Image"
PHONE, OWNER = "0890001122", "ทดสอบ ระบบ"

results: list[dict] = []


def env_value(name: str) -> str | None:
    """อ่านค่าจาก env หรือ .env (ไม่พิมพ์ค่าออกมา)"""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def record(group: str, method: str, path: str, what: str, expect, r: httpx.Response | None,
           seconds: float, note: str = "") -> httpx.Response | None:
    want = expect if isinstance(expect, (set, tuple, list)) else (expect,)
    status = r.status_code if r is not None else 0
    ok = status in want
    results.append(dict(group=group, method=method, path=path, what=what, expected="/".join(map(str, want)),
                        status=status, ok=ok, seconds=round(seconds, 2), note=note))
    print(f"{'PASS' if ok else 'FAIL'} {method:6} {path:48} {status} {seconds:.2f}s {note}", flush=True)
    return r


def call(client: httpx.Client, group, method, path, what, expect, note="", check=None, **kw):
    """ยิง 1 request — check(r) คืนข้อความเสริม หรือ raise AssertionError ถ้าเนื้อหาไม่ถูก"""
    start = time.perf_counter()
    try:
        r = client.request(method, BASE + path, **kw)
    except httpx.HTTPError as exc:
        return record(group, method, path, what, expect, None, time.perf_counter() - start, f"ต่อไม่ได้: {exc}")
    seconds = time.perf_counter() - start
    if check and r.status_code in (expect if isinstance(expect, (set, tuple, list)) else (expect,)):
        try:
            note = check(r) or note
        except (AssertionError, KeyError, ValueError) as exc:
            record(group, method, path, what, "เนื้อหาถูกต้อง", None, seconds, f"เนื้อหาไม่ตรง: {exc}")
            return r
    return record(group, method, path, what, expect, r, seconds, note)


def image(name: str, mime: str = "image/jpeg"):
    return (name, (IMG / name).read_bytes(), mime)


def pages(c):
    for path, what in [("/", "หน้าแรก + แชท"), ("/check", "หน้าเช็คคิว"), ("/avatar", "โหมดเสียง + อวตาร"),
                       ("/admin", "หลังบ้าน (ฟอร์ม login)")]:
        call(c, "หน้าเว็บ", "GET", path, what, 200, check=lambda r: None if "<html" in r.text else (_ for _ in ()).throw(AssertionError("ไม่ใช่ HTML")))
    call(c, "หน้าเว็บ", "GET", "/health", "ตรวจว่าเซิร์ฟเวอร์ทำงาน", 200)


def chat(c):
    g = "แชท"
    call(c, g, "GET", "/api/v1/config", "ค่าตั้งต้นของหน้าแชท", 200)
    call(c, g, "GET", "/api/v1/models", "รายชื่อโมเดล LLM", 200)
    call(c, g, "POST", "/api/v1/chat", "ถาม-ตอบแบบรอคำตอบเต็ม (LLM + RAG)", 200, json={"message": "ร้านเปิดกี่โมงคะ", "web_search": False},
         check=lambda r: "ตอบ: " + r.json()["reply"].replace("\n", " ")[:50] if "09:00" in r.json()["reply"] else (_ for _ in ()).throw(AssertionError("ไม่มีเวลาเปิดร้าน")))

    def stream_ok(r):
        events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
        assert any("delta" in e for e in events) and events[-1].get("done"), "สตรีมไม่จบด้วย done"
        return f"SSE {len(events)} events"
    call(c, g, "POST", "/api/v1/chat/stream", "ถาม-ตอบแบบสตรีม (SSE)", 200,
         json={"message": "ตัดเล็บเท่าไหร่คะ", "web_search": False}, check=stream_ok)
    call(c, g, "GET", "/api/v1/history", "ประวัติแชทของ session", 200,
         check=lambda r: f"{len(r.json()['messages'])} ข้อความ")
    r = call(c, g, "POST", "/api/v1/conversations", "เปิดบทสนทนาใหม่", 200)
    cid = r.json().get("id") if r is not None and r.status_code == 200 else "none"
    call(c, g, "GET", "/api/v1/conversations", "รายการบทสนทนา", 200)
    call(c, g, "POST", f"/api/v1/conversations/{cid}/activate", "สลับบทสนทนา", 200)
    call(c, g, "DELETE", f"/api/v1/conversations/{cid}", "ลบบทสนทนา", 200)
    call(c, g, "POST", "/api/v1/chat/reset", "ล้างแชท", 200)

    g = "รูป (Vision)"
    call(c, g, "POST", "/api/v1/attachments", "ส่งรูปน้อง → Gemini ประเมินขนาด + ราคาด้วยโค้ด", 200,
         files={"file": image("Chiwawa short.jpg")},
         check=lambda r: "ตอบ: " + (r.json().get("reply") or "").replace("\n", " ")[:50] if "250" in (r.json().get("reply") or "") else (_ for _ in ()).throw(AssertionError(r.text[:120])))
    call(c, g, "GET", "/api/v1/attachments", "รายการไฟล์แนบของ session", 200,
         check=lambda r: f"{len(r.json()['attachments'])} ไฟล์")
    call(c, g, "DELETE", "/api/v1/attachments/0", "ลบไฟล์แนบ", 200)

    g = "เสียง (TTS)"
    call(c, g, "GET", "/api/v1/tts/config", "เปิดใช้เสียง Cartesia หรือไม่", 200,
         check=lambda r: f"enabled={r.json()['enabled']}")
    call(c, g, "POST", "/api/v1/tts/stream", "ข้อความ → เสียงพูด (Cartesia)", 200, json={"text": "สวัสดีค่ะ"},
         check=lambda r: f"เสียง {len(r.content) // 1024} KB" if len(r.content) > 1000 else (_ for _ in ()).throw(AssertionError("ไม่มีเสียง")))


def line(c):
    secret = env_value("LINE_CHANNEL_SECRET")
    body = b'{"destination":"test","events":[]}'
    call(c, "LINE", "POST", "/line/webhook", "ลายเซ็นผิด → ปฏิเสธ", 401, content=body,
         headers={"Content-Type": "application/json", "X-Line-Signature": "wrong"})
    if secret:
        sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        call(c, "LINE", "POST", "/line/webhook", "ลายเซ็นถูก (เหมือนปุ่ม Verify ของ LINE)", 200, content=body,
             headers={"Content-Type": "application/json", "X-Line-Signature": sig})


def booking_public(c):
    g = "จองคิว"
    r = call(c, g, "GET", "/api/v1/booking/slots", "ช่องเวลาที่ว่าง 14 วัน", 200,
             check=lambda r: f"{len(r.json()['days'])} วัน")
    call(c, g, "GET", "/api/v1/booking/pickup", "ตำแหน่งร้าน + ตารางค่ารับส่ง", 200)
    call(c, g, "GET", "/api/v1/booking/pickup?lat=13.729&lng=100.748", "คิดระยะทาง + ค่ารับส่งจากหมุด", 200,
         check=lambda r: f"{r.json()['km']} กม. {r.json()['fee']} บาท")
    call(c, g, "GET", "/api/v1/booking/cancel-options", "รายชื่อธนาคารสำหรับรับเงินคืน", 200)
    return r


def booking_safe(c):
    """เว็บจริง: ไม่สร้างการจอง — ดูว่า endpoint ตอบและปฏิเสธข้อมูลผิดอย่างถูกต้อง"""
    g = "จองคิว"
    call(c, g, "POST", "/api/v1/booking", "จองด้วยข้อมูลไม่ครบ → ปฏิเสธ", 422, data={"pet_name": "", "phone": "123"})
    call(c, g, "GET", "/api/v1/booking/mine", "ใบจองของ session นี้", 200, check=lambda r: f"{len(r.json()['bookings'])} ใบ")
    call(c, g, "GET", "/api/v1/booking/HH-0101-01/image/pet", "รูปน้องของการจองคนอื่น → ไม่พบ", 404)
    call(c, g, "POST", "/api/v1/booking/check", "เช็คคิวด้วยเบอร์โทร", 200, json={"phone": PHONE},
         check=lambda r: f"{len(r.json()['bookings'])} คิว")
    who = dict(booking_id="HH-0101-01", phone=PHONE, owner_name="ไม่มีจริง")
    call(c, g, "POST", "/api/v1/booking/cancel/verify", "ยืนยันตัวตนผิด → ปฏิเสธ", 404, json=who)
    call(c, g, "POST", "/api/v1/booking/cancel", "ยกเลิกด้วยตัวตนผิด → ปฏิเสธ", 404,
         json={**who, "method": "promptpay", "account": PHONE, "account_name": "x"})
    call(c, g, "POST", "/api/v1/booking/refund-proof", "ขอดูสลิปโอนคืนด้วยตัวตนผิด → ปฏิเสธ", 404, json=who)

    g = "หลังบ้าน"
    call(c, g, "POST", "/admin/login", "รหัสผ่านผิด → กลับหน้า login", 303, data={"password": "wrong-password"},
         check=lambda r: "ไป " + r.headers.get("location", ""))
    for method, path, what in [
        ("GET", "/api/v1/admin/bookings", "ตารางคิว"),
        ("GET", "/api/v1/admin/bookings/HH-0101-01", "รายละเอียดการจอง"),
        ("POST", "/api/v1/admin/bookings/HH-0101-01/status", "เปลี่ยนสถานะ"),
        ("POST", "/api/v1/admin/bookings/HH-0101-01/refunded", "ยืนยันโอนคืน"),
        ("POST", "/api/v1/admin/bookings/HH-0101-01/refund-rejected", "ปฏิเสธการคืนเงิน"),
        ("GET", "/api/v1/admin/bookings/HH-0101-01/image/slip", "ดูสลิป"),
    ]:
        call(c, g, method, path, f"{what} โดยไม่ login → ปฏิเสธ", 401, json={"status": "confirmed"} if "status" in path else None)
    call(c, g, "POST", "/admin/logout", "ออกจากระบบ", 303)


def booking_full(c, slots_response):
    """เครื่องตัวเอง: เส้นทางเต็มของลูกค้า + เจ้าของร้าน"""
    g = "จองคิว"
    password = env_value("ADMIN_PASSWORD")
    slot = next(s["key"] for d in slots_response.json()["days"] for s in d["slots"] if s["left"] > 0)
    r = call(c, g, "POST", "/api/v1/booking", "จองคิว + Gemini ตรวจสลิปมัดจำ 50 บาท", 201,
             data={"pet_name": "ถั่วแดง", "owner_name": OWNER, "phone": PHONE, "slot": slot},
             files={"pet_photo": image("Chiwawa short.jpg"), "slip": image("slip_owner_50.png", "image/png")},
             check=lambda r: "เลขจอง " + r.json()["booking"]["id"])
    if r is None or r.status_code != 201:
        return
    b = r.json()["booking"]
    bid = b["id"]
    who = dict(booking_id=bid, phone=PHONE, owner_name=OWNER)
    call(c, g, "GET", "/api/v1/booking/mine", "ใบจองของ session นี้", 200, check=lambda r: f"{len(r.json()['bookings'])} ใบ")
    call(c, g, "GET", b["pet_image"], "รูปน้องบนใบจอง", 200, check=lambda r: r.headers["content-type"])
    call(c, g, "POST", "/api/v1/booking/check", "เช็คคิวด้วยเบอร์โทร", 200, json={"phone": PHONE},
         check=lambda r: r.json()["bookings"][0]["status_label"])

    g = "หลังบ้าน"
    admin = httpx.Client(timeout=90)
    call(admin, g, "POST", "/admin/login", "เข้าสู่ระบบ", 303, data={"password": password or ""},
         check=lambda r: None if r.headers.get("location") == "/admin" else (_ for _ in ()).throw(AssertionError("รหัสไม่ถูก")))
    call(admin, g, "GET", "/api/v1/admin/bookings", "ตารางคิว", 200, check=lambda r: f"{len(r.json()['bookings'])} คิว")
    call(admin, g, "GET", f"/api/v1/admin/bookings/{bid}", "รายละเอียดการจอง + ผลตรวจสลิป", 200,
         check=lambda r: f"สลิปตรวจอัตโนมัติ={r.json()['booking']['slip'].get('auto_ok')}")
    call(admin, g, "GET", f"/api/v1/admin/bookings/{bid}/image/slip", "ดูสลิปมัดจำ", 200)
    call(admin, g, "POST", f"/api/v1/admin/bookings/{bid}/status", "ยืนยันคิว", 200, json={"status": "confirmed"},
         check=lambda r: r.json()["booking"]["status_label"])

    g = "จองคิว"
    call(c, g, "POST", "/api/v1/booking/cancel/verify", "ยืนยันตัวตนก่อนยกเลิก", 200, json=who,
         check=lambda r: f"คืน {r.json()['booking']['refund_amount']} บาท")
    call(c, g, "POST", "/api/v1/booking/cancel", "ยกเลิกคิว + แจ้งบัญชีรับเงินคืน", 200,
         json={**who, "method": "promptpay", "account": PHONE, "account_name": OWNER},
         check=lambda r: r.json()["booking"]["status_label"])
    call(c, g, "POST", "/api/v1/booking/refund-proof", "ดูสลิปโอนคืนก่อนร้านโอน → ยังไม่มี", 404, json=who)

    g = "หลังบ้าน"
    call(admin, g, "POST", f"/api/v1/admin/bookings/{bid}/refunded", "ยืนยันโอนคืนโดยไม่แนบสลิป → ปฏิเสธ", 422)
    call(admin, g, "POST", f"/api/v1/admin/bookings/{bid}/refunded", "แนบสลิปโอนคืน + ยืนยัน", 200,
         files={"proof": image("slip_ok_50.png", "image/png")},
         check=lambda r: "คืนเงิน: " + r.json()["booking"]["refund"]["status"])
    call(c, "จองคิว", "POST", "/api/v1/booking/refund-proof", "ลูกค้าดูสลิปโอนคืน (ยืนยันชื่อเจ้าของ)", 200, json=who,
         check=lambda r: r.headers["content-type"])
    call(admin, g, "POST", "/admin/logout", "ออกจากระบบ", 303)
    call(admin, g, "GET", "/api/v1/admin/bookings", "หลัง logout → ปฏิเสธ", 401)


def main() -> None:
    with httpx.Client(timeout=120) as c:
        pages(c)
        chat(c)
        line(c)
        slots = booking_public(c)
        if FULL:
            booking_full(c, slots)
        else:
            booking_safe(c)

    now = datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")
    OUT.write_text(json.dumps(dict(base_url=BASE, mode="full" if FULL else "safe", tested_at=now, results=results),
                              ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(r["ok"] for r in results)
    print(f"\nผ่าน {passed}/{len(results)} · บันทึกที่ {OUT}")


if __name__ == "__main__":
    main()

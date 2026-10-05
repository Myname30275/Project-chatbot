"""ทดสอบ 5 ภาพตามโจทย์ Final Project กับระบบจริง (Gemini Vision จริง) แล้วบันทึกผลวิเคราะห์ + เวลาตอบ

ใช้:  python tests/run_5_images.py [BASE_URL]      (ค่าเริ่ม = เว็บจริงบน Vercel)
ผล:   docs/test-5-images.json

แต่ละภาพเป็นแชทใหม่ (ล้าง cookie) · คำตอบหลังส่งรูปสร้างด้วยโค้ดจากผลวิเคราะห์ของ Vision
ผ่าน = คำตอบมีคำสำคัญครบทุกกลุ่ม (กลุ่มที่เป็น tuple = มีคำใดคำหนึ่งก็ได้) และไม่มีคำต้องห้าม
"""

import json
import mimetypes
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://hom-hom-grooming.vercel.app"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "test-5-images.json"

IMAGES = [
    dict(file="Chiwawa short.jpg", what="สุนัขเล็กขนสั้น (ชิวาวา)", expect="สุนัขเล็ก: อาบน้ำ 250 / ตัดขน 400 บาท + ขอน้ำหนักจริง",
         must=["250", "400"], must_not=["500", "750"]),
    dict(file="Cyberian.jpg", what="สุนัขใหญ่ขนฟู", expect="สุนัขใหญ่: อาบน้ำ 500 / ตัดขน 750 บาท",
         must=["500", "750"], must_not=["250 บาท"]),
    dict(file="cat.JPG", what="แมวไทยขนสั้น", expect="แมว: อาบน้ำ 300 / ตัดขน 600 บาท ไม่ขอน้ำหนัก",
         must=["300", "600"], must_not=["กี่กิโล"]),
    dict(file="Crocodile.webp", what="จระเข้ (สัตว์ที่ร้านไม่รับ)", expect="แจ้งว่าร้านรับเฉพาะสุนัขและแมว ไม่บอกราคา",
         must=[("สุนัขและแมว", "ไม่ได้")], must_not=["บาท"]),
    dict(file="slip_wrong_500.png", what="สลิปจำลอง ยอด 500 บาท โอนเข้าบัญชีคนอื่น",
         expect="แจ้งว่ายอดไม่ตรงมัดจำ และชื่อผู้รับไม่ใช่บัญชีร้าน ไม่ยืนยันคิว",
         must=["500", ("ไม่ตรง", "ไม่ใช่")], must_not=["ยืนยันคิวให้แล้ว", "จองสำเร็จ"]),
]


def problems(reply: str, case: dict) -> list[str]:
    out = []
    for group in case["must"]:
        words = group if isinstance(group, tuple) else (group,)
        if not any(w in reply for w in words):
            out.append("ขาด: " + " / ".join(words))
    out += [f"มีคำต้องห้าม: {w}" for w in case.get("must_not", []) if w in reply]
    return out


def main() -> int:
    results = []
    with httpx.Client(base_url=BASE, timeout=120) as client:
        for no, case in enumerate(IMAGES, 1):
            client.cookies.clear()
            path = ROOT / "tests" / "Image" / case["file"]
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            start = time.perf_counter()
            r = client.post("/api/v1/attachments", files={"file": (path.name, path.read_bytes(), mime)})
            seconds = round(time.perf_counter() - start, 2)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            reply = body.get("reply") or ""
            bad = problems(reply, case) if r.status_code == 200 else [f"HTTP {r.status_code}"]
            results.append({"no": no, "file": case["file"], "what": case["what"], "expected": case["expect"],
                            "status": r.status_code, "response": body, "reply": reply,
                            "seconds": seconds, "passed": not bad, "problems": bad})
            print(f"{no}. {case['file']} · {seconds} วิ · {'ผ่าน' if not bad else 'ไม่ผ่าน ' + str(bad)}", flush=True)
            print("   " + reply.replace("\n", " | "), flush=True)
    stamp = datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")
    OUT.write_text(json.dumps({"base_url": BASE, "tested_at": stamp, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    passed = sum(r["passed"] for r in results)
    print(f"ผ่าน {passed}/{len(results)} · บันทึกที่ {OUT}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

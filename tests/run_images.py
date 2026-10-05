"""ทดสอบชุดภาพ 15 ภาพ (สัตว์เลี้ยง 6 · ร้านไม่รับ 4 · สลิป 5) ตามโจทย์ Final Project กับระบบจริง (Gemini Vision จริง) แล้วบันทึกผลวิเคราะห์ + เวลาตอบ

ใช้:  python tests/run_images.py [BASE_URL]      (ค่าเริ่ม = เว็บจริงบน Vercel)
ผล:   docs/test-images.json

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
OUT = ROOT / "docs" / "test-images.json"
FOLDER = "test 10 pic"

IMAGES = [
    # ---- รูปสัตว์เลี้ยงที่ร้านรับ ----
    dict(file="Chiwawa short.jpg", group="สัตว์เลี้ยง", what="สุนัขเล็กขนสั้น (ชิวาวา)",
         expect="สุนัขเล็ก: อาบน้ำ 250 / ตัดขน 400 บาท + ขอน้ำหนักจริง", must=["250", "400"], must_not=["500", "750"]),
    dict(file="Chiwawa.jpeg", group="สัตว์เลี้ยง", what="สุนัขเล็กขนยาว (ชิวาวา)",
         expect="สุนัขเล็ก: อาบน้ำ 250 / ตัดขน 400 บาท", must=["250", "400"], must_not=["500", "750"]),
    dict(file="Cyberian.jpg", group="สัตว์เลี้ยง", what="สุนัขใหญ่ขนฟู",
         expect="สุนัขใหญ่: อาบน้ำ 500 / ตัดขน 750 บาท", must=["500", "750"], must_not=["250 บาท"]),
    dict(file="Two dog.JPG", group="สัตว์เลี้ยง", what="สุนัข 2 ตัวในรูปเดียว",
         expect="แยกราคาทีละตัวตามขนาดของแต่ละตัว", must=[("ตัวที่ 2", "2 ตัว", "สองตัว")], must_not=[]),
    dict(file="cat.JPG", group="สัตว์เลี้ยง", what="แมวไทยขนสั้น",
         expect="แมว: อาบน้ำ 300 / ตัดขน 600 บาท ไม่ขอน้ำหนัก", must=["300", "600"], must_not=["กี่กิโล"]),
    dict(file="cat dog b.jfif", group="สัตว์เลี้ยง", what="แมวดำนอนทับสุนัขดำ (2 ตัว คนละชนิด)",
         expect="เห็นทั้งแมวและสุนัข แยกราคาทีละตัว", must=["แมว", "สุนัข", "300"], must_not=[]),
    # ---- รูปที่ร้านให้บริการไม่ได้ ----
    dict(file="cat 1.jpg", group="ร้านไม่รับ", what="คาราคัล (แมวป่า ไม่ใช่แมวบ้าน)",
         expect="ไม่ตีราคาเป็นแมวบ้าน แจ้งว่าร้านให้บริการไม่ได้", must=[("สุนัขและแมว", "ไม่ได้", "สุนัข/แมว")], must_not=["บาท"]),
    dict(file="Bird.jpg", group="ร้านไม่รับ", what="นก",
         expect="แจ้งว่าร้านให้บริการไม่ได้ (รับเฉพาะสุนัขและแมว) ไม่บอกราคา", must=[("สุนัขและแมว", "ไม่ได้", "สุนัข/แมว")], must_not=["บาท"]),
    dict(file="Panda.jpg", group="ร้านไม่รับ", what="แพนด้า",
         expect="แจ้งว่าร้านให้บริการไม่ได้ (รับเฉพาะสุนัขและแมว) ไม่บอกราคา", must=[("สุนัขและแมว", "ไม่ได้", "สุนัข/แมว")], must_not=["บาท"]),
    dict(file="Kimera full matal.jfif", group="ร้านไม่รับ", what="ภาพการ์ตูน/CG สัตว์ประหลาด (ไม่ใช่รูปถ่ายจริง)",
         expect="ไม่บรรยายรูป ไม่ตีราคา แจ้งว่าดูได้เฉพาะรูปน้องและสลิป", must=[("สลิป", "ไม่ได้")], must_not=["บาท", "Fullmetal", "คิเมร่า"]),
    # ---- สลิป (สลิปจริงของผู้พัฒนา เลขบัญชีถูกปิดบางส่วนโดยแอปธนาคาร) ----
    dict(file="slip tp.jfif", group="สลิป", what="สลิปจริง 50 บาท โอนเข้าบัญชีร้าน (ถูกต้อง)",
         expect="รับสลิปมัดจำ 50 บาท แจ้งว่ารอร้านตรวจและยืนยันคิว ไม่ยืนยันเอง", must=["50", ("ยืนยัน", "ตรวจ")],
         must_not=["ไม่ตรง", "ไม่ใช่บัญชี", "จองสำเร็จ"]),
    dict(file="slip t.jfif", group="สลิป", what="สลิปจริง 50 บาท แต่โอนเข้าบัญชีคนอื่น",
         expect="แจ้งว่าชื่อผู้รับไม่ใช่บัญชีร้าน", must=[("ไม่ใช่บัญชี", "ไม่ตรง")], must_not=["จองสำเร็จ"]),
    dict(file="Slip Gum auction.jpg", group="สลิป", what="สลิปจริง 7,350 บาท จ่ายร้านค้าอื่น",
         expect="แจ้งว่ายอดในสลิปไม่ใช่ยอดมัดจำ ไม่รับเป็นสลิปมัดจำ", must=[("7,350", "7350"), "แต่ค่ามัดจำ"], must_not=["จองสำเร็จ", "ได้รับรูปสลิปมัดจำ"]),
    dict(file="Slip credit.jpg", group="สลิป", what="สลิปจ่ายด้วยบัตรเครดิต 2,273 บาท ร้านค้าอื่น",
         expect="แจ้งว่ายอดในสลิปไม่ใช่ยอดมัดจำ ไม่รับเป็นสลิปมัดจำ", must=[("2,273", "2273"), "แต่ค่ามัดจำ"], must_not=["จองสำเร็จ", "ได้รับรูปสลิปมัดจำ"]),
    dict(file="sl f.jpg", group="สลิป", what="สลิปปลอม: แก้ชื่อผู้รับของสลิปใบก่อนหน้าให้เป็นบัญชีร้าน",
         expect="ตรวจพบว่าเป็นสลิปที่ถูกแก้ไข (ระบบอ่านจากรูป จึงคาดว่าตรวจไม่พบ — ข้อจำกัดที่ทราบ)", must=[("แก้ไข", "ปลอม", "ซ้ำ")], must_not=[]),
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
    with httpx.Client(base_url=BASE, timeout=75) as client:
        for no, case in enumerate(IMAGES, 1):
            client.cookies.clear()
            path = ROOT / "tests" / FOLDER / case["file"]
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            for attempt in range(3):  # serverless ตัดการเชื่อมต่อ/หมดเวลาเป็นบางครั้ง ลองใหม่ได้ 2 รอบ
                start = time.perf_counter()
                try:
                    r = client.post("/api/v1/attachments", files={"file": (path.name, path.read_bytes(), mime)})
                    break
                except httpx.TransportError as exc:
                    print(f"  ({case['file']}: {type(exc).__name__} ลองใหม่)", flush=True)
                    if attempt == 2:
                        raise
            seconds = round(time.perf_counter() - start, 2)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            reply = body.get("reply") or ""
            bad = problems(reply, case) if r.status_code == 200 else [f"HTTP {r.status_code}"]
            results.append({"no": no, "file": case["file"], "group": case["group"], "what": case["what"], "expected": case["expect"],
                            "status": r.status_code, "response": body, "reply": reply,
                            "seconds": seconds, "passed": not bad, "problems": bad})
            print(f"{no}. {case['file']} · {seconds} วิ · {'ผ่าน' if not bad else 'ไม่ผ่าน ' + str(bad)}", flush=True)
            print("   " + reply.replace("\n", " | "), flush=True)
    stamp = datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")
    OUT.write_text(json.dumps({"base_url": BASE, "folder": "tests/" + FOLDER, "tested_at": stamp, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    passed = sum(r["passed"] for r in results)
    print(f"ผ่าน {passed}/{len(results)} · บันทึกที่ {OUT}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

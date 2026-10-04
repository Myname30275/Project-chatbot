"""ทดสอบ 10 คำถามตามโจทย์ Final Project กับระบบจริง (LLM + RAG จริง) แล้วบันทึกคำตอบ + เวลาตอบ

ใช้:  python tests/run_10_questions.py [BASE_URL]      (ค่าเริ่ม = เว็บจริงบน Vercel)
ผล:   docs/test-10-questions.json (คำตอบเต็ม) + ตาราง Markdown พิมพ์ออกหน้าจอ

แต่ละข้อเป็นแชทใหม่ (ไม่ส่ง cookie) จึงไม่มีบริบทจากข้อก่อนหน้า
ผ่าน = คำตอบมีคำสำคัญครบทุกกลุ่ม (กลุ่มที่เป็น tuple = มีคำใดคำหนึ่งก็ได้) และไม่มีคำต้องห้าม
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://hom-hom-grooming.vercel.app"
OUT = Path(__file__).resolve().parent.parent / "docs" / "test-10-questions.json"

QUESTIONS = [
    dict(q="อาบน้ำหมาหนัก 8 กิโล ราคาเท่าไหร่คะ", expect="สุนัขเล็ก 250 บาท + แจ้งว่าเป็นราคาประเมิน",
         must=["250", "ประเมิน"], must_not=["350", "500"]),
    dict(q="ตัดขนแมวทั้งตัวเท่าไหร่ ใช้เวลานานไหม", expect="600 บาท ประมาณ 2–3 ชั่วโมง",
         must=["600", ("2–3", "2-3", "2 - 3", "2 ถึง 3")]),
    dict(q="ร้านเปิดกี่โมง หยุดวันไหนบ้าง", expect="อังคาร–อาทิตย์ 09:00–18:00 น. หยุดวันจันทร์",
         must=["09:00", "18:00", "จันทร์"]),
    dict(q="อยากจองคิวต้องทำยังไง", expect="กดปุ่มจองคิว กรอกข้อมูล เลือกเวลา แนบสลิปมัดจำ 50 บาท + มีปุ่มจองคิว",
         must=["จองคิว", "สลิป"], actions=["book"]),
    dict(q="มัดจำเท่าไหร่ โอนเข้าบัญชีชื่ออะไร", expect="50 บาท บัญชีนายภาณุพงศ์ บุตรดี",
         must=["50", "ภาณุพงศ์"]),
    dict(q="ขนน้องพันกันเยอะมาก ต้องเสียเงินเพิ่มไหม", expect="เพิ่ม 150–300 บาท ประเมินหน้างาน",
         must=["150", "300"]),
    dict(q="มีบริการรับส่งน้องถึงบ้านไหม คิดค่าบริการยังไง", expect="มี ≤5 กม. 150 บาท, 5–10 กม. 250 บาท ไม่เกิน 10 กม.",
         must=["150", "250", "10"]),
    dict(q="ถ้าจะยกเลิกคิวต้องทำยังไง ได้เงินมัดจำคืนไหม", expect="ยกเลิกก่อนนัด 3 ชั่วโมง ร้านโอนคืน + มีปุ่มยกเลิกคิว",
         must=["3 ชั่วโมง", ("คืน",)], actions=["cancel"]),
    dict(q="มีส่วนลดสำหรับลูกค้าประจำไหม", expect="แพ็กเกจสมาชิกรายเดือน ลด 10% เท่านั้น",
         must=["10%", "สมาชิก"]),
    dict(q="ฝากน้องค้างคืนที่ร้านได้ไหมคะ", expect="ร้านไม่มีบริการฝากเลี้ยงค้างคืน (ไม่รับปาก)",
         must=[("ไม่มีบริการ", "ไม่มี")], must_not=["ได้ค่ะ ฝาก", "ต่อคืน"]),
]


def ask(client: httpx.Client, question: str) -> dict:
    start = time.perf_counter()
    first = None
    text, blocked, actions, sources = "", None, [], []
    with client.stream("POST", f"{BASE}/api/v1/chat/stream", json={"message": question}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if "delta" in ev:
                first = first or time.perf_counter() - start
                text += ev["delta"]
            elif "replace" in ev:
                text = ev["replace"]
            elif "blocked" in ev:
                blocked = ev["blocked"]
            elif "actions" in ev:
                actions = ev["actions"]
            elif "knowledge" in ev:
                sources = [s.get("title") or s.get("id") for s in ev["knowledge"]]
    return dict(answer=text.strip(), blocked=blocked, actions=actions, sources=sources,
                first_token_s=round(first or 0, 2), total_s=round(time.perf_counter() - start, 2))


def judge(case: dict, got: dict) -> list[str]:
    """คืนรายการสิ่งที่ไม่ผ่าน (ว่าง = ผ่าน)"""
    problems = []
    if got["blocked"]:
        problems.append(f"ถูกบล็อก {got['blocked']}")
    for group in case.get("must", []):
        words = group if isinstance(group, tuple) else (group,)
        if not any(w in got["answer"] for w in words):
            problems.append(f"ไม่มีคำว่า {' / '.join(words)}")
    for w in case.get("must_not", []):
        if w in got["answer"]:
            problems.append(f"มีคำต้องห้าม {w}")
    for a in case.get("actions", []):
        if a not in got["actions"]:
            problems.append(f"ไม่มีปุ่ม {a}")
    return problems


def main() -> None:
    results = []
    with httpx.Client(timeout=90) as client:
        for i, case in enumerate(QUESTIONS, 1):
            got = ask(client, case["q"])
            problems = judge(case, got)
            results.append(dict(no=i, question=case["q"], expected=case["expect"], **got,
                                passed=not problems, problems=problems))
            print(f"Q{i} {'PASS' if not problems else 'FAIL ' + str(problems)} {got['total_s']} s", flush=True)
            time.sleep(2)  # ไม่ยิงถี่จนชน rate limit ของ LLM ฟรี

    now = datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")
    OUT.write_text(json.dumps(dict(base_url=BASE, tested_at=now, results=results), ensure_ascii=False, indent=2),
                   encoding="utf-8")

    passed = sum(r["passed"] for r in results)
    times = [r["total_s"] for r in results]
    print(f"\nผ่าน {passed}/{len(results)} · เวลาตอบเฉลี่ย {sum(times) / len(times):.1f} วิ "
          f"(เร็วสุด {min(times)} / ช้าสุด {max(times)}) · บันทึกที่ {OUT}\n")
    print("| # | คำถาม | ผลที่คาดหวัง | คำตอบจริง | ปุ่ม | คำแรก | ตอบจบ | ผล |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        answer = r["answer"].replace("\n", " ").replace("|", "/")
        print(f"| Q{r['no']} | {r['question']} | {r['expected']} | {answer} | {', '.join(r['actions']) or '—'} "
              f"| {r['first_token_s']} วิ | {r['total_s']} วิ | {'✅' if r['passed'] else '❌ ' + '; '.join(r['problems'])} |")


if __name__ == "__main__":
    main()

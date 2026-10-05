"""สร้างแผนภาพสถาปัตยกรรมฉบับนำเสนอ (16:9) → docs/architecture-slides.html (+ PNG ใน docs/img/)

ใช้:  python docs/build_slides.py          สร้างไฟล์ HTML
      python docs/build_slides.py --png    สร้าง HTML แล้วส่งออก PNG 1920×1080 ด้วย Playwright

ตัวเลขในภาพ (จำนวน FAQ / ชิ้นความรู้ / กฎ) อ่านจากไฟล์จริงของโปรเจกต์ จึงไม่ต้องแก้มือเมื่อข้อมูลร้านเปลี่ยน
ผลทดสอบอ่านจาก docs/test-*.json ที่สคริปต์ทดสอบบันทึกไว้
"""

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))
import build_aws_diagram as aws  # noqa: E402  แผ่นที่ 1
OUT = ROOT / "docs" / "architecture-slides.html"
W, H = 1600, 900


# ---------------- ตัวเลขจากไฟล์จริง ----------------

def facts() -> dict:
    catalog = json.loads((ROOT / "shop" / "catalog.json").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "rag" / "index.json").read_text(encoding="utf-8"))
    prompt = (ROOT / "prompts" / "chat_system.txt").read_text(encoding="utf-8")
    must = prompt.split("# ต้องทำ")[1].split("# ห้ามทำ")[0]
    must_not = prompt.split("# ห้ามทำ")[1].split("# เมื่อลูกค้าถามนอกเรื่อง")[0]

    def result(name, key="passed"):
        path = ROOT / "docs" / name
        if not path.exists():
            return "—"
        rows = json.loads(path.read_text(encoding="utf-8"))["results"]
        return f"{sum(bool(r[key]) for r in rows)}/{len(rows)}"

    ten = json.loads((ROOT / "docs" / "test-10-questions.json").read_text(encoding="utf-8"))["results"]
    return {
        "faq": len(re.findall(r"^## \d+\.", (ROOT / "shop" / "faq.md").read_text(encoding="utf-8"), re.M)),
        "chunks": len(index["vectors"]),
        "items": sum(len(catalog[k]) for k in ("services", "addons", "delivery", "packages", "products")),
        "must": len(re.findall(r"^\d+\. ", must, re.M)),
        "must_not": len(re.findall(r"^\d+\. ", must_not, re.M)),
        "deposit": catalog["payment"]["deposit"],
        "capacity": catalog["booking"]["capacity_per_slot"],
        "max_pets": catalog["booking"]["max_pets"],
        "cancel_hours": catalog["booking"]["cancel_hours_before"],
        "line": catalog["shop"]["contacts"]["line"],
        "q10": result("test-10-questions.json"),
        "safety": result("test-prompt-safety.json"),
        "api": result("test-endpoints.json", "ok"),
        "avg": f"{sum(r['total_s'] for r in ten) / len(ten):.1f}",
        "first": f"{sum(r['first_token_s'] for r in ten) / len(ten):.1f}",
    }


# ---------------- ชิ้นส่วน SVG ----------------

def text(x, y, s, cls="t", anchor="middle"):
    return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{escape(s)}</text>'


def box(x, y, w, h, title, subs=(), cls="bx", r=14, title_cls="t", align="middle"):
    """กล่อง 1 ใบ: หัวข้อ + บรรทัดย่อย จัดกึ่งกลางแนวตั้งอัตโนมัติ"""
    lines = [(title, title_cls)] + [(s, "ts") for s in subs]
    step = 21
    top = y + h / 2 - (len(lines) - 1) * step / 2 + 5
    tx = x + w / 2 if align == "middle" else x + 16
    out = [f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" />']
    out += [text(tx, top + i * step, s, c, align) for i, (s, c) in enumerate(lines)]
    return "\n".join(out)


def group(x, y, w, h, label, cls="grp"):
    return (f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="20" />\n'
            + text(x + 18, y + 26, label, "gl", "start"))


def arrow(d, cls="ln", marker="a"):
    return f'<path class="{cls}" d="{d}" marker-end="url(#{marker})" />'


def badge(x, y, n):
    return (f'<circle class="num" cx="{x}" cy="{y}" r="13" />'
            + f'<text class="numt" x="{x}" y="{y + 5}" text-anchor="middle">{n}</text>')


DEFS = """<defs>
  <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="#5c3d2e" /></marker>
  <marker id="an" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="#b0503a" /></marker>
</defs>"""


def header(title, sub):
    return (text(48, 62, title, "h1", "start") + text(48, 94, sub, "h2", "start")
            + '<image href="../static/img/logo-badge.png" x="1486" y="24" width="72" height="72" />')


def svg(body, label):
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}">\n{DEFS}\n'
            f'<rect class="bg" x="0" y="0" width="{W}" height="{H}" />\n{body}\n</svg>')


# ---------------- สไลด์ 1: ภาพรวมระบบ ----------------

def slide_system(f: dict) -> str:
    p = [header("สถาปัตยกรรมระบบแชทบอท “น้องหอม”",
                "Hom Hom Grooming · ร้านอาบน้ำ-ตัดขนสุนัขและแมว · https://hom-hom-grooming.vercel.app")]

    # ผู้ใช้
    p.append(box(40, 150, 150, 334, "ลูกค้า", ("ถามราคา", "ส่งรูปน้อง / สลิป", "จอง · เช็ค · ยกเลิกคิว"), "bx-user"))
    p.append(box(40, 530, 150, 64, "เจ้าของร้าน", ("ดูแลคิว",), "bx-user"))

    # หน้าจอ
    p.append(group(215, 110, 250, 500, "หน้าจอที่ผู้ใช้เห็น"))
    fronts = [
        (150, "หน้าแรก + แชท  /", "แชท · ฟอร์มจอง · ยกเลิกคิว"),
        (230, "แอป LINE", f"LINE OA {f['line']}"),
        (310, "โหมดเสียง  /avatar", "พูดคุยกับอวตารพนักงาน"),
        (420, "เช็คคิว  /check", "สถานะ · คืนเงิน · ยกเลิก"),
        (530, "หลังบ้าน  /admin", "ตารางคิว · ยืนยัน · โอนคืน"),
    ]
    for y, t, s in fronts:
        p.append(box(230, y, 220, 64, t, (s,)))
        p.append(arrow(f"M190 {y + 32} H226"))
        p.append(arrow(f"M450 {y + 32} H526"))

    # Vercel
    p.append(group(500, 110, 700, 730, "Vercel Serverless · FastAPI (Python)", "grp-main"))
    p.append(text(615, 135, "", "gl"))
    channels = [(150, "web_chat.py", "แชทแบบสตรีม (SSE)"), (230, "line_webhook.py", "ตรวจลายเซ็น LINE"),
                (310, "tts.py", "ข้อความ → เสียง"), (420, "booking_api.py", "จอง · เช็ค · ยกเลิก"),
                (530, "admin.py", "login + จัดการคิว")]
    for y, t, s in channels:
        p.append(box(530, y, 160, 64, t, (s,), "bx-ch"))
    p.append(text(610, 618, "ช่องทางเข้า  channels/", "gs"))

    # แกนกลางแชท
    p.append(f'<rect class="bx-core" x="720" y="150" width="460" height="244" rx="16" />')
    p.append(text(950, 178, "แกนกลางแชท  chatbot/assistant.py", "t"))
    p.append(text(950, 198, "ทุกช่องทางผ่าน pipeline เดียวกัน", "ts"))
    steps = [
        (735, 212, "① กฎในโค้ด", "ยาว · ถี่ · คำต้องห้าม · injection"),
        (960, 212, "ดักเบอร์โทร / เลขจอง", "→ ปุ่มเช็คคิว (ไม่เรียก LLM)"),
        (735, 272, "② ตรวจเจตนา (LLM)", "นอกเรื่อง · ข้อมูลคนอื่น · อันตราย"),
        (960, 272, "RAG ค้นข้อมูลร้าน", f"4 ชิ้นจาก {f['chunks']} ชิ้น · ทำพร้อม ②"),
        (735, 332, "LLM ตอบ (สตรีม)", "ข้อมูลร้าน + ประวัติ 12 ข้อความ"),
        (960, 332, "③ ตรวจคำตอบทีละประโยค", "ราคา · ข้อมูลส่วนตัว · เดาคิวว่าง"),
    ]
    for x, y, t, s in steps:
        p.append(box(x, y, 205, 52, t, (s,), "bx", 10, "tsb"))

    # ระบบจอง + vision
    p.append(box(720, 414, 220, 116, "ระบบจอง  booking/", ("โค้ดล้วน ไม่ผ่าน LLM", "ช่องเวลา · หลายตัว · รับ-ส่ง",
                                                         "ยืนยันตัวตน · ยกเลิก · คืนเงิน"), "bx-hl"))
    p.append(box(960, 414, 220, 116, "อ่านรูป  vision/", ("Gemini → JSON ที่ตรวจแล้ว", "รูปน้อง → ราคาจากโค้ด",
                                                        "สลิป → ตรวจยอด/ผู้รับ/ผู้โอน"), "bx"))
    p.append(box(720, 550, 460, 96, "ข้อมูลร้าน (แหล่งเดียวของทุกคำตอบ)",
                 (f"shop/catalog.json {f['items']} รายการ · faq.md {f['faq']} ข้อ · policies.md → RAG {f['chunks']} ชิ้น",
                  f"prompts/  ต้องทำ {f['must']} ข้อ · ห้ามทำ {f['must_not']} ข้อ"), "bx-data"))

    # ลูกศรภายใน
    p.append(arrow("M690 182 H716"))            # web_chat → core
    p.append(arrow("M690 262 H716"))            # line → core
    p.append(arrow("M690 452 H716"))            # booking_api → booking
    p.append(arrow("M690 562 H704 V500 H716"))  # admin → booking
    p.append(arrow("M940 472 H956"))            # booking → vision (ตรวจสลิป)
    p.append(arrow("M1070 394 V410"))           # core → vision
    p.append(arrow("M950 550 V398"))            # data → core

    # หลักออกแบบ
    p.append(f'<rect class="bx-note" x="530" y="666" width="650" height="156" rx="14" />')
    p.append(text(548, 692, "หลักการออกแบบ", "th", "start"))
    notes = ["ราคา · ยอดมัดจำ · ช่องเวลา · ผลตรวจสลิป มาจากโค้ด — LLM แต่งเองไม่ได้ (ด่าน ③ ตรวจซ้ำ)",
             "แชทบอทอ่านข้อมูลการจองไม่ได้ — เช็ค/ยกเลิก/คืนเงิน ต้องยืนยันตัวตนในระบบจอง",
             "ทุกช่องทาง (เว็บ · เสียง · LINE) ใช้กฎชุดเดียวกันผ่านแกนกลางตัวเดียว",
             "API key อยู่ฝั่งเซิร์ฟเวอร์ · ข้อมูลทั้งหมดอยู่ใน Redis (serverless ไม่จำสถานะ)"]
    for i, n in enumerate(notes):
        p.append(text(548, 718 + i * 26, "• " + n, "tn2", "start"))

    # บริการภายนอก
    p.append(group(1225, 110, 340, 730, "บริการภายนอก (API)", "grp-ext"))
    ext = [
        (150, "Typhoon", "LLM ภาษาไทย", "ตอบแชท · ตรวจเจตนา ②"),
        (258, "Gemini", "Vision + Embedding", "อ่านรูปน้อง/สลิป · เวกเตอร์ RAG"),
        (366, "Cartesia", "Text-to-Speech", "เสียงของน้องหอม"),
        (474, "LINE Messaging API", "Webhook + Reply", "รับ-ตอบข้อความใน LINE"),
        (582, "Upstash Redis", "ที่เก็บข้อมูล", "ประวัติแชท · การจอง · ตัวนับคิว · รูป"),
        (690, "OpenStreetMap", "แผนที่ปักหมุดรับ-ส่ง", "โหลดจากเบราว์เซอร์โดยตรง"),
    ]
    for y, t, s1, s2 in ext:
        p.append(box(1245, y, 300, 92, t, (s1, s2), "bx-ext"))
    for y in (196, 304, 412, 520, 628):
        p.append(arrow(f"M1200 {y} H1241"))

    # ผลทดสอบ
    p.append(f'<rect class="bx-ok" x="40" y="640" width="425" height="200" rx="16" />')
    p.append(text(60, 670, "ทดสอบกับระบบจริง", "th", "start"))
    rows = [(f"ชุดคำถาม 10 ข้อ", f["q10"]), ("กฎต้องทำ/ห้ามทำ + ความปลอดภัย", f["safety"]),
            ("ทุก API endpoint", f["api"]), ("เวลาตอบเฉลี่ย", f"{f['avg']} วิ")]
    for i, (k, v) in enumerate(rows):
        p.append(text(60, 704 + i * 34, k, "tn2", "start"))
        p.append(text(445, 704 + i * 34, v, "big", "end"))
    return svg("\n".join(p), "ภาพรวมสถาปัตยกรรม: ลูกค้าและเจ้าของร้านใช้หน้าเว็บหรือ LINE เข้าสู่ FastAPI บน Vercel "
                               "ซึ่งมีแกนกลางแชท ระบบจอง และตัวอ่านรูป ต่อกับ Typhoon Gemini Cartesia LINE และ Redis")


# ---------------- สไลด์ 2: เส้นทางของ 1 ข้อความ ----------------

def slide_message(f: dict) -> str:
    p = [header("เส้นทางของ 1 ข้อความ (Data flow)",
                "ลูกค้าพิมพ์ “อาบน้ำหมาพันธุ์ปอมเท่าไหร่คะ” ในหน้าต่างแชท → POST /api/v1/chat/stream")]
    y, h, w = 300, 130, 186
    xs = [40, 258, 476, 694, 912, 1130, 1348]

    p.append(box(xs[0], y, w, h, "ลูกค้า", ("พิมพ์ข้อความ", "ในหน้าต่างแชท"), "bx-user"))
    p.append(box(xs[1], y, w, h, "ด่าน ① กฎในโค้ด", ("≤ 1000 ตัวอักษร", "≤ 15 ข้อความ/นาที", "คำต้องห้าม · injection")))
    p.append(box(xs[2], y, w, h, "ดักเบอร์ / เลขจอง", ("แชทดูคิวไม่ได้", "→ ตอบพาไปปุ่มเช็คคิว")))
    p.append(box(xs[3], y - 95, w, 110, "ด่าน ② ตรวจเจตนา", ("Typhoon จำแนก", "5 หมวด")))
    p.append(box(xs[3], y + 115, w, 110, "RAG", (f"ค้น {f['chunks']} ชิ้น → 4 ชิ้น", "embedding + TF-IDF")))
    p.append(text(xs[3] + w / 2, y + 70, "ทำพร้อมกัน", "th"))
    p.append(box(xs[4], y, w, h, "Typhoon ตอบ", ("กฎ + ข้อมูลร้าน 4 ชิ้น", "+ ประวัติ 12 ข้อความ", "สตรีมทีละคำ"), "bx-core"))
    p.append(box(xs[5], y, w, h, "ด่าน ③ ตรวจคำตอบ", ("ทีละประโยคก่อนส่ง", "ราคาต้องมีใน catalog", "ไม่มีข้อมูลส่วนตัว")))
    p.append(box(xs[6], y, w + 26, h, "หน้าจอลูกค้า", ("คำตอบ + แหล่งข้อมูล", "ปุ่ม เช็คคิว / ยกเลิก", "จองคิว / โทรหาร้าน"), "bx-hl"))

    for i in (0, 1):
        p.append(arrow(f"M{xs[i] + w} {y + h / 2} H{xs[i + 1] - 4}"))
    mid = y + h / 2
    p.append(arrow(f"M{xs[2] + w} {mid} H{xs[3] - 16} V{y - 40} H{xs[3] - 4}"))
    p.append(arrow(f"M{xs[3] - 16} {mid} V{y + 170} H{xs[3] - 4}"))
    p.append(arrow(f"M{xs[3] + w} {y - 40} H{xs[4] - 16} V{mid} H{xs[4] - 4}"))
    p.append(f'<path class="ln" d="M{xs[3] + w} {y + 170} H{xs[4] - 16} V{mid}" />')
    p.append(arrow(f"M{xs[4] + w} {mid} H{xs[5] - 4}"))
    p.append(arrow(f"M{xs[5] + w} {mid} H{xs[6] - 4}"))

    # ทางออกเมื่อไม่ผ่าน
    exits = [
        (xs[1] + w / 2, y + h, 560, ["ไม่ผ่าน → ปฏิเสธทันที", "ไม่เรียก LLM ไม่บันทึกประวัติ"]),
        (xs[2] + w / 2, y + h, 640, ["เป็นเบอร์/เลขจอง → ตอบสำเร็จรูป", "ไม่เรียก LLM ไม่เก็บเบอร์"]),
        (xs[5] + w / 2, y + h, 560, ["ราคา/ส่วนลดที่ไม่มีจริง → แทนทั้งคำตอบ", "เดาคิวว่าง · แนะนำร้านอื่น → ตัดประโยค"]),
    ]
    for x, y0, y1, lines in exits:
        p.append(arrow(f"M{x} {y0} V{y1 - 26}", "ln-no", "an"))
        for i, s in enumerate(lines):
            p.append(text(x, y1 + i * 22, s, "tn"))
    p.append(arrow(f"M{xs[3] + w / 2} {y - 95} V{y - 140}", "ln-no", "an"))
    p.append(text(xs[3] + w / 2, y - 150, "นอกเรื่อง / ขอข้อมูลคนอื่น / อันตราย → ปฏิเสธ ไม่เรียก LLM ตอบ", "tn"))

    # สิ่งที่ส่งให้ LLM + ตัวเลข
    p.append(f'<rect class="bx-note" x="40" y="700" width="1020" height="150" rx="14" />')
    p.append(text(60, 730, "ลำดับข้อความที่ส่งให้ Typhoon", "th", "start"))
    seq = [f"1. system: บทบาท + ต้องทำ {f['must']} ข้อ + ห้ามทำ {f['must_not']} ข้อ + ข้อมูลหลักร้าน (ชื่อ เวลา ติดต่อ บริการที่ไม่มี)",
           "2. system: “ข้อมูลร้านที่ค้นได้” — ผลวิเคราะห์รูป (ถ้ามี) + 4 ชิ้นจาก RAG",
           "3. ประวัติของ session นี้ 12 ข้อความล่าสุด   4. ข้อความใหม่ของลูกค้า"]
    for i, s in enumerate(seq):
        p.append(text(60, 760 + i * 28, s, "tn2", "start"))
    p.append(f'<rect class="bx-ok" x="1090" y="700" width="470" height="150" rx="14" />')
    p.append(text(1110, 730, "วัดจากระบบจริง (10 คำถาม)", "th", "start"))
    for i, (k, v) in enumerate([("เห็นคำแรก (เฉลี่ย)", f"{f['first']} วิ"), ("ตอบจบ (เฉลี่ย)", f"{f['avg']} วิ"),
                                ("ถูกดักที่ด่านขาเข้า", "0.5–1.8 วิ")]):
        p.append(text(1110, 766 + i * 32, k, "tn2", "start"))
        p.append(text(1540, 766 + i * 32, v, "big", "end"))
    return svg("\n".join(p), "ข้อความผ่านด่าน 1 การดักเบอร์โทร ด่าน 2 พร้อมการค้น RAG แล้ว Typhoon ตอบแบบสตรีมผ่านด่าน 3 ก่อนถึงลูกค้า")


# ---------------- สไลด์ 3: ระบบจองและยกเลิก ----------------

def slide_booking(f: dict) -> str:
    p = [header("ระบบจองคิวและยกเลิกคิว",
                "โค้ดล้วน ไม่ผ่าน LLM — แชทบอททำได้แค่พาลูกค้ามาที่ปุ่ม จึงหลอกบอทให้จอง/ยกเลิก/คืนเงินแทนคนอื่นไม่ได้")]

    def flow(y, title, nodes, exits, w=190, gap=30, x0=40):
        p.append(text(x0, y - 22, title, "th2", "start"))
        for i, (t, subs, cls) in enumerate(nodes):
            x = x0 + i * (w + gap)
            p.append(box(x, y, w, 120, t, subs, cls))
            if i:
                p.append(arrow(f"M{x - gap} {y + 60} H{x - 4}"))
        for i, lines in exits.items():
            x = x0 + i * (w + gap) + w / 2
            p.append(arrow(f"M{x} {y + 120} V{y + 152}", "ln-no", "an"))
            for j, s in enumerate(lines):
                p.append(text(x, y + 174 + j * 21, s, "tn"))

    d, cap, mx = f["deposit"], f["capacity"], f["max_pets"]
    flow(180, "จองคิว  ·  POST /api/v1/booking", [
        ("ฟอร์ม 3 ขั้น", ("ชื่อน้อง บริการ เจ้าของ เบอร์", f"จำนวนน้อง 1–{mx} ตัว", "เลือกเวลา · รับ-ส่ง"), "bx-user"),
        ("ตรวจฟอร์ม", ("ชื่อ · เบอร์ 10 หลัก", "ช่องเวลาเปิดจริง", "ไฟล์เป็นรูปจริง"), "bx"),
        ("กันช่องเวลา", (f"ช่าง {cap} คน · กันตามบริการ", "อาบน้ำ 2 ชม. · ตัดขน 3 ชม.", "ตัวที่ 3–4 = รอบถัดไป"), "bx"),
        ("Gemini อ่านสลิป", ("ยอด · ผู้รับ · ผู้โอน", "เลขอ้างอิง", "→ JSON"), "bx-ext"),
        ("โค้ดตรวจสลิป", (f"ยอด = {d} × จำนวนตัว", "+ ค่ารับส่งตามระยะ", "ผู้รับ = บัญชีร้าน"), "bx"),
        ("กันสลิปซ้ำ", ("เลขอ้างอิงใช้ได้", "ครั้งเดียว (SET NX)"), "bx"),
        ("ใบจอง", ("สถานะ “รอร้านยืนยัน”", "ไม่มีราคาบนใบจอง", "เจ้าของร้านกดยืนยัน"), "bx-hl"),
    ], {1: ["422 บอกช่องที่ผิด"], 2: ["409 คิวไม่พอ"], 4: ["ยอด/บัญชีผิด", "→ คืนช่องเวลา"], 5: ["เคยใช้แล้ว", "→ คืนช่องเวลา"]})

    h = f["cancel_hours"]
    flow(560, "ยกเลิกคิว + คืนเงิน  ·  POST /api/v1/booking/cancel", [
        ("ป๊อปอัปยกเลิก", ("จากแชท · หน้าแรก", "หรือหน้าเช็คคิว", "(เครื่องไหนก็ได้)"), "bx-user"),
        ("ยืนยันตัวตน", ("เลขจอง + เบอร์โทร", "+ ชื่อเจ้าของ", "ตรงครบทั้ง 3 อย่าง"), "bx"),
        ("ตรวจเวลา", (f"ก่อนนัด ≥ {h} ชั่วโมง", "สถานะยังไม่ยกเลิก"), "bx"),
        ("ยกเลิก + คืนช่อง", ("กันกดซ้ำ (SET NX)", "คืนทุกชั่วโมงที่กันไว้"), "bx"),
        ("คำขอคืนเงิน", ("ยอดที่ลูกค้าโอนมา", "เทียบชื่อบัญชีกับ", "ชื่อผู้โอนในสลิป"), "bx"),
        ("เจ้าของร้านโอนคืน", ("ตรวจยอดมัดจำเข้าบัญชี", "แนบสลิปโอนคืน", "แล้วจึงกดยืนยัน"), "bx-core"),
        ("ลูกค้าเห็นผล", ("หน้าเช็คคิว: โอนคืนแล้ว", "ดูสลิปได้หลังยืนยัน", "ชื่อเจ้าของ"), "bx-hl"),
    ], {1: ["ไม่ตรง → 404 ไม่บอกช่องที่ผิด", "ผิด 5 ครั้ง → ล็อก 24 ชม."], 2: ["409 เลยกำหนด"], 5: ["ไม่แนบสลิป → 422", "ไม่พบยอดเข้า → ไม่คืนเงิน"]})

    p.append(f'<rect class="bx-note" x="40" y="800" width="1520" height="62" rx="14" />')
    p.append(text(60, 838, "กันสวมรอยรับมัดจำ 3 ชั้น:  ① ต้องรู้เลขจอง + เบอร์ + ชื่อเจ้าของ (ชื่อไม่แสดงบนหน้าเช็คคิว)   "
                           "② ผิด 5 ครั้งล็อก 24 ชม. (นับใน Redis)   ③ โอนคืนเฉพาะบัญชีชื่อเดียวกับผู้โอนมัดจำ", "tn2", "start"))
    return svg("\n".join(p), "การจองผ่านการตรวจฟอร์ม กันช่องเวลา อ่านและตรวจสลิป กันสลิปซ้ำ แล้วออกใบจอง "
                               "ส่วนการยกเลิกต้องยืนยันตัวตนก่อนคืนช่องเวลาและสร้างคำขอคืนเงินให้เจ้าของร้านโอนคืนพร้อมสลิป")


# ---------------- หน้า HTML ----------------

CSS = """
@import url("https://fonts.googleapis.com/css2?family=Mali:wght@600;700&family=Nunito:wght@400;600;700;800&family=IBM+Plex+Sans+Thai+Looped:wght@400;500;600;700&display=swap");
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px 64px; background: #efe6d6; color: #5c3d2e;
  font-family: "Nunito", "IBM Plex Sans Thai Looped", sans-serif; }
.intro { max-width: 1100px; margin: 0 auto 20px; font-size: .95rem; }
.intro h1 { font-family: "Mali", sans-serif; font-size: 1.5rem; margin: 0 0 4px; }
.intro a { color: #b86e1b; }
.slide { max-width: 1600px; margin: 0 auto 28px; border: 2px solid #5c3d2e; border-radius: 18px; overflow: hidden; background: #fffbf3; }
.slide svg { display: block; width: 100%; height: auto; }
svg text { font-family: "Nunito", "IBM Plex Sans Thai Looped", sans-serif; fill: #5c3d2e; }
.bg { fill: #fffbf3; }
.h1 { font-family: "Mali", "Nunito", sans-serif; font-size: 36px; font-weight: 700; }
.h2 { font-size: 17px; fill: #7a5f50; }
.t { font-size: 16px; font-weight: 800; }
.tsb { font-size: 14px; font-weight: 800; }
.ts { font-size: 13px; fill: #6b5142; }
.tn { font-size: 13.5px; fill: #b0503a; font-weight: 600; }
.tn2 { font-size: 15px; }
.th { font-size: 16px; font-weight: 800; fill: #b86e1b; }
.th2 { font-family: "Mali", "Nunito", sans-serif; font-size: 21px; font-weight: 700; fill: #b86e1b; }
.gl { font-size: 14.5px; font-weight: 800; fill: #7a5f50; }
.gs { font-size: 13px; font-style: italic; fill: #7a5f50; }
.big { font-family: "Mali", "Nunito", sans-serif; font-size: 22px; font-weight: 700; fill: #4f6e37; }
.bx { fill: #ffffff; stroke: #5c3d2e; stroke-width: 2; }
.bx-ch { fill: #ffffff; stroke: #5c3d2e; stroke-width: 2; }
.bx-user { fill: #fff5e1; stroke: #5c3d2e; stroke-width: 2; }
.bx-core { fill: #f8dda8; stroke: #5c3d2e; stroke-width: 2.6; }
.bx-hl { fill: #f8dda8; stroke: #b86e1b; stroke-width: 2.6; }
.bx-ext { fill: #e9f0f7; stroke: #456a8c; stroke-width: 2; }
.bx-data { fill: #eef4e6; stroke: #4f6e37; stroke-width: 2; }
.bx-note { fill: #fff5e1; stroke: #5c3d2e; stroke-width: 1.5; stroke-dasharray: 6 5; }
.bx-ok { fill: #eef4e6; stroke: #4f6e37; stroke-width: 2; }
.grp { fill: none; stroke: #7a5f50; stroke-width: 1.6; stroke-dasharray: 7 6; }
.grp-main { fill: #fffdf8; stroke: #5c3d2e; stroke-width: 2.4; }
.grp-ext { fill: #f6f9fc; stroke: #456a8c; stroke-width: 1.8; stroke-dasharray: 7 6; }
.ln { stroke: #5c3d2e; stroke-width: 2; fill: none; }
.ln-dash { stroke: #456a8c; stroke-width: 1.8; fill: none; stroke-dasharray: 6 5; }
.ln-no { stroke: #b0503a; stroke-width: 1.8; fill: none; stroke-dasharray: 5 5; }
.num { fill: #5c3d2e; }
.numt { fill: #fffbf3; font-size: 14px; font-weight: 800; }
"""


def build() -> str:
    f = facts()
    # แผ่นที่ 1 = ภาพรวมระบบแบบ AWS (ชุดเดียวกับในเอกสาร report) · แผ่นภาพรวมแบบเดิมเก็บไว้ท้ายสุดเป็นแผ่นสำรอง
    slides = [("aws", aws.svg()), ("message", slide_message(f)), ("booking", slide_booking(f)), ("system", slide_system(f))]
    body = "\n".join(f'<section class="slide" id="{name}">\n{content}\n</section>' for name, content in slides)
    return f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Hom Hom Grooming — แผนภาพสถาปัตยกรรม (ฉบับนำเสนอ)</title>
<style>{CSS}</style>
</head>
<body>
<div class="intro">
  <h1>แผนภาพสถาปัตยกรรม — ฉบับนำเสนอ (16:9)</h1>
  <p>3 แผ่น: ภาพรวมระบบ (โครงแบบ AWS) · เส้นทางของ 1 ข้อความ · ระบบจองและยกเลิกคิว + แผ่นสำรอง 1 แผ่น (ภาพรวมระบบแบบเดิม)
  — ไฟล์ PNG 1920×1080 อยู่ใน <code>docs/img/</code>: <code>arch-aws.png</code>, <code>arch-2-message.png</code>, <code>arch-3-booking.png</code>, <code>arch-1-system.png</code> (สำรอง)
  · รายละเอียดฉบับเต็ม: <a href="architecture.html">architecture.html</a> · สร้างด้วย <code>python docs/build_slides.py --png</code> · เอกสารส่งอาจารย์: <a href="report.html">report.html</a></p>
</div>
{body}
</body>
</html>
"""


def export_png() -> None:
    from playwright.sync_api import sync_playwright

    img = ROOT / "docs" / "img"
    img.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1700, "height": 1000}, device_scale_factor=1.2)
        page.goto(OUT.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(800)
        for name, file in (("aws", "arch-aws"), ("system", "arch-1-system"), ("message", "arch-2-message"),
                           ("booking", "arch-3-booking")):
            page.locator(f"#{name} svg").screenshot(path=str(img / f"{file}.png"))
        browser.close()


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print("เขียน", OUT)
    if "--png" in sys.argv:
        export_png()
        print("ส่งออก PNG ที่ docs/img/")

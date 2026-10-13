"""แผนภาพสถาปัตยกรรมระบบแบบ AWS architecture diagram → docs/architecture-aws.html (+ docs/img/arch-aws.png)

ใช้:  python docs/build_aws_diagram.py          สร้างไฟล์ HTML
      python docs/build_aws_diagram.py --png    สร้าง HTML แล้วส่งออก PNG 1920×1080 ด้วย Playwright

โครงตามแนวทางของ AWS (aws.amazon.com/th/what-is/architecture-diagramming): ผู้ใช้อยู่ซ้าย · กรอบกลุ่มซ้อนกัน
(Cloud → Function → กลุ่มย่อย) มีไอคอนมุมบนซ้าย · บริการเป็นไอคอนสี่เหลี่ยมสีตามหมวด มีชื่อใต้ไอคอน ·
ลูกศรหักมุมฉาก มีเลขลำดับขั้นตอน และคำอธิบายขั้นตอนด้านล่าง
สีและตัวอักษรใช้ธีมเดียวกับระบบและแผนภาพชุดเดิม (พื้นครีม เส้นน้ำตาล ฟอนต์ Mali / Nunito) ให้เข้าชุดกับภาพที่ 2–3
แผนภาพชุดเดิม (docs/build_slides.py → docs/img/arch-1-system.png ฯลฯ) ยังเก็บไว้เป็นไฟล์สำรอง
"""

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "architecture-aws.html"
PNG = ROOT / "docs" / "img" / "arch-aws.png"
W, H = 1600, 900

INK = "#5c3d2e"
PAPER = "#fffbf3"
# สีตามหมวดบริการ (แบ่งหมวดแบบชุดไอคอน AWS แต่ใช้สีของธีมร้าน): โค้ดของเรา = ส้มน้ำตาล · บริการ AI/ภายนอก = น้ำเงิน ·
# ข้อมูล = เขียว · ความปลอดภัย = แดงอิฐ · เครือข่าย = น้ำตาลเทา · ผู้ใช้ = น้ำตาลเข้ม
COMPUTE, ML, DB, NET, INTEG, SEC, STORE, GENERAL = "#b86e1b", "#456a8c", "#456a8c", "#7a5f50", "#4f6e37", "#b0503a", "#4f6e37", "#5c3d2e"


def facts() -> dict:
    catalog = json.loads((ROOT / "shop" / "catalog.json").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "rag" / "index.json").read_text(encoding="utf-8"))
    return {
        "chunks": len(index["vectors"]),
        "faq": len(re.findall(r"^## \d+\.", (ROOT / "shop" / "faq.md").read_text(encoding="utf-8"), re.M)),
        "items": sum(len(catalog[k]) for k in ("services", "addons", "delivery", "packages", "products")),
        "line": catalog["shop"]["contacts"]["line"],
    }


# ---------------- ชิ้นส่วน SVG ----------------

GLYPH = {
    "user": '<circle cx="24" cy="18" r="7"/><path d="M10 40c0-8 6-13 14-13s14 5 14 13"/>',
    "edge": '<circle cx="24" cy="24" r="14"/><path d="M10 24h28M24 10c-6 4-6 24 0 28M24 10c6 4 6 24 0 28"/>',
    "api": '<path d="M18 15l-9 9 9 9M30 15l9 9-9 9M27 12l-6 24"/>',
    "chat": '<path d="M10 12h28v18H22l-8 7v-7h-4z"/>',
    "image": '<rect x="9" y="12" width="30" height="24" rx="2"/><circle cx="18" cy="20" r="3"/><path d="M9 32l9-8 7 6 5-4 9 8"/>',
    "sound": '<path d="M10 20h7l8-7v22l-8-7h-7zM31 18c3 3 3 9 0 12M35 14c5 5 5 15 0 20"/>',
    "calendar": '<rect x="9" y="12" width="30" height="26" rx="2"/><path d="M9 20h30M17 8v8M31 8v8M16 28l5 5 10-10"/>',
    "lock": '<rect x="12" y="22" width="24" height="16" rx="2"/><path d="M17 22v-6a7 7 0 0114 0v6"/>',
    "flow": '<rect x="8" y="10" width="12" height="10" rx="1"/><rect x="28" y="10" width="12" height="10" rx="1"/><rect x="18" y="30" width="12" height="10" rx="1"/><path d="M14 20v5h20v-5M24 25v5"/>',
    "shield": '<path d="M24 8l14 5v10c0 9-6 15-14 18-8-3-14-9-14-18V13z"/><path d="M17 24l5 5 9-10"/>',
    "search": '<circle cx="21" cy="21" r="10"/><path d="M29 29l10 10"/>',
    "eye": '<path d="M6 24c5-9 31-9 36 0-5 9-31 9-36 0z"/><circle cx="24" cy="24" r="5"/>',
    "button": '<rect x="8" y="16" width="32" height="16" rx="8"/><path d="M18 24h12"/>',
    "db": '<ellipse cx="24" cy="13" rx="13" ry="5"/><path d="M11 13v22c0 3 6 5 13 5s13-2 13-5V13M11 24c0 3 6 5 13 5s13-2 13-5"/>',
    "doc": '<path d="M13 8h15l8 8v24H13z"/><path d="M28 8v8h8M18 24h12M18 31h12"/>',
    "index": '<rect x="9" y="9" width="12" height="12"/><rect x="27" y="9" width="12" height="12"/><rect x="9" y="27" width="12" height="12"/><rect x="27" y="27" width="12" height="12"/>',
    "brain": '<rect x="13" y="13" width="22" height="22" rx="3"/><path d="M19 8v5M29 8v5M19 35v5M29 35v5M8 19h5M8 29h5M35 19h5M35 29h5"/><circle cx="24" cy="24" r="4"/>',
    "map": '<path d="M24 41c-8-10-11-15-11-20a11 11 0 0122 0c0 5-3 10-11 20z"/><circle cx="24" cy="21" r="4"/>',
    "cloud": '<path d="M14 34a8 8 0 01-1-16 11 11 0 0121-2 9 9 0 012 18z"/>',
    "lambda": '<path d="M13 10h6l12 28h5M21 22l-8 16"/>',
}


def text(x, y, s, cls="a-name", anchor="middle"):
    return f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(s)}</text>'


def node(cx, cy, glyph, color, title, *lines, size=52):
    """ไอคอนบริการ: สี่เหลี่ยมสีตามหมวด + ลายเส้นสีขาว ชื่อและคำอธิบายอยู่ใต้ไอคอน"""
    k = size / 48
    x, y = cx - size / 2, cy - size / 2
    out = [f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="10" fill="{color}"/>',
           f'<g transform="translate({x},{y}) scale({k})" fill="none" stroke="#fff" stroke-width="2.4" '
           f'stroke-linecap="round" stroke-linejoin="round">{GLYPH[glyph]}</g>',
           text(cx, y + size + 17, title, "a-name")]
    out += [text(cx, y + size + 33 + i * 15, line, "a-sub") for i, line in enumerate(lines)]
    return "".join(out)


def group(x, y, w, h, label, color, glyph=None, dashed=False, fill="none", width=1.8):
    """กรอบกลุ่มแบบ AWS: เส้นขอบบาง + ป้ายไอคอนมุมบนซ้าย"""
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{color}" stroke-width="{width}"{dash}/>']
    tx = x + 10
    if glyph:
        out.append(f'<path d="M{x} {y + 28}V{y + 14}a14 14 0 0 1 14-14H{x + 28}V{y + 20}a8 8 0 0 1-8 8z" fill="{color}"/>'
                   f'<g transform="translate({x + 2},{y + 2}) scale(0.5)" fill="none" stroke="#fff" stroke-width="3" '
                   f'stroke-linecap="round" stroke-linejoin="round">{GLYPH[glyph]}</g>')
        tx = x + 38
    out.append(f'<text x="{tx}" y="{y + 19}" class="a-group" fill="{color}">{escape(label)}</text>')
    return "".join(out)


def arrow(points, both=False, dashed=False):
    d = "M" + " L".join(f"{x} {y}" for x, y in points)
    extra = ' marker-start="url(#aws-ah2)"' if both else ""
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    return f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.8" marker-end="url(#aws-ah)"{extra}{dash}/>'


def step(x, y, n):
    return (f'<circle cx="{x}" cy="{y}" r="13" fill="{INK}"/>'
            f'<text x="{x}" y="{y + 5}" class="a-num" text-anchor="middle">{n}</text>')


# ---------------- แผนภาพ ----------------

def diagram() -> str:
    f = facts()
    p = []
    p.append(text(40, 46, "สถาปัตยกรรมระบบแชทบอท Hom Hom Grooming", "a-h1", "start"))
    p.append(text(40, 72, "ร้านอาบน้ำ-ตัดขนสุนัขและแมว · https://hom-hom-grooming.vercel.app", "a-h2", "start"))
    p.append('<image href="../static/img/logo-badge.png" x="1498" y="14" width="72" height="72"/>')

    # ---- ผู้ใช้ (ซ้าย) ----
    p.append(group(30, 100, 200, 590, "ผู้ใช้งาน", GENERAL, "user", fill="#fff5e1", width=2))
    p.append(node(130, 185, "user", GENERAL, "ลูกค้า (เว็บเบราว์เซอร์)", "แชท · ส่งรูป · โหมดเสียง", "จองคิว · เช็คคิว · ยกเลิกคิว"))
    p.append(node(130, 385, "chat", INTEG, "LINE Platform", f"ลูกค้าในแอป LINE {f['line']}", "Messaging API (webhook + reply)"))
    p.append(node(130, 585, "user", GENERAL, "เจ้าของร้าน", "หลังบ้าน /admin", "ยืนยันคิว · โอนเงินคืน"))

    # ---- Vercel Cloud ----
    p.append(group(270, 100, 880, 590, "Vercel Cloud", GENERAL, "cloud", fill="#fffdf8", width=2.4))
    p.append(node(345, 385, "edge", NET, "Edge Network", "HTTPS · CDN", "ไฟล์หน้าเว็บ", "HTML / CSS / JS"))

    p.append(group(430, 140, 700, 535, "Serverless Function · FastAPI (Python)", COMPUTE, "lambda", dashed=True))

    # API routes
    p.append(group(448, 180, 190, 480, "API routes (channels/)", "#7a5f50", fill="#ffffff"))
    api = [("chat", "Chat API", "/api/v1/chat/stream (SSE)"), ("image", "Attachments API", "/api/v1/attachments"),
           ("sound", "TTS API", "/api/v1/tts/stream"), ("chat", "LINE Webhook", "/line/webhook"),
           ("calendar", "Booking API", "/api/v1/booking/*"), ("lock", "Admin API", "/api/v1/admin/*")]
    for i, (g, title, path) in enumerate(api):
        p.append(node(543, 228 + i * 75, g, COMPUTE if g != "lock" else SEC, title, path, size=34))

    # Application logic
    p.append(group(668, 180, 444, 300, "ชั้นประมวลผล (Application logic)", "#b86e1b", fill="#f8dda8", width=2.4))
    logic = [("flow", COMPUTE, "Assistant pipeline", "chatbot/ · แกนกลางของทุกช่องทาง"),
             ("shield", SEC, "Guardrails 3 ด่าน", "กฎในโค้ด · ตรวจเจตนา · ตรวจคำตอบ"),
             ("search", ML, "RAG retriever", "rag/ · embedding + TF-IDF"),
             ("eye", ML, "Vision analyzer", "vision/ · รูปน้อง · สลิป"),
             ("calendar", COMPUTE, "Booking service", "booking/ · คิว · ยกเลิก · คืนเงิน"),
             ("button", COMPUTE, "Quick actions", "ปุ่มจองคิว · เช็คคิว · ยกเลิก")]
    for i, (g, color, title, sub) in enumerate(logic):
        # แบ่งคำอธิบายเป็น 2 บรรทัดที่จุดคั่นแรก ให้ไม่ล้นคอลัมน์
        head, _, tail = sub.partition(" · ")
        p.append(node(742 + (i % 3) * 148, 240 + (i // 3) * 140, g, color, title, head, tail, size=44))

    # ข้อมูลที่ deploy พร้อมโค้ด
    p.append(group(668, 500, 444, 160, "ข้อมูลร้านที่ deploy พร้อมโค้ด", "#4f6e37", fill="#eef4e6"))
    p.append(node(742, 555, "doc", STORE, "shop/", f"ราคา {f['items']} รายการ", f"FAQ {f['faq']} ข้อ · นโยบาย", size=44))
    p.append(node(890, 555, "index", STORE, "rag/index.json", f"{f['chunks']} ชิ้นข้อมูล", "เวกเตอร์ 768 มิติ", size=44))
    p.append(node(1038, 555, "doc", STORE, "prompts/", "กฎต้องทำ / ห้ามทำ", "คำสั่งตรวจเจตนา · อ่านรูป", size=44))

    # ---- บริการภายนอก ----
    p.append(group(1210, 100, 360, 590, "บริการภายนอก (เรียกผ่าน HTTPS API)", "#456a8c", "api", dashed=True, fill="#f6f9fc"))
    ext = [("brain", ML, "Typhoon LLM", "เรียบเรียงคำตอบภาษาไทย · ตรวจเจตนา"),
           ("eye", ML, "Google Gemini", "Vision อ่านรูป · Embedding สำหรับ RAG"),
           ("sound", ML, "Cartesia TTS", "แปลงคำตอบเป็นเสียง (โหมดอวตาร)"),
           ("db", DB, "Upstash Redis", "ประวัติแชท · การจอง · ตัวนับคิว · รูป"),
           ("map", NET, "OpenStreetMap", "แผนที่ปักหมุดรับ-ส่ง (โหลดจากเบราว์เซอร์)")]
    ys = [172, 285, 398, 511, 624]
    for (g, color, title, sub), y in zip(ext, ys):
        p.append(node(1390, y, g, color, title, sub, size=44))

    # ---- ลูกศร ----
    p.append(arrow([(160, 185), (250, 185), (250, 370), (317, 370)]))                 # ลูกค้าเว็บ → Edge
    p.append(arrow([(158, 385), (317, 385)], both=True))                              # LINE ↔ Edge
    p.append(arrow([(160, 585), (250, 585), (250, 400), (317, 400)]))                 # เจ้าของร้าน → Edge
    p.append(arrow([(373, 385), (446, 385)]))                                         # Edge → API
    p.append(arrow([(638, 330), (666, 330)]))                                         # API → logic
    p.append(arrow([(890, 480), (890, 498)], both=True))                              # logic ↔ ข้อมูลร้าน
    p.append(arrow([(1112, 200), (1160, 200), (1160, 172), (1364, 172)], both=True))  # → Typhoon
    p.append(arrow([(1112, 285), (1364, 285)], both=True))                            # → Gemini
    p.append(arrow([(1112, 398), (1364, 398)], both=True))                            # → Cartesia
    p.append(arrow([(1112, 455), (1160, 455), (1160, 511), (1364, 511)], both=True))  # → Redis
    p.append(arrow([(130, 690), (130, 705), (1390, 705), (1390, 688)], dashed=True))  # เบราว์เซอร์ → OSM

    for x, y, n in [(250, 270, 1), (410, 385, 2), (652, 310, 3), (912, 489, 4), (1250, 172, 5), (1250, 285, 6),
                    (1250, 511, 8), (1250, 398, 7)]:
        p.append(step(x, y, n))

    # ---- คำอธิบายขั้นตอน ----
    steps = [
        "ลูกค้าพิมพ์ข้อความ ส่งรูป หรือกดจองคิว ผ่านเว็บหรือ LINE · เจ้าของร้านเข้าหลังบ้านด้วยรหัสผ่าน",
        "Vercel ส่งหน้าเว็บให้ลูกค้า และส่งคำขอต่อไปยังโปรแกรมของเรา (FastAPI)",
        "โปรแกรมแยกงานตามประเภท: ข้อความไปแชทบอท · รูปไปตัวอ่านรูป · การจองไประบบจองคิว",
        "แชทบอทตรวจว่าข้อความปลอดภัยไหม แล้วค้นข้อมูลร้านที่ตรงกับคำถาม",
        "Typhoon ช่วยตรวจเจตนาของข้อความ และเขียนคำตอบภาษาไทยจากข้อมูลร้านที่ค้นได้",
        "Gemini อ่านรูปน้องหรือสลิป และแปลงคำถามเป็นตัวเลขเพื่อใช้ค้นข้อมูลร้าน",
        "ตรวจคำตอบอีกครั้งก่อนส่งถึงลูกค้าพร้อมปุ่มทางลัด · หน้าคุยด้วยเสียงแปลงคำตอบเป็นเสียงด้วย Cartesia",
        "ประวัติแชท การจอง จำนวนคิวแต่ละชั่วโมง และรูป เก็บไว้ที่ Redis",
    ]
    for i, s in enumerate(steps):
        col, row = divmod(i, 4)
        x, y = 44 + col * 790, 738 + row * 40
        p.append(step(x, y, i + 1))
        p.append(text(x + 24, y + 5, s, "a-legend", "start"))
    return "".join(p)


CSS = f"""
@import url("https://fonts.googleapis.com/css2?family=Mali:wght@600;700&family=Nunito:wght@400;600;700;800&family=IBM+Plex+Sans+Thai+Looped:wght@400;500;600;700&display=swap");
text{{font-family:"Nunito","IBM Plex Sans Thai Looped",sans-serif;fill:{INK}}}
.a-h1{{font-family:"Mali","Nunito",sans-serif;font-size:30px;font-weight:700}} .a-h2{{font-size:16px;fill:#7a5f50}}
.a-group{{font-size:14px;font-weight:800}}
.a-name{{font-size:13.5px;font-weight:800}} .a-sub{{font-size:11.5px;fill:#6b5142}}
.a-num{{font-size:14px;font-weight:800;fill:{PAPER}}} .a-legend{{font-size:13px}}
"""


def svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img"
 aria-label="แผนภาพสถาปัตยกรรมระบบแชทบอท Hom Hom Grooming">
<defs>
<marker id="aws-ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker>
<marker id="aws-ah2" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 0L0 5L10 10z" fill="{INK}"/></marker>
<style>{CSS}</style>
</defs>
<rect width="{W}" height="{H}" fill="{PAPER}"/>
{diagram()}
</svg>"""


def main() -> int:
    html = f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>สถาปัตยกรรมระบบ Hom Hom Grooming</title>
<style>body{{margin:0;background:{PAPER}}}svg{{display:block;width:100%;height:auto}}</style></head>
<body>{svg()}</body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"เขียน {OUT}")
    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1.2)
            page.goto(OUT.as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.locator("svg").screenshot(path=str(PNG))
            b.close()
        print(f"ส่งออก {PNG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

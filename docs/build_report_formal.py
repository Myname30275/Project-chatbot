"""รายงานฉบับทางการ (PDF): หน้าปก · คำนำ · สารบัญ (มีเลขหน้า) · เนื้อหาเดียวกับ docs/report.html · ฟอนต์ TH Sarabun New

ใช้:  python docs/build_report_formal.py      → docs/report-formal.pdf (แนบรูปทดสอบ รวมสลิปจริง — อย่าขึ้น git)
เนื้อหาทุกหัวข้อดึงจาก docs/build_report.py (ตัวเดียวกับรายงานฉบับปกติ)
เลขหน้าในสารบัญได้จากการเรนเดอร์เนื้อหาก่อน แล้วหาตัวทำเครื่องหมายที่มองไม่เห็นหน้าหัวข้อใน PDF
"""

import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "docs"))
import build_report as br  # noqa: E402

DOCS = PROJECT / "docs"
OUT = DOCS / "report-formal.pdf"

COURSE = "06048308 Intelligent Chatbot Development"
FACULTY = "คณะเทคโนโลยีสารสนเทศ"
INSTITUTE = "สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง"
TERM = "ภาคเรียนที่ 1 ปีการศึกษา 2569"
ADVISOR = "อาจารย์ชัชรินทร์ เลิศยศบดินทร์"

_FONT_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts" / "THSarabunNew.ttf"
_FONT_SRC = 'local("TH Sarabun New"), local("THSarabunNew")' + (f', url("{_FONT_FILE.as_uri()}")' if _FONT_FILE.exists() else "")

FORMAL_CSS = f"""
@font-face{{font-family:"THSarabun";src:{_FONT_SRC};font-weight:400}}
:root{{--ink:#000;--muted:#333;--line:#999;--head:#ececec;--accent:#000;--ok:#1a6b3c;--bad:#a1271e;--bg:#fff;--paper:#fff}}
html,body{{background:#fff}}
body{{font-family:"THSarabun","TH Sarabun New","Sarabun",sans-serif;font-size:16pt;line-height:1.25;color:#000}}
main{{max-width:none;margin:0;padding:0;box-shadow:none}}
h1,h2,h3,h4{{font-family:inherit;color:#000}}
h2{{font-size:20pt;margin:18pt 0 6pt;padding-bottom:3pt;border-bottom:1px solid #000;break-after:avoid}}
h2.chapter{{break-before:page;margin-top:0}}
h3{{font-size:18pt;margin:12pt 0 4pt}}
h4{{font-size:16pt}}
p{{margin:4pt 0}}
a{{color:inherit;text-decoration:none}}
code{{font-family:"THSarabun","TH Sarabun New",sans-serif;font-size:1em;background:none;padding:0}}
table{{font-size:14pt;line-height:1.15;margin:6pt 0 10pt}}
table.small{{font-size:12.5pt}}
th,td{{border:1px solid #777;padding:3pt 5pt;overflow-wrap:break-word;word-break:normal}}
th{{background:#e8e8e8;font-weight:700}}
.note,.why,figcaption{{font-size:14pt;color:#222}}
.chip{{font-size:13pt}}
.result{{background:#f3f3f3;border-left:3pt solid #555}}
.fix__box{{background:#f7f7f7;border-left-color:#888}}
.fix__box--after{{background:#f3f3f3;border-left-color:#333}}
.thumb{{width:80pt;height:70pt}}
figure img{{border:1px solid #bbb}}
.mark{{position:absolute;font-size:1px;line-height:1px;color:#fff;white-space:nowrap}}
@page{{size:A4;margin:25mm 25mm 25mm 38mm}}
@media print{{body{{font-size:16pt}}table{{font-size:14pt}}table.small{{font-size:12.5pt}}h2{{margin-top:18pt}}h2.chapter{{margin-top:0}}}}
"""

FRONT_CSS = """
.page{position:relative;height:246mm;break-after:page;overflow:hidden}
.page:last-child{break-after:auto}
.pno{position:absolute;top:0;right:0;font-size:16pt}
.cover{border:none;padding:0;margin:0;text-align:center;display:flex;flex-direction:column;justify-content:space-between}
.cover h1{font-size:28pt;line-height:1.3;margin:0}
.cover .big{font-size:22pt;font-weight:700;margin:8pt 0;line-height:1.35}
.cover p{margin:2pt 0;color:#000;text-align:center}
.cover img{width:34mm;height:34mm;display:block;margin:0 auto 8mm}
.cover .people p{font-size:18pt}
.title-center{text-align:center;font-size:22pt;font-weight:700;margin:0 0 14pt}
.preface p{text-indent:12mm;margin:0 0 6pt;text-align:justify}
.preface .title-center{text-indent:0;text-align:center}
.sign p{text-align:right;text-indent:0;margin:2pt 0}
.sign{margin-top:16pt}
.toc{width:100%;border-collapse:collapse;font-size:16pt;border:none}
.toc td{border:none;padding:1pt 0;vertical-align:bottom;background:none}
.toc td.pg{text-align:right;width:14mm}
.toc td.lv2{padding-left:9mm}
.toc .head td{font-weight:700;padding-bottom:4pt}
.toc .dots{display:flex;align-items:baseline;gap:4pt}
.toc .dots::after{content:"";flex:1;border-bottom:1.5px dotted #000;transform:translateY(-4pt);min-width:8mm}
"""


def headings(body: str):
    """ใส่ id + ตัวทำเครื่องหมายหน้าหัวข้อ h2/h3 · หัวข้อใหญ่ (h2) ขึ้นหน้าใหม่ · คืนรายการ (ระดับ, id, ข้อความ)"""
    found = []

    def repl(m):
        level = int(m.group(1))
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        hid = f"h{len(found) + 1}"
        found.append((level, hid, text))
        cls = ' class="chapter"' if level == 2 else ""
        return f'<h{level} id="{hid}"{cls}><span class="mark">QQ{hid}QQ</span>{m.group(2)}</h{level}>'

    return re.sub(r"<h([23])>(.*?)</h\1>", repl, body, flags=re.S), found


def front_matter(cat, toc_rows: str) -> str:
    shop = cat["shop"]
    name = br.e(shop.get("assistant_name", "น้องหอม"))
    people = "".join(f"<p>{br.e(n)} &nbsp; รหัสนักศึกษา {sid}</p>" for sid, n in br.DEVELOPERS)
    today = br.thai_date(datetime.date.today().isoformat())
    return f"""
<section class="page cover">
  <div>
    <img src="../static/img/logo-badge.png" alt="" />
    <h1>รายงานการพัฒนาโครงงาน</h1>
    <p class="big">แชทบอทผู้ช่วยตอบลูกค้า “{name}”<br>ร้าน {br.e(shop['name'])} ({br.e(shop.get('name_th', ''))})</p>
  </div>
  <div class="people"><p><b>จัดทำโดย</b></p>{people}</div>
  <div class="people"><p><b>เสนอ</b></p><p>{ADVISOR}</p></div>
  <div>
    <p>รายงานนี้เป็นส่วนหนึ่งของรายวิชา {COURSE}</p>
    <p>{FACULTY} {INSTITUTE}</p>
    <p>{TERM}</p>
  </div>
</section>
<section class="page preface">
  <span class="pno">ก</span>
  <p class="title-center">คำนำ</p>
  <p>รายงานฉบับนี้เป็นส่วนหนึ่งของรายวิชา {COURSE} จัดทำขึ้นเพื่อนำเสนอการพัฒนาแชทบอท “{name}”
  ผู้ช่วยตอบลูกค้าของร้านอาบน้ำ-ตัดขนสุนัขและแมว {br.e(shop['name'])} ซึ่งตอบคำถามจากข้อมูลจริงของร้านด้วย RAG ภาษาไทย
  ประเมินราคาจากรูปสัตว์เลี้ยงและตรวจสลิปมัดจำด้วย Vision คุยกับลูกค้าด้วยเสียงผ่านอวาตาร์
  และมีระบบป้องกันการใช้งานผิดวัตถุประสงค์ (Guardrails) หลายชั้น</p>
  <p>เนื้อหาประกอบด้วยข้อมูลของธุรกิจ แผนภาพสถาปัตยกรรมและการไหลของข้อมูล บทบาทหน้าที่ของผู้พัฒนา
  ผลการทดสอบกับระบบจริงทั้งชุดคำถาม ชุดภาพ และกรณีด้านความปลอดภัย รวมถึงจุดที่ปรับปรุงพร้อมผลก่อนและหลังการแก้ไข</p>
  <p>คณะผู้จัดทำหวังว่ารายงานฉบับนี้จะเป็นประโยชน์ต่อผู้ที่สนใจการพัฒนาแชทบอทสำหรับธุรกิจขนาดเล็ก
  หากมีข้อผิดพลาดประการใด คณะผู้จัดทำขออภัยมา ณ ที่นี้</p>
  <div class="sign"><p>คณะผู้จัดทำ</p><p>{today}</p></div>
</section>
<section class="page">
  <span class="pno">ข</span>
  <p class="title-center">สารบัญ</p>
  <table class="toc"><tr class="head"><td></td><td class="pg">หน้า</td></tr>{toc_rows}</table>
</section>
"""


def toc_html(items, pages) -> str:
    rows = []
    for level, hid, text in items:
        cls = "lv2" if level == 3 else ""
        weight = ' style="font-weight:700"' if level == 2 else ""
        rows.append(f'<tr><td class="{cls}"{weight}><span class="dots">{br.e(text)}</span></td>'
                    f'<td class="pg">{pages.get(hid, "")}</td></tr>')
    return "".join(rows)


def page_html(extra_css: str, content: str) -> str:
    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;700&display=swap" rel="stylesheet">
<style>{br.CSS}{FORMAL_CSS}{extra_css}</style></head><body><main>{content}</main></body></html>"""


def render(pw, html: str, path: Path, numbered: bool) -> None:
    tmp = DOCS / f".formal-{os.getpid()}-{path.stem}.html"  # อยู่ใน docs/ ให้รูป img/... หาเจอ
    tmp.write_text(html, encoding="utf-8")
    try:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(tmp.as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        opts = dict(path=str(path), format="A4", print_background=True, prefer_css_page_size=True)
        if numbered:
            opts.update(display_header_footer=True, footer_template="<span></span>",
                        header_template='<div style="width:100%;font-family:\'TH Sarabun New\',\'Sarabun\',sans-serif;'
                                        'font-size:16pt;text-align:right;padding-right:25mm;padding-top:8mm">'
                                        '<span class="pageNumber"></span></div>')
        page.pdf(**opts)
        b.close()
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    import pymupdf
    from playwright.sync_api import sync_playwright

    cat = json.loads((PROJECT / "shop" / "catalog.json").read_text(encoding="utf-8"))
    ten, ps = br.load("test-10-questions.json"), br.load("test-prompt-safety.json")
    ep, img = br.load("test-endpoints.json"), br.load("test-images.json")
    f = br.facts(cat, ten, ps, ep, img)
    body = "".join([
        br.section_project(cat, f), br.section_business(cat, f), br.section_architecture(f, ep), br.section_roles(f),
        br.section_questions(ten), br.section_images(img), br.section_safety(ps), br.section_improvements(f),
        br.section_checklist(f),
    ])
    marked, items = headings(body)
    clean = re.sub(r'<span class="mark">QQh\d+QQ</span>', "", marked)

    with tempfile.TemporaryDirectory() as td, sync_playwright() as pw:
        td = Path(td)
        probe_pdf, body_pdf, front_pdf = td / "probe.pdf", td / "body.pdf", td / "front.pdf"
        render(pw, page_html("", marked), probe_pdf, numbered=True)
        render(pw, page_html("", clean), body_pdf, numbered=True)
        pages = {}
        with pymupdf.open(probe_pdf) as doc, pymupdf.open(body_pdf) as final:
            if doc.page_count != final.page_count:
                print("คำเตือน: จำนวนหน้ารอบวัดกับรอบจริงไม่เท่ากัน", doc.page_count, final.page_count)
            for i, pg in enumerate(doc, 1):
                for hid in re.findall(r"QQ(h\d+)QQ", pg.get_text()):
                    pages.setdefault(hid, i)
        missing = [t for _, hid, t in items if hid not in pages]
        if missing:
            print("หาเลขหน้าไม่เจอ:", missing)
        render(pw, page_html(FRONT_CSS, front_matter(cat, toc_html(items, pages))), front_pdf, numbered=False)

        out = pymupdf.open()
        with pymupdf.open(front_pdf) as fr, pymupdf.open(body_pdf) as bd:
            front_n = fr.page_count
            out.insert_pdf(fr)
            out.insert_pdf(bd)
        toc = [[1, "คำนำ", 2], [1, "สารบัญ", 3]] + [
            [level - 1, text, front_n + pages[hid]] for level, hid, text in items if hid in pages]
        out.set_toc(toc)
        out.set_metadata({"title": f"รายงานการพัฒนาโครงงาน แชทบอทร้าน {cat['shop']['name']}",
                          "author": ", ".join(n for _, n in br.DEVELOPERS)})
        out.save(OUT, garbage=3, deflate=True)
        print(f"ส่งออก {OUT} · {out.page_count} หน้า (ส่วนหน้า {front_n} · เนื้อหา {out.page_count - front_n}) · หัวข้อ {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# CLAUDE.md — บันทึกสำหรับ Claude ที่ทำงานกับโปรเจกต์นี้

แชทบอท "น้องหอม" ของร้านอาบน้ำ-ตัดขนสุนัขและแมว **Hom Hom Grooming (หอมหอม กรูมมิ่ง)** — Final Project วิชา
06048308 Intelligent Chatbot Development (IT KMITL, ภาคเรียนที่ 1/2569) · งานคู่: แพรว พลอยกระจ่างศรี (68076050) ·
ภาณุพงศ์ บุตรดี (68076052) · อาจารย์ผู้สอน: อาจารย์ชัชรินทร์ เลิศยศบดินทร์
เว็บจริง: https://hom-hom-grooming.vercel.app (`/` แชท + จองคิว · `/avatar` คุยด้วยเสียง · `/check` · `/admin`) · LINE OA @103fgxwt

## วิธีทำงานกับผู้ใช้
- **ตอบเป็นภาษาไทยเสมอ** รวมถึงสรุปท้ายงาน โค้ดและคอมเมนต์ในโค้ดก็เขียนไทยตามแบบที่มีอยู่
- งาน UI: ทำบนเครื่องและส่งภาพตัวอย่างให้ดูก่อน **deploy เมื่อผู้ใช้สั่งเท่านั้น** (commit/push ก็รอคำสั่งเช่นกัน)
- รายงาน = HTML + PDF · แผนภาพ = โครงแบบ AWS แต่ใช้ธีมสีครีม/น้ำตาลของร้าน
- บอทตอบเฉพาะเรื่องของร้าน · เรื่องที่ผิดไม่ได้ (ราคา คิว ราคาจากรูป) ให้โค้ดตอบ ไม่ปล่อยให้ LLM ตัดสินเอง

## สิ่งที่ห้ามทำ
- ห้าม commit `.env` (key ของ Typhoon, Gemini, Groq, Cartesia, LINE, VERCEL_TOKEN) และห้ามพิมพ์ค่า secret ออกมา
- **ห้าม `git add` ทั้งโฟลเดอร์** — stage ทีละไฟล์และอ่าน `git status` ก่อนเสมอ (เคยหลุดสลิปจริงขึ้น GitHub จาก `git add tests/`)
- รูปสลิปจริง/รูปส่วนตัวอยู่ในเครื่องเท่านั้น (gitignored): `tests/test 10 pic/`, `docs/img/test-images/`, `docs/*.pdf`, `Demo/`
  — PDF รายงานทุกฉบับมีรูปสลิปจริงฝังอยู่
- ห้ามแก้ git config แบบ global · ห้าม force push / เขียนประวัติ git ใหม่เอง (ระบบอนุญาตอัตโนมัติจะบล็อก ให้เตรียมคำสั่งให้ผู้ใช้รันเอง)

## คำสั่งที่ใช้บ่อย
```bash
# git — โฟลเดอร์อยู่ใน Box จึงต้องมี safe.directory ทุกคำสั่ง และ commit ด้วยตัวตนที่ผู้ใช้กำหนด
git -c safe.directory=* status
git -c safe.directory=* -c user.name=Myname -c user.email=Myname30275@gmail.com commit -m "..."
# ข้อความ commit ปิดท้ายด้วยบรรทัด Co-Authored-By ตามที่ระบบกำหนด

# deploy (push ขึ้น GitHub ไม่ได้ deploy — ต้องใช้ Vercel CLI)
export $(grep ^VERCEL_TOKEN= .env) && npx --yes vercel@latest deploy --prod --yes --token "$VERCEL_TOKEN"

python -m unittest discover -s tests          # เทสอัตโนมัติ (ไม่เรียก API ภายนอก)
uvicorn main:app --port 8000                  # รันบนเครื่อง (แก้ prompt / shop / index แล้วต้องรีสตาร์ต)
python -m rag.build_index                     # ต้องรันทุกครั้งที่แก้ไฟล์ใน shop/
python docs/build_report.py --pdf             # รายงานฉบับปกติ → docs/report.html + report.pdf
python docs/build_report_formal.py            # รายงานฉบับทางการ (ปก คำนำ สารบัญ TH Sarabun New) → docs/report-formal.pdf
python docs/build_aws_diagram.py --png        # แผนภาพภาพรวม (AWS layout)
python docs/build_slides.py --png             # แผนภาพย่อยทั้งหมด → docs/img/arch-*.png
python tests/run_10_questions.py              # ชุดทดสอบกับเว็บจริง (มี run_prompt_safety / run_endpoint_check / run_images ด้วย)
```
ตั้ง `PYTHONIOENCODING=utf-8` (และ `python -X utf8`) ไม่งั้นข้อความไทยในเทอร์มินัลจะเพี้ยน

## โครงระบบโดยย่อ
- **ทุกช่องทาง** (แชทเว็บ, LINE, หน้าเสียง) เรียก `chatbot/assistant.py` ตัวเดียว: กฎขาเข้า → ตัวตรวจ LLM ∥ RAG → คำตอบจากโค้ด
  (คิวว่าง ราคาตามน้ำหนัก ดักเบอร์/เลขจอง) → Typhoon สตรีม → ตรวจคำตอบทีละประโยค (`guardrails/output_guard.py`) → ปุ่มทางลัด (`chatbot/actions.py`)
- **ข้อมูลร้าน** อยู่ที่ `shop/catalog.json` (แหล่งราคาเดียว) + `policies.md` + `faq.md` · `shop/pricing.py` แตกชื่อรายการเป็นคำสำคัญให้ตัวตรวจ/การค้นใช้
- **อ่านรูป** `vision/image_analyzer.py`: Gemini Flash (บัญชี 2 → บัญชี 1) → Flash Lite (บัญชี 2 → บัญชี 1) → Groq `qwen/qwen3.8-27b`
  (สลับลำดับได้ด้วย `VISION_KEY2_FIRST` / `VISION_BACKUP_FIRST`)
  ตัวที่ยังมีตัวถัดไปลองครั้งเดียว · โค้ดคิดราคาจาก catalog (`vision/pet_estimate.py`) · ลูกสัตว์ (`life_stage=young`) ได้แพ็กเกจลูกสุนัขแทนราคาตามพันธุ์
- **จองคิว** `booking/` เป็นโค้ดล้วน ไม่ผ่าน LLM · ฟอร์ม 3 ขั้น: บริการ + วันเวลา → ข้อมูลน้อง (+ รับ-ส่ง) → สลิปมัดจำ · เจ้าของร้านยืนยันคิวเสมอ
- **หน้าเสียง** `static/js/voice.js` + `voice-avatar.js` (VRM): Web Speech API → แกนกลางเดียวกับแชท → Cartesia · ขีดแสดงช่วงอ่านเป็น "ถึง" (`channels/tts.py`)
- ข้อมูลเก็บที่ Upstash Redis · เซิร์ฟเวอร์เป็น FastAPI บน Vercel (serverless)

## เรื่องที่เจอมาแล้ว
- Heredoc ใน Git Bash ทำ `\\` หาย และพังกับบางชุดอักษรไทย/เครื่องหมายคำพูด → เขียนสคริปต์แก้ไฟล์เป็นไฟล์ Python แล้วรัน
- CSS/JS ทุกไฟล์ต่อท้ายด้วย `?v={{ asset_v() }}` — ใส่ให้ไฟล์ใหม่ด้วย
- สไตล์ `svg { width: 20px }` ทั้งเว็บทำให้ SVG ของไลบรารีหด → เขียน override เฉพาะจุด
- ป๊อปอัปจองกับยกเลิกใช้ `.sheet__panel` ร่วมกัน → ในเทสให้ระบุ `#booking-sheet`
- ทดสอบหน้าเสียงด้วย Playwright ต้องใช้ `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`
  และ `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` · ปิดเส้นทาง `/api/v1/tts/stream` ไว้เพื่อไม่ใช้เครดิต Cartesia
- เซิร์ฟเวอร์ทดสอบสำหรับเบราว์เซอร์: สร้าง script ที่แทน `image_analyzer.analyze` ด้วยผลสลิปจำลอง ตั้ง `ADMIN_PASSWORD=test` แล้วรัน `main:app` ที่พอร์ต 8001
- โควตาฟรี: Groq ราว 2 รูป/นาที · Gemini รายวันรีเซ็ต 14:00 น. เวลาไทย — อย่ายิงซ้ำเพื่อทดสอบโดยไม่จำเป็น
- Vercel แพลนฟรีเก็บ log ย้อนหลังราว 1 ชั่วโมง
- ทุกการแก้ที่เกิดจากการทดสอบจริง บันทึกเป็น "จุดปรับปรุงที่ N" ใน `docs/test-log.md` (ล่าสุด 22) แล้วสร้างรายงานใหม่

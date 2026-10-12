# Hom Hom Grooming Chatbot (FastAPI + Vercel)

แชทบอท "น้องหอม" ของร้านอาบน้ำ-ตัดขนสุนัขและแมว Hom Hom Grooming — Final Project วิชา 06048308 Intelligent Chatbot Development
ผู้พัฒนา: แพรว พลอยกระจ่างศรี (68076050) · ภาณุพงศ์ บุตรดี (68076052)

- เว็บจริง: https://hom-hom-grooming.vercel.app (`/` แชท + จองคิว · `/avatar` โหมดเสียง · `/check` เช็คคิว/ยกเลิก · `/admin` หลังบ้าน)
- ตอบจากข้อมูลร้านเท่านั้น (RAG ภาษาไทย) · ประเมินราคาจากรูปสัตว์เลี้ยงและตรวจสลิปมัดจำ (Vision) · ด่านความปลอดภัย 3 ชั้น
- จองคิวบนเว็บ: เลือกบริการ วันเวลา แนบสลิป ได้ใบจองทันที · ยกเลิกและขอเงินคืนเองได้ · เจ้าของร้านยืนยันคิวในหลังบ้าน
- ถามคิวว่างในแชท ("พรุ่งนี้ว่างไหม" "มีคิวว่างวันไหนบ้าง") → บอทตอบว่าตรวจสอบคิวว่างได้จากปุ่ม "จองคิว" (ตอบด้วยโค้ด ไม่ผ่าน LLM) วันและเวลาที่ว่างจริงแสดงในฟอร์มจองขั้นแรก · วันหยุด/วันที่ผ่านแล้ว/เกินช่วงที่เปิดจองมีข้อความบอกเหตุผล ใช้ได้ทั้งแชท LINE และโหมดเสียง

LLM คุยผ่าน OpenAI-compatible Chat Completions API ค่าเริ่มต้นใช้ [Typhoon](https://opentyphoon.ai) (โมเดลภาษาไทย มี free tier)
สลับไปผู้ให้บริการอื่นที่เป็น OpenAI-compatible ได้โดยไม่ต้องแก้โค้ด

## เอกสารและผลทดสอบ

| ไฟล์ | เนื้อหา |
|---|---|
| [docs/report.html](docs/report.html) | เอกสารการพัฒนาโครงงานและผลการทดสอบ (ฉบับส่งอาจารย์) — สร้างด้วย `python docs/build_report.py --pdf` |
| [docs/architecture-slides.html](docs/architecture-slides.html) | แผนภาพฉบับนำเสนอ: ภาพรวมระบบ · เส้นทางของ 1 ข้อความ · ระบบจอง (PNG ใน `docs/img/`) |
| [docs/system-architecture.md](docs/system-architecture.md) | สถาปัตยกรรมฉบับเต็ม endpoint ทั้งหมด และเหตุผลของการออกแบบ |
| [docs/test-log.md](docs/test-log.md) | บันทึกผลทดสอบและจุดปรับปรุงทุกจุด (ก่อน-หลัง) |
| [docs/booking-plan.md](docs/booking-plan.md) | ข้อตกลงและรายละเอียดของระบบจองคิว |

## การทดสอบ

```bash
python -m unittest discover -s tests        # เทสอัตโนมัติ (ไม่เรียก API ภายนอก)
python tests/run_10_questions.py            # 10 คำถามกับเว็บจริง → docs/test-10-questions.json
python tests/run_prompt_safety.py           # กฎต้องทำ/ห้ามทำ + ความปลอดภัย → docs/test-prompt-safety.json
python tests/run_endpoint_check.py          # ทุก endpoint (โหมดไม่สร้างการจอง) → docs/test-endpoints.json
python tests/run_images.py                  # ชุดภาพทดสอบ → docs/test-images.json
```

สคริปต์ `run_*.py` รับ URL เป็นอาร์กิวเมนต์ได้ (เช่น `http://127.0.0.1:8000`) · ชุดภาพใน `tests/test 10 pic` มีสลิปจริงของผู้พัฒนา
จึงไม่อยู่ใน repo — ใช้รูปของตัวเองแทนได้โดยแก้รายการใน `tests/run_images.py`
แก้ข้อมูลใน `shop/` แล้วต้องรัน `python -m rag.build_index` ทุกครั้ง

## โครงสร้างโปรเจกต์

แบ่งโฟลเดอร์ตามชั้นของสถาปัตยกรรม

```
api/index.py                   entrypoint ที่ Vercel เรียกใช้ (import app จาก main.py)
main.py                        สร้าง FastAPI app, mount static/templates, รวม router
config.py                      อ่านค่าตั้งค่าจาก environment variables

channels/        ① ช่องทางเข้า (API layer)
  web_chat.py                  /api/v1/* ของหน้าเว็บ (สตรีม SSE, History, ไฟล์แนบ) → เรียก assistant
  tts.py                       /api/v1/tts/* — proxy เสียง Cartesia สำหรับโหมดเสียง
  line_webhook.py              LINE OA @103fgxwt: แชท + รูปน้อง/สลิป (จอง/เช็คคิวส่งลิงก์เว็บ)
  booking_api.py               /api/v1/booking/* — ช่องเวลา จองคิว เช็คคิว ยกเลิก ดูสลิปโอนคืน
  admin.py                     /admin + /api/v1/admin/* — หลังบ้านของเจ้าของร้าน (ยืนยันคิว โอนคืน)
booking/         ระบบจองคิว (โค้ดล้วน ไม่ผ่าน LLM)
  slots.py                     ช่องเวลา + กันเวลาช่างตามบริการที่เลือก (อาบน้ำ 2 ชม. ตัดขน 3 ชม.)
  service.py                   จอง ตรวจสลิป ยืนยันตัวตนก่อนยกเลิก คำขอคืนเงิน
  pickup.py, store.py          ค่ารับ-ส่งตามระยะทาง · ที่เก็บข้อมูล (in-memory หรือ Redis)
chatbot/         ② แกนกลางที่ทุกช่องทางใช้ร่วมกัน
  assistant.py                 pipeline กลาง: guardrails → (คำตอบจากโค้ด) → RAG → LLM → ตรวจขาออก → บันทึกประวัติ
  llm_client.py                คุยกับผู้ให้บริการ LLM (+ retry เมื่อโดน rate limit)
  conversation_store.py        ประวัติบทสนทนา + ไฟล์แนบ (in-memory หรือ Redis/Vercel KV)
  prompt_builder.py            ประกอบ system prompt จาก prompts/ + ข้อมูลหลักใน shop/
  actions.py                   ปุ่มทางลัดใต้คำตอบ (จองคิว เช็คคิว ยกเลิก ติดต่อร้าน) + ดักเบอร์โทร/เลขจองในแชท
  availability.py              ถามคิวว่าง → ตอบด้วยโค้ดให้ตรวจสอบจากปุ่มจองคิว (+ เหตุผลถ้าเป็นวันหยุด/วันที่จองไม่ได้) ไม่ผ่าน LLM
  search.py                    ค้นเว็บอัตโนมัติ (Tavily) — ปิดไว้ บอทร้านตอบจากข้อมูลร้านเท่านั้น
rag/             RAG: ค้นคืนข้อมูลร้านตามคำถาม
  chunker.py                   แบ่ง shop/ เป็น 48 ชิ้น (บริการละชิ้น, หัวข้อนโยบาย/FAQ ละชิ้น)
  retriever.py                 hybrid: embedding (Gemini) 0.7 + TF-IDF character n-gram 0.3
  build_index.py               สร้าง index.json — รันใหม่ทุกครั้งที่แก้ shop/
  index.json                   embedding ที่สร้างไว้ล่วงหน้า (commit ขึ้น git)
guardrails/      ③ ความปลอดภัย 3 ด่าน (ฟรี ไม่ต้องใช้ key เพิ่ม)
  input_rules.py               ด่าน 1: ความยาว, ความถี่, blocklist.txt, รูปแบบ prompt injection
  judge.py                     ด่าน 2: ใช้ Typhoon จำแนกเจตนา (SAFE/OFF_TOPIC/INJECTION/PRIVACY/HARMFUL)
  output_guard.py              ด่าน 3: ราคา/ส่วนลดต้องมีจริง, ห้ามหลุดข้อมูลส่วนตัวหรือกฎภายใน
  pipeline.py, categories.py   รวมด่าน + ข้อความปฏิเสธภาษาไทย
vision/          ④ Vision: รูปสัตว์ → ประเมินราคา, รูปสลิป → ตรวจมัดจำ
  documents.py                 อ่านไฟล์แนบ (PDF: pymupdf + typhoon-ocr, รูป → image_analyzer)
  image_analyzer.py            Gemini จำแนกรูป สัตว์/สลิป/อื่น ๆ เป็น JSON (มีโมเดลสำรอง)
  pet_estimate.py              รูปสัตว์ → ราคาจาก catalog + ข้อความตอบลูกค้าทันที
  slip_check.py                รูปสลิป → เทียบยอดมัดจำ/ชื่อผู้รับ (แอดมินเป็นผู้ยืนยัน)
shop/            ⑤ ข้อมูลร้าน: catalog.json (ราคา), policies.md, faq.md + pricing.py
prompts/         ⑥ prompt แยกเป็นไฟล์ (chat_system.txt, guard_judge.txt, image_analyze.txt, voice_hint.txt, line_hint.txt)
static/, templates/  ⑦ UX/UI — / (หน้าแรก + แชท + ฟอร์มจอง), /avatar (อวตาร + เสียง), /check (เช็คคิว), /admin (หลังบ้าน)
                               voice.js ตัดคำตอบเป็นท่อนส่งทำเสียงที่ท้ายประโยค/เว้นวรรค/ขอบคำไทย (ไม่ผ่ากลางคำ)
tests/                         unit tests (test_*.py) + สคริปต์ทดสอบกับระบบจริง (run_*.py)
docs/                          เอกสารส่งอาจารย์ แผนภาพ บันทึกผลทดสอบ
```

## รันในเครื่องตัวเอง

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # แล้วใส่ค่า LLM_API_KEY ของตัวเอง
uvicorn main:app --reload
```

เปิด http://127.0.0.1:8000

ขอ API key ฟรีของ Typhoon ได้ที่ [opentyphoon.ai](https://opentyphoon.ai) →
เข้าสู่ระบบ → Playground → API Keys

## ตั้งค่า .env

| ตัวแปร | ตัวอย่าง | หมายเหตุ |
|---|---|---|
| `LLM_BASE_URL` | `https://api.opentyphoon.ai/v1` | ต้องจบด้วย `/v1` |
| `LLM_API_KEY` | (จาก dashboard ผู้ให้บริการ) | อย่า commit ค่านี้ขึ้น git |
| `LLM_MODEL` | `typhoon-v2.5-30b-a3b-instruct` | หรือ `typhoon-v2.1-12b-instruct` |
| `LLM_TEMPERATURE` | `0.7` | ไม่ตั้ง = ใช้ค่า default ของผู้ให้บริการ |
| `LLM_MAX_TOKENS` | `16384` | ความยาวคำตอบสูงสุด; **ถ้าไม่ตั้ง Typhoon จะ default แค่ 512** (คำตอบยาวจะถูกตัด) — 16384 คือเพดานของ Typhoon |
| `KV_REST_API_URL` | (จาก Vercel KV) | ดูหัวข้อ "ความจำบทสนทนา" ด้านล่าง |
| `KV_REST_API_TOKEN` | (จาก Vercel KV) | |
| `ALLOWED_ORIGINS` | `https://myapp.com` | ตั้งเมื่อมี frontend คนละโดเมน (คั่นด้วย `,`) |
| `VISION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | ดูหัวข้อ "แนบไฟล์" ด้านล่าง |
| `VISION_API_KEY` | (Gemini key จาก aistudio.google.com) | ไม่ตั้ง = รูปอ่านได้แค่ข้อความ (OCR) |
| `VISION_MODEL` | `gemini-flash-latest` | โมเดล vision (alias ตัวล่าสุด) |
| `ADMIN_PASSWORD` | (ตั้งเอง) | รหัสเข้าหลังบ้าน `/admin` — ไม่ตั้ง = ปิดหลังบ้าน |
| `CARTESIA_API_KEY` | (จาก cartesia.ai) | เสียงตอบในโหมด `/avatar` — ไม่ตั้ง = ใช้เสียงของเบราว์เซอร์ |
| `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` | (จาก LINE Developers) | ตั้งเมื่อจะต่อ LINE OA |

### สลับไปผู้ให้บริการอื่น

โค้ดคุยด้วยฟอร์แมต OpenAI-compatible Chat Completions ล้วนๆ จึงสลับได้แค่แก้ `.env`:

- **LM Studio (รันในเครื่อง):** `LLM_BASE_URL=http://127.0.0.1:1234/v1` แล้วเปิด local server
- **OpenRouter:** `LLM_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL=openai/gpt-4o-mini`

> Typhoon ไม่มี endpoint `GET /v1/models` — หน้า `/api/v1/models` จึงจะคืนแค่โมเดล
> ตัวที่ตั้งใน `LLM_MODEL` (fallback อัตโนมัติ ไม่ error)

## ความจำบทสนทนา (สำคัญตอน deploy)

`chatbot/conversation_store.py` เลือกที่เก็บประวัติอัตโนมัติจาก environment:

- **ไม่ตั้ง `KV_REST_API_*`** → เก็บใน dict ในหน่วยความจำของโปรเซส
  ใช้ได้ตอนรันในเครื่อง (process เดียว) แต่บน Vercel serverless แต่ละ request อาจ
  ตกคนละ instance ทำให้ AI "ลืม" บทสนทนาก่อนหน้าแบบไม่สม่ำเสมอ
- **ตั้ง `KV_REST_API_URL` + `KV_REST_API_TOKEN`** → เก็บที่ Redis (Upstash REST API
  ตัวเดียวกับที่ Vercel KV ให้มา) ทุก instance อ่าน/เขียนร่วมกัน บอทจึงจำได้จริง
  key ใช้ `conv:<session_id>` มีอายุ 7 วัน (`CONVERSATION_TTL_SECONDS`)

วิธีเปิด Vercel KV และ deploy ทั้งหมดอยู่ใน [DEPLOY_STEPS.md](DEPLOY_STEPS.md)

## แนบไฟล์ (PDF / รูปภาพ / ข้อความ)

ปุ่ม 📎 ในแถบพิมพ์ → อัปโหลดไฟล์ → ระบบดึงข้อความมาแปะใน context ของโมเดลแชต
(ไม่ใช่ RAG — ยัดข้อความตรงๆ) ไฟล์อยู่กับ session จนกด ✕ หรือ "เริ่มใหม่"

- **PDF ที่เป็นข้อความ** → `pymupdf` ดึงตรงๆ (ฟรี ไม่เรียก AI)
- **PDF สแกน / รูปภาพ** → `typhoon-ocr` ถอดข้อความ (ใช้ `LLM_API_KEY` เดิม)
- **รูปภาพ + `VISION_API_KEY`** → Gemini จำแนกเป็นรูปสัตว์เลี้ยง / สลิป / อื่น ๆ แล้วโค้ดคิดราคาหรือตรวจยอดจาก `shop/catalog.json`
  (รูปที่ไม่เกี่ยวกับร้านบอทไม่บรรยาย)
  ขอ key ฟรีที่ [aistudio.google.com](https://aistudio.google.com) (ไม่ต้องผูกบัตร)

จำกัด: 8 MB/ไฟล์, PDF อ่าน 12 หน้าแรก (`config.py`), รวมข้อความทุกไฟล์ 80k ตัวอักษร
บน Vercel: `typhoon-ocr` จำกัด 20 req/นาที และ PDF สแกนหน้าเยอะอาจใช้เวลานาน —
ถ้าโดน timeout ให้ตั้ง Max Duration เป็น 60s ที่ Vercel Settings → Functions

## โหมดเสียงและการทดลอง Cartesia

หน้า `/avatar` คือโหมดคุยด้วยเสียง: อวตาร VRM พนักงานร้าน (`static/avatar/Avatar grooming.vrm`,
ท่า `Idle.fbx`) + STT ของเบราว์เซอร์ + เสียงตอบจาก Cartesia (เลือกเสียงได้ในหน้านั้น)
Cartesia รับเสียงแบบ PCM streaming ผ่าน backend โดยเก็บคีย์ใน `CARTESIA_API_KEY`
ถ้าไม่ตั้ง key จะใช้เสียงไทยของเบราว์เซอร์แทน (Chrome บน Windows อาจไม่มีเสียงไทย ให้ใช้ Edge)
ดู [การตั้งค่า ผลทดสอบ และงานค้าง](docs/cartesia-trial.md)

## Deploy ขึ้น Vercel

ย่อ: push ขึ้น GitHub → New Project บน Vercel → ใส่ Environment Variables →
(ถ้าอยากให้จำบทสนทนา) เปิด Vercel KV แล้ว connect → Deploy

ขั้นตอนเต็มพร้อมเช็คลิสต์ทดสอบ: [DEPLOY_STEPS.md](DEPLOY_STEPS.md)

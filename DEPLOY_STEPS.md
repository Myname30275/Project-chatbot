# ขั้นตอน Deploy

คู่มือพา chatbot จากเครื่องตัวเองขึ้น Vercel โดยใช้ Typhoon API (free tier)
และเปิด Vercel KV เพื่อให้บอทจำบทสนทนาได้จริง

---

## 1. รันในเครื่องและทดสอบ

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

ถ้า Windows ติด execution policy ตอน activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### ขอ Typhoon API key (ฟรี)

1. เข้า https://opentyphoon.ai → สมัคร/เข้าสู่ระบบ
2. ไป Playground → API Keys → สร้าง key (ขึ้นต้นด้วย `sk-...`)
3. free tier จำกัด 5 requests/วินาที และ 200 requests/นาที ต่อโมเดล

### สร้าง .env

```bash
cp .env.example .env
```

แก้ `.env`:

```
LLM_BASE_URL=https://api.opentyphoon.ai/v1
LLM_API_KEY=<key ที่เพิ่งสร้าง>
LLM_MODEL=typhoon-v2.5-30b-a3b-instruct
SYSTEM_PROMPT="คุณคือผู้ช่วย AI ที่เป็นมิตรและตอบเป็นภาษาไทย"
```

> `.env` ถูก gitignore ไว้แล้ว — ห้าม commit key ขึ้น git เด็ดขาด

### รัน

```bash
uvicorn main:app --reload
```

### เช็คลิสต์ทดสอบ (local)

1. เปิด http://127.0.0.1:8000 — หน้าเว็บขึ้นธีมเข้ม หัวเรื่อง "NO ONE"
2. พิมพ์ "สวัสดี" — คำตอบสตรีมมาทีละคำ ไม่มีแถบ error แดง
3. เปิด http://127.0.0.1:8000/api/v1/models — เห็น `typhoon-v2.5-30b-a3b-instruct`
   (Typhoon ไม่มี endpoint นี้จริง แอป fallback ให้ — ถือว่าปกติ)
4. ทดสอบปุ่ม **หยุด** (กดตอนบอทกำลังพิมพ์) และปุ่ม **เริ่มใหม่**
5. ทดสอบความจำ: "ผมชื่อโดม" แล้วถาม "ผมชื่ออะไร" — ในเครื่องต้องจำได้ (process เดียว)

กด `Ctrl+C` เพื่อหยุดเซิร์ฟเวอร์

---

## 2. ขึ้น GitHub repo ของตัวเอง

```bash
git init                          # ถ้ายังไม่ใช่ git repo
git add -A
git status                        # ยืนยันว่า .env ไม่ขึ้นในรายการ
git commit -m "chatbot + Typhoon API + Redis conversation store"
```

ตรวจก่อน push ว่าไม่มี secret หลุด:

```bash
git ls-files | grep env           # ต้องเจอแค่ .env.example
```

สร้าง repo เปล่าใน github.com (Private ได้) แล้ว:

```bash
git remote add origin https://github.com/<username>/<repo>.git
git branch -M main
git push -u origin main
```

---

## 3. Deploy ขึ้น Vercel

1. เข้า https://vercel.com → ล็อกอินด้วย GitHub → **Add New → Project** → เลือก repo
2. ไม่ต้องแตะ build settings (Vercel อ่าน `vercel.json` เอง)
3. กาง **Environment Variables** ใส่ 3 ตัว:

   | Key | Value |
   |---|---|
   | `LLM_BASE_URL` | `https://api.opentyphoon.ai/v1` |
   | `LLM_API_KEY` | `<Typhoon key ของคุณ>` |
   | `LLM_MODEL` | `typhoon-v2.5-30b-a3b-instruct` |

   (จะใส่ `SYSTEM_PROMPT`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` เพิ่มด้วยก็ได้)

4. กด **Deploy** → ได้ URL เช่น `https://your-repo.vercel.app`

ตอนนี้บอทใช้งานได้แล้ว แต่ยัง **ลืมบทสนทนาเป็นครั้งคราว** เพราะยังไม่มีที่เก็บกลาง
(อ่านต่อข้อ 4)

---

## 4. เปิด Vercel KV (จำเป็นสำหรับ History / จำบทสนทนา)

`chatbot/conversation_store.py` เก็บบทสนทนาในหน่วยความจำ process ถ้าไม่เจอ
`KV_REST_API_URL` / `KV_REST_API_TOKEN` — บน serverless แต่ละ request ตกคนละ
instance และ instance ถูกปิดทิ้งได้ตลอด **ประวัติ + History จะหาย** ต้องมี Redis กลาง:

1. ใน Vercel project → แท็บ **Storage** → **Create Database** → เลือก **KV**
   (ให้บริการโดย Upstash ผ่าน Vercel Marketplace)
2. ตั้งชื่อ → **Create** → หน้า **Connect Project** เลือก project นี้ →
   ติ๊กให้ครอบ **ทุก environment (Production / Preview / Development)** → **Connect**
3. Vercel จะฉีด env `KV_REST_API_URL`, `KV_REST_API_TOKEN` ให้อัตโนมัติ
4. **Redeploy** ทั้ง production (main) และ preview branch ที่กำลังรีวิว

> ถ้า integration ฉีดชื่อ `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` แทน
> แอปก็รองรับทั้งสองชื่อ · key ที่ใช้: `sess:<session_id>` (1 ก้อนต่อผู้ใช้
> เก็บทุกบทสนทนา) อายุ 7 วัน

### ทดสอบหลังเปิด KV

1. คุย 2-3 รอบ → **รีเฟรชหน้า** → ข้อความเดิมยังอยู่
2. กด **เริ่มแชตใหม่** → คุยต่อ → เปิด **ประวัติ** เห็นทั้งสองบท สลับไปมาได้
3. **Redeploy อีกครั้ง** (จำลอง instance ใหม่) → ประวัติยังอยู่ = KV ทำงาน

---

## 5. (ทางเลือก) เปิดการ "เข้าใจรูปภาพ" ด้วย Gemini

ปุ่ม 📎 อ่าน **ข้อความ** ในไฟล์/รูปได้เลยโดยไม่ต้องตั้งอะไร (typhoon-ocr ใช้ `LLM_API_KEY` เดิม)
ถ้าอยากให้ AI **บรรยายรูปถ่าย/กราฟ/ไดอะแกรม** ด้วย ต้องต่อโมเดล vision แยก:

1. ขอ API key ฟรีที่ [aistudio.google.com](https://aistudio.google.com) → Get API key (ไม่ต้องผูกบัตร)
2. Vercel → Settings → Environment Variables ใส่:

   | Key | Value |
   |---|---|
   | `VISION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` |
   | `VISION_API_KEY` | `<Gemini key>` |
   | `VISION_MODEL` | `gemini-flash-latest` |

3. **Redeploy**

---

## 6. (ทางเลือก) เปิด "ค้นเว็บอัตโนมัติ" ด้วย Tavily

เวลาผู้ใช้ถามข้อมูลล่าสุด (ข่าว/ราคา/ผลกีฬา/เหตุการณ์ปัจจุบัน) บอตจะประเมินเอง →
ค้นเว็บ → ตอบพร้อมชิปแหล่งอ้างอิงใต้คำตอบ ไม่ตั้ง key = ฟีเจอร์นี้ปิด (ทุกอย่างอื่นปกติ)

1. ขอ API key ฟรีที่ [tavily.com](https://tavily.com) → Sign up → API Keys
   (ไม่ต้องผูกบัตร, 1000 ครั้ง/เดือน, key ขึ้นต้น `tvly-`)
2. Vercel → Settings → Environment Variables ใส่:

   | Key | Value |
   |---|---|
   | `SEARCH_API_KEY` | `<Tavily key>` |

   (ปรับเพิ่มได้: `SEARCH_MAX_RESULTS` ค่าเริ่ม 5, `WEB_SEARCH_ENABLED=false` เพื่อปิดทั้งฟีเจอร์)
3. **ตั้ง Settings → Functions → Max Duration = 60s** — รอบที่ค้นเว็บจะช้ากว่าปกติ
   (ประเมิน ~0.7s + ค้น ~2s ก่อนเริ่มสตรีมคำตอบ) อาจเกิน default 10s
4. **Redeploy**

### ทดสอบ

1. ถาม "ข่าว AI ล่าสุดวันนี้" → เห็น "กำลังค้นเว็บ: ..." → คำตอบมี [1][2] + ชิปแหล่ง
2. ถาม "2+2 เท่ากับเท่าไหร่" / "เขียนกลอนเรื่องแมว" → ตอบทันที ไม่ค้น
3. ปิดสวิตช์ "ค้นเว็บอัตโนมัติ" ในหน้าตั้งค่า → ถามข้อ 1 ซ้ำ → ไม่ค้น

---

## 7. โหมดสนทนาด้วยเสียง (ไม่ต้องตั้งค่าอะไร)

ปุ่ม 🎙️ ในแถบพิมพ์ → เปิดโหมดเสียงเต็มจอ (อินเทอร์เฟซเซลล์ประสาท) คุยโต้ตอบได้

ทำงานในเบราว์เซอร์ล้วน ไม่มีบริการเสียงภายนอก ไม่มีค่าใช้จ่าย:
- **STT**: Web Speech API (`th-TH`) — รองรับ **Chrome / Edge / Chrome บน Android** เท่านั้น
  (iOS Safari / Firefox จะขึ้นข้อความแจ้งว่าไม่รองรับ)
- **LLM**: `/api/v1/chat/stream` เดิม — ประวัติ/ค้นเว็บ/Settings ใช้ต่อได้
- **TTS**: `speechSynthesis` ของอุปกรณ์ — เลือกเสียงได้ในหน้า **ตั้งค่า → เสียงพูด**
  (รายชื่อเสียงมาจาก OS ของผู้ใช้แต่ละคน)
- ต้องเป็น **HTTPS** (Vercel เป็นอยู่แล้ว) ไมโครโฟนถึงจะใช้ได้

---

## หมายเหตุ

- แก้ env ทีหลังต้องกด **Redeploy** ใน Vercel ถึงจะมีผล
- Typhoon free tier ตอบ `429` เมื่อยิงถี่เกิน — แอปมี retry + exponential backoff
  ให้อัตโนมัติ (`chatbot/llm_client.py`) ถ้ายังไม่ผ่านจะขึ้นข้อความไทยสุภาพแทน error ดิบ
- ถ้าต้อง throughput สูง Typhoon แนะนำให้ใช้ผ่าน Together AI (ดู docs.opentyphoon.ai)

### ไฟล์แนบ + `vercel.json`

- `requirements.txt` เพิ่ม `pymupdf`, `python-multipart` — Vercel ติดตั้งให้อัตโนมัติ
- `vercel.json` ใช้ฟอร์แมต `builds`/`routes` (แบบ `rewrites` จะ rewrite path ทำให้ FastAPI
  routing พังทั้งหน้า) — **ถ้า OCR PDF สแกนหลายหน้าโดน timeout 10 วิ** ให้ไปตั้ง
  Max Duration ที่ Vercel: **Settings → Functions → Max Duration → 60s** (ไม่ต้องแก้ vercel.json)
- `typhoon-ocr` จำกัด 2 req/วินาที, 20 req/นาที — PDF สแกน >12 หน้าจะอ่านแค่ 12 หน้าแรก

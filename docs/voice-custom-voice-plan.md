# แผนงานถัดไป: ใช้เสียงโคลนของตัวเองในโหมดสนทนาด้วยเสียง

## สถานะล่าสุด — 2026-09-21: Cartesia ผ่านแล้ว ใช้เป็นระบบหลัก

- **ผู้ใช้ทดสอบผ่านเบราว์เซอร์จริงครบวงจร (mic → Typhoon → เสียงโคลน Cartesia) แล้ว — สรุปว่า
  "ใช้ได้เลย" ในโหมดเสียง** คุณภาพเสียงไทยของเสียงโคลนผ่านเกณฑ์ (ต่างจากเสียงสำเร็จรูป Suda
  รอบก่อนที่ตกไป) — ปิดข้อกังวลเรื่องภาษาไทยที่ค้างมาตั้งแต่รอบทดลองแรกแล้ว
- สร้างเสียงโคลนจริงด้วย Cartesia Instant Clone แล้ว มี 4 เสียงในลิสต์ (ASN/krt/Dora/Hiso)
- UI รวมเป็นช่อง "เสียงพูด" เดียว (เสียงโคลน Cartesia + เสียงเบราว์เซอร์) — ตัด dropdown
  provider กับช่อง URL Colab ออกแล้ว path Qwen/Colab ที่เพิ่ง prefetch ให้ **เข้าไม่ถึงจาก UI
  แล้ว** (โค้ดยังอยู่ ไม่ได้ลบ)
- แก้บั๊กเสียง "ตึ๊ด" คั่นรอยต่อประโยคด้วย fade in/out สั้นแล้ว
- รายละเอียดการตั้งค่า ผลวัด และงานค้างที่เหลือ (deploy/merge) อยู่ใน [cartesia-trial.md](cartesia-trial.md)

หัวข้อด้านล่างเป็นประวัติแผนและการทดลองก่อนหน้า (Qwen/Colab, prefetch pipeline) — เก็บไว้
เผื่ออยากย้อนกลับไปใช้ทางฟรีในอนาคต ไม่ใช่ทิศทางที่ใช้งานจริงตอนนี้แล้ว

## อัปเดต 2 — prefetch ท่อนถัดไปล่วงหน้า (commit ล่าสุด, `feat/cloned-voice-tts`)

ทดสอบจริงแล้วพบว่าคำตอบยาวยังดีเลย์อยู่ดี แม้สตรีมทีละประโยคแล้ว — สาเหตุคือของเดิมยิง
`/tts` ท่อนถัดไป **หลัง** ท่อนก่อนหน้า "จัดคิวเล่นเสร็จ" เท่านั้น (ไม่ใช่หลังเล่นจบ แต่ก็ยัง
ต้องรอ fetch+decode ของท่อนก่อนหน้าให้เสร็จก่อน) ทำให้ทุกท่อนต้องจ่าย "ค่าเดินทางเครือข่าย/
คิวของเซิร์ฟเวอร์" (เช่น tunnel ของ Colab) ซ้ำทุกครั้ง

**ลองวิธีอื่นตามที่ขอ (ไม่จำกัดความยาวคำตอบ)** — เอา `max_tokens` cap ที่เคยเพิ่มออกแล้ว
(ผู้ใช้ไม่ต้องการให้ตัดเนื้อหา) เปลี่ยนไปแก้ที่ pipeline แทน:

- `voice.js`: **ยิง `/tts` ล่วงหน้าได้พร้อมกันสูงสุด 2 ท่อน** (`TTS_PREFETCH`) — พอท่อน N เริ่มยิง
  ท่อน N+1 ก็ยิงตามทันทีโดยไม่ต้องรอผลของท่อน N (แต่ยัง **เล่นเรียงตามลำดับเดิมเสมอ** — await
  ท่อนเก่าสุดก่อนเสมอแม้ท่อนถัดไปจะเตรียมเสร็จก่อน) ทำให้เวลาเครือข่าย/คิวเซิร์ฟเวอร์ของท่อนถัดไป
  ซ้อนทับกับเวลา generate ของท่อนปัจจุบันแทนที่จะต่อกันเป็นเส้นตรง
- แยก `speakServerChunk()` เดิมเป็น `prepareServerChunk()` (ยิง+ถอดรหัสเสียงอย่างเดียว ไม่แตะ
  state/เล่นเสียง — เรียกล่วงหน้าได้หลายท่อนพร้อมกันอย่างปลอดภัย) + `kickoffChunk()` (ตัดสินใจ
  server/browser ตอน "เริ่มยิง" ไม่ใช่ตอน "ถึงคิวเล่น") + จุดเล่น/fallback อยู่ใน `pumpSpeakQueue()`
- `ttsAbort` (ตัวเดียว) → `ttsAborts` (Set) เพราะยิงพร้อมกันได้หลายคำขอ ต้อง abort ได้ทุกตัวตอน
  พูดแทรก/ปิดโหมด

**ทดสอบยืนยัน:** จำลองเซิร์ฟเวอร์ TTS ช้า (สุ่ม gen 1.2 วิ/ท่อน + ล็อก GPU ตัวเดียวเหมือนของจริง)
gap ระหว่างคำขอที่เซิร์ฟเวอร์ได้รับ = `[2.98, 0.03, 1.28, 1.25, 1.17, 1.23]` — เห็นชัดว่าท่อนที่ 2
ถูกส่งไปเกือบพร้อมท่อนที่ 1 (0.03 วิ) ไม่ต้องรอท่อน 1 ตอบกลับก่อน พิสูจน์ว่า prefetch ทำงานจริง —
ที่เหลือ (~1.2 วิ/gap) คือเวลา generate ล้วนๆ ซึ่งเป็นข้อจำกัดของเครื่อง/engine ไม่ใช่ของ pipeline แล้ว
· barge-in / fallback เบราว์เซอร์ ยังทำงานถูกต้องเหมือนเดิมหลังปรับโครงสร้าง

**ผลคือ:** ดีเลย์ที่เหลือตอนนี้ผูกกับความเร็ว **generate จริงของเครื่อง/engine** เป็นหลัก
(ไม่ใช่ overhead ของ client อีกต่อไป) — ถ้ายังรู้สึกช้า ทางที่เหลือคือเปลี่ยน engine/เครื่องให้
generate เร็วขึ้น (3070 local / GPT-SoVITS / F5-TTS-THAI) ตามที่วางแผนไว้เดิม ไม่ใช่แก้ที่ client อีก

---

## อัปเดต 1 — Phase 2 สตรีมทีละประโยค เสร็จแล้ว (commit `edd8415`, branch `feat/cloned-voice-tts`)

`voice.js` ไม่รอคำตอบ LLM จบทั้งก้อนอีกแล้ว — ตัดข้อความเป็นท่อน (ท่อนแรกตัดไว ~40 ตัวอักษร
ให้เสียงเริ่มไวสุด, ท่อนถัดไปตัดท้ายประโยคหรือทุก 160 ตัวอักษร) ยิง `/tts` ทีละท่อนทันทีที่ตัดได้
แล้วต่อคิวเล่นแบบไม่มีช่องว่าง (gapless) บน `AudioContext` เดียว — ยิงท่อนถัดไปทันทีหลังท่อน
ปัจจุบัน "จัดคิวเล่น" แล้ว ไม่ต้องรอเล่นจบ ทำให้เจนเนอเรตล่วงหน้าทันเวลาเล่นเมื่อ pipeline อุ่นแล้ว
เพิ่ม `ChatRequest.voice` flag → system prompt "ตอบสั้น" ในโหมดเสียงด้วย (เร็วขึ้นทุก engine)

ทดสอบกับ Typhoon จริง + mock TTS server แล้ว: ตัดท่อนถูกต้อง, เล่นต่อเนื่องไม่มีช่องว่าง,
พูดแทรกหยุดทันทีไม่มีเสียงค้าง, fallback `speechSynthesis` ทำงานทั้งกรณีเซิร์ฟเวอร์ต่อไม่ได้และ
เบราว์เซอร์ไม่มีเสียง TTS เลย — ดูรายละเอียดใน commit message

**งานค้างที่เหลือ (เรียงลำดับ):** ติดตั้ง GPT-SoVITS/ทำ Thai frontend (หรือย้ายไป F5-TTS-THAI) →
merge `feat/cloned-voice-tts` → `main`. ดูหัวข้อ "งานค้าง" ด้านล่าง (ข้อ 2-3 เสร็จแล้ว)

**หมายเหตุ:** commit `voice_server.ipynb` (warm-up cell) บน repo `Voice chatbot` ไปด้วย
identity `dd_parnupong@maco.co.th` ที่ git auto-detect จากเครื่องนี้ ไม่ใช่ `myname30275@gmail.com`
ที่ใช้อยู่เดิม (ไม่มี `user.email` ตั้งไว้ใน global config ของเครื่องนี้) — ถ้าอยากให้ตรงกัน ต้องตั้ง
`git config --global user.email` ก่อนคอมมิตรอบต่อไป

---

## สถานะก่อนหน้า (2026-09-08)

**2 repo:**

| repo | GitHub | มีอะไร |
|---|---|---|
| `chatbot-typhoon` (repo นี้) | `Myname30275/chatbot-typhoon` | ตัวแอป · โค้ดฝั่ง client ของโหมดเสียงโคลน |
| `Voice chatbot` (`Clone-voice`) | `Myname30275/Clone-voice` | โมเดล/ไฟล์เสียง Asuna + เซิร์ฟเวอร์ TTS ทุกแบบ |

**Part 2 (ฝั่ง chatbot) — เสร็จ + push แล้ว** · branch `feat/cloned-voice-tts`
- `templates/index.html` แถว `#opt-tts-url` · `static/js/voice.js` (`speakServer()`/`playTts()`/
  `pingTts()`/barge-in/fallback อัตโนมัติ + timeout 60s + Chrome resume) · `static/css/style.css` ·
  `docs/architecture.html` §07
- **client รองรับ TTS server แบบไหนก็ได้** ที่เปิด `POST /tts {text}→WAV` + `GET /health` + CORS
  → ย้าย engine ได้โดยไม่แตะ chatbot อีก
- ทดสอบแล้ว: fallback `speechSynthesis` ทำงาน · mock server ผ่าน Vercel preview ผ่าน ·
  Qwen (Colab) พูดคำตอบจริงได้ แต่ **ดีเลย์เยอะ** (สังเคราะห์ทั้งคำตอบทีเดียว ~15-30s)

**ฝั่ง server (ใน repo `Voice chatbot`) — 3 ทางเลือก:**

| ไฟล์ | engine | สถานะ |
|---|---|---|
| `voice_server.ipynb` | Qwen3-TTS บน Colab/Kaggle/GPU (ฟรี) | ใช้ได้ แต่ช้า · เก็บเป็น fallback |
| `mock_tts_server.py` | คืนไฟล์เสียง Asuna เดิมทุกครั้ง | เครื่องมือดีบั๊ก plumbing เท่านั้น |
| `sovits/` + `GPT_SOVITS_SETUP.md` | **GPT-SoVITS บนเครื่อง (RTX 3070)** — ทางที่เลือก | โครงเสร็จ · รอผู้ใช้ติดตั้ง GPT-SoVITS + **แก้ปัญหา frontend ภาษาไทย** |

**งานค้าง (เรียงลำดับ):**
1. ติดตั้ง GPT-SoVITS v2/v2Pro + ทำ Thai support (community model + patch `text/thai.py`) — ดู `GPT_SOVITS_SETUP.md`
   ถ้าไทยไม่ไหว → ย้ายไป **F5-TTS-THAI** (`VIZINTZOR/F5-TTS-THAI`) · `sovits/sovits_server.py` เปลี่ยนเป็น adapter ของ F5 แทน
2. **Phase 2 — สตรีมทีละประโยค** ใน `voice.js` (ยิง `/tts` ทีละประโยคระหว่าง LLM พิมพ์) — ลดดีเลย์มากสุด ใช้ได้กับทุก engine
3. (ออปชัน) flag `voice:true` → system prompt "ตอบสั้น" ในโหมดเสียง
4. merge `feat/cloned-voice-tts` → `main` เมื่อทดสอบผ่าน

**เครื่องนี้:** มี NVIDIA RTX 3070 (8 GB) แล้ว · git config ทั้ง 2 repo = `Myname30275 <myname30275@gmail.com>`

---

## (ประวัติ) แผน Part 1 + Part 2 ตอนเริ่ม

## เป้าหมาย

ให้โหมดสนทนาด้วยเสียง (ปุ่ม 🎙️) พูดตอบด้วย **เสียง Asuna ที่โคลนไว้** แทน
`speechSynthesis` ของเบราว์เซอร์ โดยยังฟรี และไม่รื้อของเดิม (ถ้าไม่ได้ตั้งค่า
เสียงโคลน ก็ยัง fallback ไป `speechSynthesis` เหมือนเดิม)

## ของที่มีอยู่แล้ว

- โมเดลโคลน: **`Qwen/Qwen3-TTS-12Hz-1.7B-Base`** (ICL mode) — repo `Voice chatbot` / `Clone-voice`
  - reference: `voices/asuna/reference/Asuna_vocals.wav` (Demucs แยกเสียงร้องแล้ว, 20s stereo)
  - ref_text (Whisper large-v3): `voices/_shared_source/ref_transcripts_whisper_large.json`
  - recipe ที่ดีที่สุด (v5) — จาก `Voice_Cloning_Pipeline.ipynb`:
    ```python
    voice_prompt = model.create_voice_clone_prompt(
        ref_audio="Asuna_vocals.wav",
        ref_text=<transcript จาก Whisper large-v3, language="th">,
        x_vector_only_mode=False,
    )
    wavs, sr = model.generate_voice_clone(
        text=<ข้อความ>, language="auto", voice_clone_prompt=voice_prompt,
        max_new_tokens=450, temperature=0.5, top_p=0.8, top_k=30,
    )
    audio = wavs[0] if isinstance(wavs, list) else wavs   # numpy float
    ```
- เครื่องพัฒนา: เดิมไม่มี GPU → ใช้ Colab · **ตอนนี้มี RTX 3070 (8 GB)** → รัน GPT-SoVITS ในเครื่องได้
- Vercel รันโมเดลเองไม่ได้ (ไม่มี GPU, function จำกัด 60 วิ) → เป็นได้แค่ตัวกลาง
  → เบราว์เซอร์เรียก TTS server (Colab tunnel / GPT-SoVITS local + cloudflared) โดยตรง

## แนวทางที่เลือก: Colab/Kaggle T4 ฟรี เป็น "เซิร์ฟเวอร์เสียงเปิดตามต้องการ"

เบราว์เซอร์เรียก TTS จาก tunnel ของ Colab **โดยตรง** — chatbot ฝั่ง Vercel ไม่ต้องแก้ backend

```
Colab (T4 ฟรี)                                 Chatbot (เบราว์เซอร์)
├─ โหลด Qwen3-TTS + สร้าง voice_prompt (asuna)   voice.js:
├─ FastAPI: POST /tts {text} → wav bytes          speak(text) →
│   + CORS: Access-Control-Allow-Origin: *          fetch(ttsUrl + "/tts")
└─ cloudflared → https://xxx.trycloudflare.com      → เล่นเสียง + ป้อน AnalyserNode
```

เหตุผลที่เรียกตรงไม่ผ่าน Vercel: URL ของ Colab เปลี่ยนทุกครั้งที่รีสตาร์ท ถ้าเก็บใน
env ของ Vercel ต้อง redeploy ทุกครั้ง — เก็บใน `localStorage` แล้ววางเอาเองสะดวกกว่า

---

## Part 1 — Colab notebook: `voice_server.ipynb` (ไฟล์ใหม่ ใน repo Clone-voice)

เซลล์ตามลำดับ:

1. **ติดตั้ง deps** — เหมือน `Voice_Cloning_Pipeline.ipynb` Cell 0
   (`torch ... cu128`, `transformers==4.57.3 qwen-tts soundfile accelerate`,
   `fastapi uvicorn nest-asyncio` + ดาวน์โหลด `cloudflared`)
2. **โหลดโมเดล + สร้าง voice_prompt ครั้งเดียว**
   - อัปโหลด `Asuna_vocals.wav` เข้า Colab (หรือ mount Drive / โหลดจาก HF dataset ส่วนตัว)
   - **precompute `ref_text`**: รัน Whisper large-v3 ครั้งเดียว แล้ว **hardcode สตริงที่ได้**
     ลงในเซลล์ → รอบต่อไปไม่ต้องโหลด Whisper (ประหยัด ~3GB VRAM + เวลาสตาร์ท)
   - `voice_prompt = model.create_voice_clone_prompt(ref_audio, ref_text, x_vector_only_mode=False)`
3. **เซิร์ฟเวอร์ FastAPI**
   - `POST /tts` body `{"text": "...", "max_new_tokens"?: int}` →
     `generate_voice_clone(text, language="auto", voice_clone_prompt, max_new_tokens=450,
     temperature=0.5, top_p=0.8, top_k=30)` → `soundfile.write` เป็น WAV ใน memory → คืน `audio/wav`
   - normalize `audio / max(abs(audio))` ก่อนส่ง (เหมือน `save_clone()`)
   - `GET /health` → `{"ok": true}` (ให้ chatbot เช็คว่าเซิร์ฟเวอร์พร้อม)
   - **CORS**: `CORSMiddleware(allow_origins=["*"], allow_methods=["*"])`
   - จำกัดความยาว: ตัด `text` ที่ ~600 ตัวอักษร (คำตอบยาวๆ ให้แบ่งประโยคฝั่ง client — ดู Phase 2)
   - รันด้วย `nest_asyncio` + `uvicorn` ใน thread (Colab)
4. **เปิด tunnel** — `cloudflared tunnel --url http://localhost:8000` → print URL `https://xxx.trycloudflare.com`
   (ไม่ต้องสมัคร Cloudflare; ทางเลือก: `pyngrok` ถ้ามี authtoken)
5. **เซลล์ทดสอบ** — `requests.post(url+"/tts", json={"text":"สวัสดีค่ะ วันนี้อากาศเป็นยังไงบ้างคะ"})`
   → เล่นใน notebook ฟังว่าเสียงไทยระดับสนทนาโอเคไหม

**เวลาสตาร์ท:** ~3-5 นาที (โหลดโมเดล) · **ต่อคำตอบ:** ~2-5 วิ บน T4

---

## Part 2 — chatbot: `static/js/voice.js` + Settings

### 2.1 Settings — ช่องใส่ URL

`templates/index.html` เพิ่มแถวในแผงตั้งค่า (ใต้ `#opt-voice`):
```html
<div class="settings__row">
  <label for="opt-tts-url">URL เซิร์ฟเวอร์เสียงโคลน (Colab)</label>
  <input id="opt-tts-url" type="url" placeholder="https://xxxx.trycloudflare.com" />
  <small id="opt-tts-note">ว่าง = ใช้เสียงของเบราว์เซอร์ · วาง URL จาก notebook เพื่อใช้เสียง Asuna</small>
</div>
```
`voice.js` อ่าน/เขียน `localStorage["ts.ttsUrl"]` + แสดงสถานะ (ping `GET /health` ตอนเปิด
โหมดเสียง → ถ้าไม่ตอบ แสดง "เชื่อมเซิร์ฟเวอร์เสียงไม่ได้ ใช้เสียงเบราว์เซอร์แทน")

### 2.2 `speak(text)` — สลับ provider

ปัจจุบัน: `synth.cancel()` + `SpeechSynthesisUtterance` + `onboundary` bump + `onend → startListening()`

ใหม่:
```
const url = ls.get("ts.ttsUrl", "").trim();
if (url && state !== "off") {
  try {
    setState("speaking");
    const res = await fetch(url.replace(/\/$/,"") + "/tts", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ text }), signal: <barge-in AbortController>,
    });
    if (!res.ok) throw ...;
    const buf = await res.arrayBuffer();
    await playPcm(buf);        // AudioBufferSourceNode → ผ่าน AnalyserNode → ต่อ destination
    if (state === "speaking") startListening();
    return;
  } catch (e) {
    if (aborted) return;
    console.warn("[voice] tts server failed, fallback:", e);
    // ตกลงมาใช้ speechSynthesis ด้านล่าง
  }
}
// ... โค้ด speechSynthesis เดิม เป็น fallback
```

### 2.3 อินเทอร์เฟซเซลล์ประสาทตอนพูด — ใช้คลื่นจริง

- สร้าง `AnalyserNode` ต่อกับ `AudioBufferSourceNode` ของเสียง TTS
- ระหว่างเล่น: อ่าน RMS ป้อน `targetLevel` แทน `u.onboundary` แบบสุ่ม
  → พัลส์/ระลอกขยับตรงกับเสียงพูดจริง (ดีกว่าที่เป็นอยู่)
- ใช้ `audioCtx` ตัวเดียวกับ mic meter ได้ (สร้างไว้แล้วใน `startMeter()`)

### 2.4 barge-in

- pointerdown ตอน `speaking` ตอนนี้เรียก `synth.cancel()` — เพิ่ม: `ttsSource?.stop()` +
  `ttsAbort?.abort()` แล้ว `startListening()`
- ตอน close(): stop เสียง TTS ที่เล่นอยู่ด้วย

### 2.5 (ไม่ทำตอนนี้) proxy ผ่าน Vercel

ถ้าภายหลังเปลี่ยนไป **HF Space ZeroGPU** (URL คงที่) ค่อยเพิ่ม:
`config.py` `TTS_BASE_URL`/`TTS_API_KEY`, `services/tts.py` `synthesize(text)->bytes`,
`POST /api/v1/tts`, `/config` เพิ่ม `tts` bool. ตอนนั้น `voice.js` เลือก:
`ts.ttsUrl` (ส่วนตัว) > `/api/v1/tts` (ถ้า config เปิด) > `speechSynthesis`

---

## Phase 2 (หลัง MVP ใช้ได้) — ลดดีเลย์

- สตรีม TTS ทีละประโยค: ตัดคำตอบ LLM ด้วย `. ? ! ๆ \n` → ยิง `/tts` ทีละก้อน →
  ต่อคิวเล่น `AudioBufferSourceNode` แบบไม่มีช่องว่าง
- เริ่มยิงประโยคแรกทันทีที่ LLM พิมพ์จบประโยคแรก (ไม่รอทั้งคำตอบ)
- เป้าหมาย: เสียงเริ่มออกภายใน ~2 วิ หลัง LLM เริ่มตอบ

---

## ข้อควรระวัง / เช็คก่อน

1. **คุณภาพไทยระดับสนทนา** — Qwen3-TTS-1.7B ทดสอบกับข้อความไทยใน notebook แล้ว (v5 = best)
   แต่ยังไม่เคยลองประโยคสนทนาสั้นๆ หลากหลาย → เซลล์ทดสอบใน Part 1 ต้องฟังจริงก่อน
2. **Colab ฟรี** — หลุดหลัง ~90 นาทีไม่ใช้งาน / สูงสุด ~12 ชม. / ใช้หนักหลายวันโดน cooldown GPU ~1 วัน
3. **URL เปลี่ยนทุกรีสตาร์ท** — ต้องวางใหม่ใน Settings ทุกเซสชัน (ยอมรับได้สำหรับใช้ส่วนตัว)
4. **workflow**: เปิด Colab → รอโหลด ~5 นาที → ก๊อป URL → คุย → ปิดเมื่อเลิก
5. **ดีเลย์รวมต่อรอบเสียง** ~6-12 วิ ก่อนทำ Phase 2
6. **`text` ยาว** — cap ที่ ~600 ตัวอักษร/คำขอ กัน generate นาน/หลุด (Phase 2 แก้ด้วยการแบ่งประโยค)
7. Kaggle เป็นทางเลือกที่เสถียรกว่า (session 9 ชม., 30 ชม./สัปดาห์) — โค้ดเซิร์ฟเวอร์เดียวกัน

## Checklist ตอนทำจริง

- [x] `voice_server.ipynb` ใน repo Clone-voice — โหลดโมเดล + prompt + FastAPI + cloudflared + เซลล์ทดสอบ
- [x] hardcode `ref_text` ของ Asuna (จาก `voices/_shared_source/ref_transcripts_whisper_large.json` — ไม่ต้องโหลด Whisper)
- [x] `templates/index.html` — แถว `#opt-tts-url` ในแผงตั้งค่า
- [x] `static/js/voice.js` — `speak()` สลับ provider (`speakServer`/`speakBrowser`), `playTts()` + `AnalyserNode`, health ping (`pingTts`), barge-in อัปเดต, fallback อัตโนมัติ
- [x] `static/css/style.css` — style `input[type="url"]` + note สถานะ `.is-ok`/`.is-bad`
- [ ] ทดสอบในเบราว์เซอร์จริง: ไม่ใส่ URL → `speechSynthesis` เหมือนเดิม · ใส่ URL ที่ใช้ไม่ได้ → fallback + แจ้งเตือน · ใส่ URL ที่ใช้ได้ → เสียง Asuna + neural viz ขยับตามเสียงจริง · barge-in ตัดเสียงได้ **(ยังไม่ได้ทำ — ต้องเปิด notebook + เบราว์เซอร์)**
- [x] อัปเดต `docs/architecture.html` หัวข้อ 07 (โหมดเสียง) ให้พูดถึง TTS server ที่ตั้งค่าได้
- [x] smoke test: หน้าเว็บ + voice.js + style.css เสิร์ฟผ่าน `TestClient` OK (ไม่มี backend เปลี่ยน)

## นอกขอบเขต (ยังไม่ทำ)

- Vercel proxy / `services/tts.py` (ทำเมื่อย้ายไป ZeroGPU)
- โคลนเสียงเพิ่ม / เลือกหลายเสียงใน UI (ตอนนี้เสียงเดียว = Asuna)
- ทำให้เซิร์ฟเวอร์เสียง always-on แบบฟรีจริง (ไม่มีทางที่ไม่มีข้อแลก — ดู "ข้อควรระวัง")

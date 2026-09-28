import logging
from pathlib import Path

# ให้ httpx ตรวจใบรับรอง TLS ผ่าน cert store ของระบบปฏิบัติการ แทน bundle ของ certifi
# จำเป็นในเครือข่ายองค์กรที่มี proxy คั่น TLS (certifi จะไม่รู้จัก CA ขององค์กร ทำให้
# ต่อ https ไม่ได้) — ครอบ try ไว้เผื่อรันในที่ที่ไม่มี/ไม่ต้องใช้
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from channels.tts import router as tts_router
from channels.web_chat import router as chat_router

# หาโฟลเดอร์ static/templates จาก path ของไฟล์นี้เอง แทนที่จะพึ่ง current working
# directory ตอนรัน เพราะบน serverless (เช่น Vercel) ไม่การันตีว่า process จะเริ่ม
# ทำงานจาก root ของโปรเจกต์เสมอไป
BASE_DIR = Path(__file__).resolve().parent

# ตั้ง logging กลางไว้ตั้งแต่จุดเริ่มโปรแกรม เพื่อให้ log จากทุกโมดูล (routers, services)
# ออกมาในฟอร์แมตเดียวกันหมด แทนที่จะต้องตั้งซ้ำในแต่ละไฟล์
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = FastAPI(
    title="AI Chatbot",
    description="Chatbot ที่คุยกับโมเดล AI ผ่าน OpenAI-compatible Chat Completions API",
    version="0.1.0",
)

# หน้าเว็บที่แถมมาเป็น same-origin จึงไม่ต้องเปิด CORS เลยโดยปกติ เปิดเฉพาะเมื่อ
# ตั้ง ALLOWED_ORIGINS ใน .env (เช่น มี frontend แยกโดเมน) — และตอนนั้นถึงจะอนุญาต
# credentials ได้ เพราะ allow_origins=["*"] คู่กับ allow_credentials=True นั้นผิดสเปก
# (เบราว์เซอร์จะปฏิเสธ)
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# เสิร์ฟไฟล์หน้าบ้าน (css/js) และ template ของหน้าแชทแบบ server-rendered เพียงหน้าเดียว
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(chat_router)
app.include_router(tts_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"model_name": settings.LLM_MODEL}
    )


@app.get("/health")
async def health():
    # ใช้เช็คว่าเซิร์ฟเวอร์ยังรันอยู่เฉยๆ (ไม่ได้เช็คว่าคุยกับผู้ให้บริการ AI ได้ไหม)
    return {"status": "ok"}

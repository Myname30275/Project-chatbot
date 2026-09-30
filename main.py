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
from channels import admin
from channels.booking_api import router as booking_router
from channels.web_chat import router as chat_router
from shop.pricing import load_catalog

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
    title="Hom Hom Grooming",
    description="น้องหอม ผู้ช่วยตอบแชทของร้านอาบน้ำ-ตัดขนสุนัขและแมว",
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


def _asset_version() -> str:
    """เลขเวอร์ชันของ css/js (เวลาแก้ไฟล์ล่าสุด) ต่อท้าย URL เป็น ?v=... — แก้ไฟล์เมื่อไหร่
    เบราว์เซอร์จะโหลดไฟล์ใหม่ทันที ไม่ค้างเวอร์ชันเก่าจาก cache"""
    files = [f for d in ("css", "js") for f in (BASE_DIR / "static" / d).glob("*") if f.is_file()]
    return str(int(max((f.stat().st_mtime for f in files), default=0)))


templates.env.globals["asset_v"] = _asset_version

app.include_router(chat_router)
app.include_router(tts_router)
app.include_router(booking_router)
app.include_router(admin.router)


@app.get("/")
async def index(request: Request):
    # ราคาบนหน้าเว็บดึงจาก catalog.json ไฟล์เดียวกับที่บอทใช้ — ตัวเลขจึงตรงกันเสมอ
    return templates.TemplateResponse(request, "index.html", {"catalog": load_catalog()})


@app.get("/admin")
async def admin_page(request: Request):
    # หลังบ้านเจ้าของร้าน: ยังไม่ login = ฟอร์มรหัสผ่าน · login แล้ว = ตารางคิว (ข้อมูลโหลดผ่าน /api/v1/admin/*)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "catalog": load_catalog(),
            "enabled": admin.enabled(),
            "logged_in": admin.is_admin(request),
            "error": request.query_params.get("e"),
        },
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
    )


@app.get("/avatar")
async def avatar(request: Request):
    # โหมดเสียง: อวตารพนักงานร้าน คุยผ่าน /api/v1/chat/stream เดิม (session เดียวกับหน้าแชท)
    return templates.TemplateResponse(request, "avatar.html", {"catalog": load_catalog()})


@app.get("/health")
async def health():
    # ใช้เช็คว่าเซิร์ฟเวอร์ยังรันอยู่เฉยๆ (ไม่ได้เช็คว่าคุยกับผู้ให้บริการ AI ได้ไหม)
    return {"status": "ok"}

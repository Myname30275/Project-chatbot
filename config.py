from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ค่าตั้งค่าทั้งหมดของแอปอ่านจากไฟล์ .env (ผ่าน pydantic-settings)
    ตัวแปรฝั่ง LLM ตั้งชื่อแบบกลางๆ ไม่ผูกกับผู้ให้บริการรายใดรายหนึ่ง เพราะโค้ดฝั่ง
    chatbot/llm_client.py คุยด้วยฟอร์แมต OpenAI-compatible Chat Completions ซึ่ง
    Typhoon (opentyphoon.ai), LM Studio (รันในเครื่อง) และ OpenRouter รองรับเหมือนกัน
    — ตอนจะสลับผู้ให้บริการจึงแค่แก้ค่าใน .env โดยไม่ต้องแตะโค้ดเลย
    """

    # ต้องรวม path เวอร์ชันไว้ในค่านี้ด้วย (เช่น https://api.opentyphoon.ai/v1 หรือ
    # http://127.0.0.1:1234/v1) เพราะโค้ดจะต่อ "/chat/completions" และ "/models"
    # เข้าไปเองตรงๆ ไม่มีการเดา path ให้
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str
    CARTESIA_API_KEY: str = ""
    CARTESIA_MODEL: str = "sonic-3.6"
    CARTESIA_VOICE_ID: str = "ccc7bb22-dcd0-42e4-822e-0731b950972f"

    # system prompt ไม่ได้ตั้งผ่าน env แล้ว — อยู่ที่ prompts/chat_system.txt + ข้อมูลร้านใน shop/
    # (ดู chatbot/prompt_builder.py) ค่า SYSTEM_PROMPT ใน .env เก่าจะถูกเมินไป (extra="ignore")

    # ปุ่มปรับพฤติกรรมโมเดล — ไม่ตั้งก็ได้ (ปล่อยให้ผู้ให้บริการใช้ค่า default ของตัวเอง)
    # ใส่ลง payload เฉพาะเมื่อมีค่า (ดู chatbot/llm_client.py::_build_payload)
    LLM_TEMPERATURE: float | None = None
    LLM_MAX_TOKENS: int | None = None

    # อายุของประวัติบทสนทนาใน store ภายนอก (วินาที) ตั้งให้เท่าอายุ cookie = 7 วัน
    CONVERSATION_TTL_SECONDS: int = 60 * 60 * 24 * 7

    # --- อ่านเอกสาร/รูปภาพที่ผู้ใช้แนบมา (vision/documents.py) ---
    # OCR ใช้ผู้ให้บริการเดียวกับแชต (Typhoon) — โมเดล typhoon-ocr เรียกผ่าน
    # LLM_BASE_URL + LLM_API_KEY เดิม ไม่ต้องตั้ง key เพิ่ม
    OCR_MODEL: str = "typhoon-ocr"

    # โมเดล "เข้าใจภาพ" (บรรยายรูปถ่าย/กราฟ/ไดอะแกรม) — แยกผู้ให้บริการเพราะ Typhoon
    # ยังไม่มีโมเดลมองภาพ ค่าเริ่มต้นเล็งไว้ที่ Gemini free tier (OpenAI-compatible)
    # ไม่ตั้ง VISION_API_KEY = ปิดฟีเจอร์นี้ (รูปจะอ่านได้แค่ "ข้อความในรูป" จาก OCR)
    VISION_BASE_URL: str | None = None
    VISION_API_KEY: str | None = None
    # gemini-flash-latest = alias ที่ Google ชี้ไปโมเดล flash ตัวล่าสุดเสมอ
    # (ตั้งชื่อเวอร์ชันตายตัวเช่น gemini-2.5-flash จะโดน 404 เมื่อ Google เลิกให้ผู้ใช้ใหม่)
    VISION_MODEL: str = "gemini-flash-latest"

    # --- RAG: ค้นคืนข้อมูลร้านจาก shop/ (rag/) ---
    # embedding ผ่าน endpoint OpenAI-compatible — ไม่ตั้ง EMBED_BASE_URL/EMBED_API_KEY จะใช้ค่า
    # VISION_* (Gemini) แทน · ไม่มีทั้งคู่ = ค้นแบบ lexical (TF-IDF) อย่างเดียว ระบบยังทำงานได้
    EMBED_BASE_URL: str | None = None
    EMBED_API_KEY: str | None = None
    EMBED_MODEL: str = "gemini-embedding-001"
    EMBED_DIMENSIONS: int = 768
    RAG_TOP_K: int = 4  # จำนวนชิ้นความรู้ที่แนบให้ LLM ต่อ 1 คำถาม

    ATTACHMENT_MAX_BYTES: int = 8 * 1024 * 1024        # 8 MB ต่อไฟล์
    ATTACHMENT_MAX_PDF_PAGES: int = 12                 # หน้าเกินนี้ไม่อ่าน
    ATTACHMENT_CONTEXT_CHAR_LIMIT: int = 80_000        # รวมทุกไฟล์ต่อ session ตัดส่วนเกิน

    # --- ค้นเว็บอัตโนมัติ (chatbot/search.py) ---
    # เวลาผู้ใช้ถามข้อมูลล่าสุด (ข่าว/ราคา/เหตุการณ์ปัจจุบัน) โมเดลจะสั่งให้ไปค้นเว็บ
    # มาก่อนตอบ — ขอ key ฟรีที่ tavily.com (ไม่ตั้ง SEARCH_API_KEY = ปิดฟีเจอร์นี้)
    # ปิดเป็นค่าเริ่มต้น: บอทร้านต้องตอบจากข้อมูลร้านเท่านั้น ข้อมูลจากเว็บเสี่ยงขัดกับราคา/นโยบายจริง
    WEB_SEARCH_ENABLED: bool = False
    SEARCH_API_KEY: str | None = None
    SEARCH_MAX_RESULTS: int = 5
    SEARCH_TIMEOUT: float = 12.0

    # ที่เก็บประวัติบทสนทนาข้าม instance (จำเป็นบน Vercel serverless) — รับได้ทั้งชื่อ
    # env ที่ Vercel KV ฉีดให้ (KV_REST_API_*) และชื่อจาก Upstash integration รุ่นใหม่
    # (UPSTASH_REDIS_REST_*) ถ้าไม่ตั้งเลย จะ fallback ไปเก็บในหน่วยความจำ process
    KV_REST_API_URL: str | None = None
    KV_REST_API_TOKEN: str | None = None
    UPSTASH_REDIS_REST_URL: str | None = None
    UPSTASH_REDIS_REST_TOKEN: str | None = None

    # โดเมนของ frontend ที่อยู่คนละที่กับ backend (คั่นด้วย ,) — ว่าง = ไม่เปิด CORS
    # ข้ามโดเมน เพราะหน้าเว็บที่แถมมาเป็น same-origin อยู่แล้ว
    ALLOWED_ORIGINS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def redis_rest_url(self) -> str | None:
        return self.KV_REST_API_URL or self.UPSTASH_REDIS_REST_URL

    @property
    def redis_rest_token(self) -> str | None:
        return self.KV_REST_API_TOKEN or self.UPSTASH_REDIS_REST_TOKEN

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def vision_enabled(self) -> bool:
        return bool(self.VISION_BASE_URL and self.VISION_API_KEY)

    @property
    def embed_base_url(self) -> str | None:
        return self.EMBED_BASE_URL or self.VISION_BASE_URL

    @property
    def embed_api_key(self) -> str | None:
        return self.EMBED_API_KEY or self.VISION_API_KEY

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.embed_base_url and self.embed_api_key)

    @property
    def search_enabled(self) -> bool:
        return bool(self.WEB_SEARCH_ENABLED and self.SEARCH_API_KEY)


settings = Settings()

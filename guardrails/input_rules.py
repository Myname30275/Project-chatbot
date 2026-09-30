"""ด่านที่ 1 (ขาเข้า): กฎในโค้ด — ฟรี เร็ว ผลแน่นอน ไม่เรียก API

ตรวจตามลำดับ (ถูกสุด/แน่นอนสุดก่อน):
1. ความยาวข้อความ           → TOO_LONG     (OWASP LLM06 Unbounded Consumption)
2. ความถี่ต่อ session         → RATE_LIMIT   (LLM06)
3. คำต้องห้ามใน blocklist.txt → BLOCKLIST
4. รูปแบบ prompt injection   → INJECTION    (LLM01 Prompt Injection)

ข้อจำกัด (ตอบ Q&A): กฎไม่เข้าใจความหมาย เลี่ยงได้ด้วยการสะกดผิด/เว้นวรรค จึงมีด่าน LLM-judge
และด่านตรวจขาออกต่อท้าย · rate limit นับในหน่วยความจำของแต่ละ instance บน serverless จึงกันได้
แค่ระดับหนึ่ง ถ้าต้องเข้มงวดจริงให้ย้ายไปนับใน Redis
"""

import logging
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

BLOCKLIST_PATH = Path(__file__).resolve().parent / "blocklist.txt"

# รูปแบบที่พบบ่อยของการสั่งให้บอทลืมกฎ/เปลี่ยนบทบาท/เปิดเผยคำสั่งระบบ
# ระวัง false positive: "สมมติว่าน้องหนัก 12 กิโล" ต้องไม่โดน จึงบังคับให้มีสรรพนามถึงบอท
_INJECTION_PATTERNS = [
    r"ลืม\s*(คำสั่ง|กฎ|ทุกอย่าง|ที่(เคย)?บอก|บทบาท)",
    r"(ไม่ต้อง|เลิก|ห้าม)\s*(สนใจ|ทำตาม|ยึด)\s*(คำสั่ง|กฎ)",
    # ไม่ใส่ "ยกเลิกคำสั่ง" เพราะลูกค้าพูดจริงว่า "ขอยกเลิกคำสั่งจอง" (false positive)
    r"(เพิกเฉย|ข้าม)\s*(ต่อ)?\s*(คำสั่ง|กฎ)",
    r"(คำสั่ง|ข้อความ)\s*(ระบบ|ตั้งต้น)|system\s*prompt|initial\s*prompt",
    r"(ตอนนี้|จากนี้(ไป)?)\s*(คุณ|เธอ|แก|นาย|บอท)\s*(คือ|เป็น|จะเป็น)",
    r"(สมมติ|แกล้งทำ|แสร้ง)\s*(ว่า)?\s*(คุณ|เธอ|แก|บอท)\s*(เป็น|คือ)",
    r"(คุณ|เธอ|บอท)\s*(ได้รับ)?\s*(สิทธิ์|อนุญาต)\s*(พิเศษ|แอดมิน|ผู้ดูแล)",
    r"(ในฐานะ|ฉันคือ|ผมคือ)\s*(แอดมิน|เจ้าของร้าน|ผู้ดูแลระบบ|developer|นักพัฒนา)",
    r"ignore\s+(all\s+|the\s+|your\s+)?(previous|above|prior|earlier)\s+(instructions|rules|prompts?)",
    r"disregard\s+.{0,20}(instructions|rules)",
    r"you\s+are\s+now|act\s+as\s+(a|an|the)\b|pretend\s+(to\s+be|you\s+are)",
    r"jailbreak|\bDAN\b|developer\s+mode|reveal\s+.{0,20}(prompt|instructions)",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


class Blocklist:
    """อ่านคำต้องห้ามจากไฟล์ รีโหลดเองเมื่อไฟล์ถูกแก้ (ดัดแปลงจาก llama-guard-layer ของ Week 11)"""

    def __init__(self, path: Path):
        self.path = path
        self._mtime: float | None = None
        self._terms: list[str] = []

    def _reload_if_changed(self) -> None:
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            self._mtime, self._terms = None, []
            return
        if mtime == self._mtime:
            return
        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        self._terms = [
            ln.strip().casefold() for ln in lines if ln.strip() and not ln.strip().startswith("#")
        ]
        self._mtime = mtime

    def matches(self, message: str) -> bool:
        self._reload_if_changed()
        # ตัดช่องว่างทิ้งก่อนเทียบ กันเลี่ยงด้วยการเว้นวรรคกลางคำ เช่น "เ หี้ ย"
        text = re.sub(r"\s+", "", message.casefold())
        return any(term in text for term in self._terms)


class RateLimiter:
    """นับข้อความต่อ session ในหน้าต่างเวลา 60 วินาที (sliding window)"""

    def __init__(self, limit: int | None = None) -> None:
        # ไม่ระบุ = ใช้เพดานของแชท (GUARD_RATE_LIMIT_PER_MINUTE) · ระบบจองใช้เพดานของตัวเอง
        self._limit = limit
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, session_id: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits[session_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= (self._limit or settings.GUARD_RATE_LIMIT_PER_MINUTE):
            return False
        q.append(now)
        return True


blocklist = Blocklist(BLOCKLIST_PATH)
rate_limiter = RateLimiter()


def check(message: str, session_id: str) -> str | None:
    """คืนรหัสหมวดที่ไม่ผ่าน หรือ None ถ้าผ่านทุกกฎ"""
    if len(message) > settings.GUARD_MAX_INPUT_CHARS:
        return "TOO_LONG"
    if not rate_limiter.allow(session_id):
        return "RATE_LIMIT"
    if blocklist.matches(message):
        return "BLOCKLIST"
    if _INJECTION_RE.search(message):
        return "INJECTION"
    return None

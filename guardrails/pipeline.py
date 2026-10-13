"""รวมด่านตรวจทั้งหมดไว้ที่เดียว — ช่องทางต่าง ๆ (เว็บ, โหมดเสียง, LINE) เรียกผ่านโมดูลนี้

    ขาเข้า:  input_rules (กฎในโค้ด) → judge (LLM จำแนกเจตนา)
    ขาออก:  output_guard (ราคา/ส่วนลด/ข้อมูลส่วนตัว ตรวจทีละประโยค)

ทุกครั้งที่บล็อกจะ log แค่รหัสหมวด + ความยาวข้อความ ไม่ log เนื้อหา (อาจมีข้อมูลส่วนตัว — PDPA)
เพื่อใช้ติดตามอัตราการบล็อกและหา false positive ตามงานด้านปฏิบัติการของ Week 11
"""

import logging
from dataclasses import dataclass

from chatbot import prompt_builder
from config import settings
from guardrails import input_rules, judge
from guardrails.categories import CATEGORIES
from guardrails.output_guard import OutputGuard
from shop import pricing

logger = logging.getLogger(__name__)

__all__ = ["Decision", "check_rules", "check_judge", "OutputGuard", "output_fallback"]


@dataclass
class Decision:
    allowed: bool
    code: str | None = None      # รหัสหมวดที่ไม่ผ่าน เช่น INJECTION
    layer: str | None = None     # rules | judge
    reason: str = ""

    @property
    def message(self) -> str:
        """ข้อความปฏิเสธที่ส่งให้ลูกค้า"""
        return CATEGORIES[self.code].message if self.code else ""


ALLOW = Decision(True)


def _blocked(code: str, layer: str, session_id: str, message: str, reason: str = "") -> Decision:
    logger.info("guard BLOCK layer=%s code=%s session=%s len=%d", layer, code, session_id, len(message))
    return Decision(False, code, layer, reason)


def check_rules(message: str, session_id: str) -> Decision:
    code = input_rules.check(message, session_id)
    return _blocked(code, "rules", session_id, message) if code else ALLOW


async def check_judge(message: str, session_id: str) -> Decision:
    if not settings.GUARD_JUDGE_ENABLED:
        return ALLOW
    verdict = await judge.classify(message)
    if verdict is None:
        if settings.GUARD_JUDGE_FAIL_CLOSED:
            return _blocked("JUDGE_DOWN", "judge", session_id, message)
        return ALLOW  # fail-open โดยตั้งใจ: กฎในโค้ด + ตรวจขาออกยังคุมอยู่ (ดู config.py)
    if verdict.safe:
        return ALLOW
    if verdict.category == "OFF_TOPIC" and pricing.mentions_offer(message):
        # ตัวตรวจเป็น LLM จึงพลาดได้: ข้อความพูดถึงบริการ/สินค้าที่มีใน catalog ของร้าน ไม่ถือว่านอกเรื่อง
        # (ยกเว้นให้เฉพาะ OFF_TOPIC — INJECTION / PRIVACY / HARMFUL ยังบล็อกตามเดิม · LLM ตอบมี prompt + ด่าน 3 คุมต่อ)
        logger.info("guard judge OFF_TOPIC overridden (shop offer mentioned) session=%s len=%d", session_id, len(message))
        return ALLOW
    return _blocked(verdict.category, "judge", session_id, message, verdict.reason)


def output_fallback(reason: str | None, session_id: str) -> str:
    logger.info("guard BLOCK layer=output code=%s session=%s", reason, session_id)
    return prompt_builder.fallback_message()

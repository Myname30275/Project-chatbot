"""รูปสลิปโอนเงิน → ตรวจเบื้องต้นกับค่ามัดจำของร้าน

ตรวจแค่ "ยอดตรงไหม / โอนให้ร้านหรือเปล่า" จากข้อมูลที่อ่านได้ **บอทไม่ยืนยันการชำระเงินเอง**
(สลิปปลอมทำได้ง่าย — ต้องให้แอดมินตรวจยอดเข้าบัญชีจริงเสมอ ตามข้อห้ามของร้าน)
"""

import re

from shop import pricing
from vision.image_analyzer import Slip


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s.lower())


def _receiver_matches(name: str | None) -> bool | None:
    """True/False = ชื่อผู้รับตรง/ไม่ตรงกับร้าน, None = อ่านชื่อไม่ได้"""
    if not name:
        return None
    shop = pricing.load_catalog()["shop"]
    candidates = {_norm(shop["name"]), _norm(shop["name_en"]), _norm("หอมหอม")}
    got = _norm(name)
    return any(c and c in got for c in candidates)


def slip_text(slip: Slip) -> str:
    deposit = pricing.load_catalog()["payment"]["deposit"]
    lines = ["ผลตรวจรูปสลิปที่ลูกค้าส่งมา (ตรวจเบื้องต้นด้วยระบบ):"]
    problems: list[str] = []  # เรื่องที่ "ต้อง" แจ้งลูกค้า — ทดสอบจริงแล้วโมเดลข้ามไปถ้าไม่เน้น

    if slip.amount is None:
        problems.append("อ่านยอดเงินในสลิปไม่ได้ รบกวนส่งรูปสลิปที่ชัดขึ้น")
    elif slip.amount == deposit:
        lines.append(f"- ยอดโอน {slip.amount:,.0f} บาท ตรงกับค่ามัดจำการจองคิว")
    else:
        problems.append(
            f"ยอดโอนในสลิปคือ {slip.amount:,.0f} บาท ไม่ตรงกับค่ามัดจำการจองคิว {deposit} บาท"
        )

    match = _receiver_matches(slip.receiver_name)
    if match is True:
        lines.append("- ชื่อผู้รับเงินตรงกับบัญชีของร้าน")
    elif match is False:
        problems.append(
            f"ชื่อผู้รับเงินในสลิป ({slip.receiver_name}) ไม่ใช่บัญชีของร้าน รบกวนตรวจสอบว่าโอนถูกบัญชีหรือไม่"
        )
    else:
        lines.append("- อ่านชื่อผู้รับเงินไม่ได้")

    if problems:
        lines.append("⚠️ พบจุดที่ไม่ตรง — ต้องแจ้งลูกค้าทุกข้อในคำตอบ:")
        lines += [f"  - {p}" for p in problems]

    when = " ".join(x for x in (slip.date, slip.time) if x)
    if when:
        lines.append(f"- วันเวลาที่โอน: {when}")
    if slip.reference:
        lines.append(f"- เลขอ้างอิง: {slip.reference}")
    lines.append(
        "สิ่งที่ต้องบอกลูกค้าเสมอ: ได้รับรูปสลิปแล้ว แอดมินจะตรวจยอดเข้าบัญชีจริงและยืนยันคิวให้อีกครั้ง "
        "(ห้ามบอกว่าชำระเงินสำเร็จหรือจองคิวสำเร็จแล้ว)"
    )
    return "\n".join(lines)


def customer_reply(slip: Slip) -> str:
    """ข้อความตอบลูกค้าทันทีที่ส่งสลิป — สร้างด้วยโค้ด ไม่ยืนยันการชำระเงินเองเด็ดขาด"""
    deposit = pricing.load_catalog()["payment"]["deposit"]
    problems = []
    if slip.amount is None:
        problems.append("อ่านยอดเงินในสลิปไม่ได้ รบกวนส่งรูปสลิปที่ชัดขึ้นนะคะ")
    elif slip.amount != deposit:
        problems.append(f"ยอดโอนในสลิปคือ {slip.amount:,.0f} บาท แต่ค่ามัดจำการจองคิวคือ {deposit} บาทค่ะ")
    if _receiver_matches(slip.receiver_name) is False:
        problems.append(f"ชื่อผู้รับเงินในสลิป ({slip.receiver_name}) ไม่ใช่บัญชีของร้าน รบกวนตรวจสอบว่าโอนถูกบัญชีไหมคะ")

    if problems:
        return "ได้รับรูปสลิปแล้วค่ะ แต่พบจุดที่ต้องตรวจสอบ:\n" + "\n".join(f"- {p}" for p in problems) + (
            "\n\nแอดมินจะช่วยตรวจสอบและติดต่อกลับอีกครั้งนะคะ"
        )
    return (
        f"ได้รับรูปสลิปมัดจำ {deposit} บาทแล้วค่ะ "
        "แอดมินจะตรวจยอดเข้าบัญชีและยืนยันคิวให้อีกครั้งนะคะ"
    )

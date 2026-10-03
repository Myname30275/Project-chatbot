"""รูปสลิปโอนเงิน → ตรวจเบื้องต้นกับค่ามัดจำของร้าน

ตรวจแค่ "ยอดตรงไหม / โอนให้ร้านหรือเปล่า" จากข้อมูลที่อ่านได้ **บอทไม่ยืนยันการชำระเงินเอง**
(สลิปปลอมทำได้ง่าย — ต้องให้แอดมินตรวจยอดเข้าบัญชีจริงเสมอ ตามข้อห้ามของร้าน)
"""

import re

from shop import pricing
from vision.image_analyzer import Slip


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s.lower())


# คำนำหน้าชื่อที่สลิปแต่ละธนาคารใส่มา (ยาวก่อน เพื่อให้ "นางสาว" ไม่ถูกตัดเหลือ "สาว")
_TITLES = sorted(
    ["นางสาว", "น.ส.", "นาง", "นาย", "ด.ช.", "ด.ญ.", "mrs.", "mrs", "miss", "ms.", "ms", "mr.", "mr"],
    key=len,
    reverse=True,
)
_THAI = re.compile(r"[฀-๿]")
_MASK_TAIL = re.compile(r"[\s*xX.•\-]+$")  # ส่วนที่ธนาคารปิดไว้ท้ายนามสกุล เช่น "บุ***", "บ."


def _strip_title(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", s).strip()  # ตัดหมายเหตุในวงเล็บ เช่น "(ข้อมูลสมมติ)"
    low = s.lower()
    for t in _TITLES:
        if low.startswith(t):
            return s[len(t):].strip(" .")
    return s


def _person_matches(got: str, account: str) -> bool:
    """ชื่อจริงต้องตรงทั้งคำ · นามสกุลในสลิปมักถูกปิดบางส่วน (บุ***, บ.) จึงยอมให้เป็นส่วนต้นของนามสกุลจริง"""
    g = _strip_title(got).split()
    a = _strip_title(account).split()
    if not g or not a or _norm(g[0]) != _norm(a[0]):
        return False
    if len(g) == 1:
        return True
    shown = _norm(_MASK_TAIL.sub("", " ".join(g[1:])))
    return not shown or (len(a) > 1 and _norm(" ".join(a[1:])).startswith(shown))


def payer_matches(payer: str | None, account_name: str) -> bool | None:
    """ชื่อบัญชีรับเงินคืนเป็นคนเดียวกับผู้โอนมัดจำไหม · None = สลิปไม่มีชื่อผู้โอน (ร้านดูรูปสลิปเอง)"""
    if not payer or not payer.strip():
        return None
    return _person_matches(payer, account_name)


def receiver_matches(name: str | None) -> bool | None:
    """True = โอนเข้าบัญชีร้าน · False = โอนให้คนอื่นแน่ ๆ · None = ตรวจด้วยโค้ดไม่ได้ (ให้ร้านตรวจเอง)

    บัญชีร้านเป็นชื่อบุคคล (payment.account_name ใน catalog) และรับชื่อร้านด้วย (บัญชีร้านค้า/พร้อมเพย์)
    ชื่อภาษาอังกฤษที่ไม่ใช่ชื่อร้าน → None เพราะการสะกดชื่อไทยเป็นอังกฤษไม่แน่นอน ห้ามปฏิเสธลูกค้าเพราะเดาผิด
    """
    if not name or not name.strip():
        return None
    catalog = pricing.load_catalog()
    shop = catalog["shop"]
    got = _norm(name)
    business = {_norm(shop["name"]), _norm(shop["name_en"]), _norm("หอมหอม")}
    if any(c and c in got for c in business):
        return True
    if _person_matches(name, catalog["payment"]["account_name"]):
        return True
    return False if _THAI.search(name) else None


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

    match = receiver_matches(slip.receiver_name)
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
    if receiver_matches(slip.receiver_name) is False:
        problems.append(f"ชื่อผู้รับเงินในสลิป ({slip.receiver_name}) ไม่ใช่บัญชีของร้าน รบกวนตรวจสอบว่าโอนถูกบัญชีไหมคะ")

    if problems:
        return "ได้รับรูปสลิปแล้วค่ะ แต่พบจุดที่ต้องตรวจสอบ:\n" + "\n".join(f"- {p}" for p in problems) + (
            "\n\nแอดมินจะช่วยตรวจสอบและติดต่อกลับอีกครั้งนะคะ"
        )
    return (
        f"ได้รับรูปสลิปมัดจำ {deposit} บาทแล้วค่ะ "
        "แอดมินจะตรวจยอดเข้าบัญชีและยืนยันคิวให้อีกครั้งนะคะ"
    )

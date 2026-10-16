"""ปุ่มทางลัดใต้คำตอบของบอท + คำตอบสำเร็จรูปเมื่อลูกค้าพิมพ์เบอร์/เลขจองมาในแชท

แชทบอททำบางอย่างแทนลูกค้าไม่ได้ (เช็คสถานะคิว, ยกเลิกคิว, ดูการคืนเงิน — ต้องยืนยันตัวตนในระบบจอง)
แทนที่จะปล่อยให้บอทขอเบอร์โทรแล้วถูก guardrails ปฏิเสธ เราชี้ลูกค้าไปที่ปุ่มของฟังก์ชันนั้นแทน
ตัดสินด้วยคำในข้อความ (ไม่ใช้ LLM) — ผลเหมือนเดิมทุกครั้ง และเทสได้
"""

import re

CHECK_WORDS = re.compile(
    r"เช็ค\s*คิว|เช็ก\s*คิว|ตรวจ\s*คิว|สถานะ|ยืนยัน(คิว)?(แล้ว)?(หรือ)?ยัง|คิว(ของ)?(ฉัน|ผม|หนู|เรา|เค้า|เขา)"
    r"|จองไว้|จองแล้ว|คืนเงิน|โอนคืน|เงินคืน|refund",
    re.IGNORECASE,
)
CANCEL_WORDS = re.compile(r"ยกเลิก|cancel|ไม่ไปแล้ว|ไปไม่ได้", re.IGNORECASE)
# เจตนาจอง: พูดถึงการจอง/นัด หรือถามช่องว่าง — "คิว" คำเดียวไม่นับ (เช่น "รับคิวสุดท้ายกี่โมง" คือถามเวลาร้าน)
BOOK_WORDS = re.compile(r"จอง|นัด|คิวว่าง|มีคิว|ว่าง\s*(ไหม|มั้ย|หรือเปล่า|รึเปล่า)")
# อยากส่งรูปน้อง/สลิปให้ดู — เช่น "อยากส่งรูปให้ประเมินราคา" "ขอส่งรูปน้องหน่อย" "ถ่ายรูปให้ดูได้ไหม"
PHOTO_WORDS = re.compile(
    r"(ส่ง|อัพ|อัป|แนบ|ถ่าย|โหลด)\s*(โหลด\s*)?(รูป|ภาพ)|(รูป|ภาพ)(น้อง|หมา|แมว)?\S{0,12}(ประเมิน|ดู\s*(ให้|หน่อย|ไหม|ได้))"
    r"|ประเมิน\S{0,10}(จาก|ด้วย)\s*(รูป|ภาพ)|\b(photo|picture|image)\b",
    re.IGNORECASE,
)

# เบอร์มือถือ/บ้านไทย หรือเลขจอง HH-1004-01 — ลูกค้ามักส่งมาเพื่อให้บอทเช็คคิวให้
_PHONE = re.compile(r"(?<!\d)0\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)")
_BOOKING_ID = re.compile(r"\bHH-\d{4}-\d{2,3}\b", re.IGNORECASE)
_FILLER = re.compile(r"[\s\d\-.,:/()+]|ค่ะ|คะ|ครับ|นะ|จ้า|เบอร์|โทร|เลข(ที่)?จอง|เลข|ของ(ฉัน|ผม|หนู)|คือ|ค่า")


def lookup_request(message: str) -> bool:
    """ลูกค้าส่งเบอร์โทร/เลขจองมาให้เช็ค (เบอร์ล้วน ๆ หรือมาพร้อมคำว่าเช็คคิว/ยกเลิก/สถานะ)"""
    text = message or ""
    if not (_PHONE.search(text) or _BOOKING_ID.search(text)):
        return False
    rest = _FILLER.sub("", _BOOKING_ID.sub("", text))
    return not rest or bool(CHECK_WORDS.search(text) or CANCEL_WORDS.search(text) or BOOK_WORDS.search(text))


def check_url() -> str:
    from config import settings

    return settings.PUBLIC_SITE_URL.rstrip("/") + "/check"


def lookup_reply(channel: str = "web") -> str:
    """ตอบแทน LLM เมื่อ lookup_request() — ไม่ขอ/ไม่ทวนเบอร์ และบอกทางไปปุ่มที่ทำได้จริง"""
    if channel == "line":
        where = f"เปิดลิงก์นี้ {check_url()} แล้วกรอกเบอร์โทรที่ใช้จองได้เลยค่ะ"
    elif channel == "voice":
        where = "กดปุ่มเช็คคิวที่ขึ้นบนหน้าจอ แล้วกรอกเบอร์โทรที่ใช้จองได้เลยค่ะ"
    else:
        where = "กดปุ่ม \"เช็คคิว\" ด้านล่าง (หรือมุมบนขวาของหน้าเว็บ) แล้วกรอกเบอร์โทรที่ใช้จองได้เลยค่ะ"
    return (
        "เพื่อความปลอดภัยของข้อมูล น้องหอมเปิดดูคิวในแชทไม่ได้ค่ะ "
        f"{where} จะเห็นวันเวลานัด สถานะคิว และการคืนเงิน ถ้าต้องการยกเลิกคิวก็กดยกเลิกได้จากหน้านั้นเลยค่ะ"
    )


def contact_suggested(reply: str) -> bool:
    """บอทบอกให้ติดต่อร้าน (ไม่มีข้อมูลในคลังความรู้ / น้ำหนักผิดปกติ / คำตอบถูกแทนด้วย fallback)
    ดูจากเบอร์โทรหรือ LINE ของร้านในคำตอบ — ไม่ผูกกับถ้อยคำ จึงใช้ได้กับทุกข้อความที่แนะนำให้ติดต่อร้าน"""
    from shop import pricing

    contacts = pricing.load_catalog()["shop"]["contacts"]
    return contacts["phone"] in (reply or "") or contacts["line"] in (reply or "")


def suggest(message: str, reply: str = "") -> list[str]:
    """ปุ่มที่ควรแสดงใต้คำตอบ เรียงตามความสำคัญ: "photo" | "check" | "cancel" | "book" | "call" + "line" """
    text, said = message or "", reply or ""
    actions = []
    if PHOTO_WORDS.search(text) or "ปุ่มส่งรูป" in said or 'ปุ่ม "ส่งรูปน้อง"' in said:
        actions.append("photo")
    if CANCEL_WORDS.search(text) or "ยกเลิกคิว" in said:
        actions.append("cancel")
    if CHECK_WORDS.search(text) or "เช็คคิว" in said or lookup_request(text):
        actions.insert(0, "check")
    if 'กดปุ่ม "จองคิว"' in said or 'ปุ่ม "จองคิว"' in said:
        actions.insert(0, "book")  # บอทบอกให้กดปุ่มจอง → ต้องมีปุ่มจองเสมอ (ขึ้นก่อนปุ่มอื่น)
    elif not [a for a in actions if a != "photo"] and (BOOK_WORDS.search(text) or "จองคิว" in said):
        actions.append("book")
    if contact_suggested(said):
        # ถามเรื่องร้านที่แชทตอบไม่ได้ → ปุ่มโทร/แอด LINE (ถ้ามีปุ่มเช็คคิว/ยกเลิกอยู่แล้วให้ต่อท้าย)
        # คำตอบ "ยังไม่มีข้อมูล" ล้วน ๆ ไม่ปนกับปุ่มจอง
        if "ยังไม่มีข้อมูล" in said:
            actions = [a for a in actions if a != "book"]
        actions += ["call", "line"]
    return actions

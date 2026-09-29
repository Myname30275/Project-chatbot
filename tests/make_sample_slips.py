"""สร้างภาพสลิปโอนเงิน "จำลอง" สำหรับทดสอบ Vision (ไม่ใช่สลิปจริง ไม่มีข้อมูลบุคคลจริง)

    python tests/make_sample_slips.py

ใช้ฟอนต์ Leelawadee UI ของ Windows (รองรับภาษาไทย)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "Image"
FONT = "C:/Windows/Fonts/LeelawUI.ttf"
FONT_BOLD = "C:/Windows/Fonts/leelawdb.ttf"

SLIPS = {
    "slip_ok_50.png": {
        "amount": "50.00", "receiver": "Hom Hom Grooming", "receiver_acc": "xxx-x-x4521-x",
        "date": "29 ก.ย. 69", "time": "14:32", "ref": "20260929143215842",
    },
    "slip_wrong_500.png": {
        "amount": "500.00", "receiver": "นาย สมมติ ทดสอบ", "receiver_acc": "xxx-x-x9087-x",
        "date": "29 ก.ย. 69", "time": "15:05", "ref": "20260929150533120",
    },
}


def draw(path: Path, s: dict) -> None:
    img = Image.new("RGB", (720, 1100), "#f4f7fb")
    d = ImageDraw.Draw(img)
    f = lambda size, bold=False: ImageFont.truetype(FONT_BOLD if bold else FONT, size)  # noqa: E731
    d.rectangle([0, 0, 720, 150], fill="#4b2d83")
    d.text((40, 45), "ธนาคารสมมติ (ตัวอย่างทดสอบ)", font=f(36, True), fill="white")
    d.text((40, 180), "โอนเงินสำเร็จ", font=f(40, True), fill="#1f9d55")
    d.text((40, 240), f"{s['date']}  {s['time']} น.", font=f(28), fill="#555")

    y = 320
    for label, value, sub in [
        ("จาก", "นาย ลูกค้า ตัวอย่าง", "xxx-x-x1234-x"),
        ("ไปยัง", s["receiver"], s["receiver_acc"]),
    ]:
        d.text((40, y), label, font=f(26), fill="#888")
        d.text((170, y), value, font=f(32, True), fill="#222")
        d.text((170, y + 45), sub, font=f(26), fill="#666")
        y += 140

    d.line([40, y, 680, y], fill="#ccc", width=2)
    d.text((40, y + 30), "จำนวนเงิน", font=f(28), fill="#888")
    d.text((40, y + 75), f"{s['amount']} บาท", font=f(56, True), fill="#222")
    d.text((40, y + 180), "ค่าธรรมเนียม 0.00 บาท", font=f(26), fill="#666")
    d.text((40, y + 230), f"เลขที่รายการ: {s['ref']}", font=f(26), fill="#666")
    d.text((140, 1030), "ภาพจำลองเพื่อทดสอบระบบ ไม่ใช่หลักฐานการโอนจริง", font=f(22), fill="#c0392b")
    img.save(path)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, spec in SLIPS.items():
        draw(OUT / name, spec)
        print("สร้าง", OUT / name)

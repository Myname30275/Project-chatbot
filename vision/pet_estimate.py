"""รูปสัตว์เลี้ยง → ประเมินราคาเบื้องต้น

Vision (Gemini) บอกแค่ "เห็นอะไร" (ชนิด ขนาด ขนพัน แผล) — ตัวเลขราคาทั้งหมดคำนวณด้วยโค้ดจาก
shop/catalog.json ผ่าน pricing.quote() ไม่ให้โมเดลคิดราคาเอง ผลลัพธ์เป็นข้อความสรุปให้โมเดลแชตเล่าต่อ
"""

from shop import pricing
from vision.image_analyzer import Animal, ImageAnalysis

_SIZE_TH = {"small": "สุนัขเล็ก (< 10 กก.)", "medium": "สุนัขกลาง (10–25 กก.)", "large": "สุนัขใหญ่ (> 25 กก.)"}
_COAT_TH = {"short": "ขนสั้น", "medium": "ขนยาวปานกลาง", "long": "ขนยาว", "unknown": "ความยาวขนไม่ชัด"}
_MATTING_TH = {"none": "ไม่พบขนพัน", "mild": "ขนพันบางจุด", "severe": "ขนพันมาก", "unknown": "มองไม่ชัดว่าขนพันไหม"}


def _range(q: pricing.Quote) -> str:
    return f"{q.min:,} บาท" if q.min == q.max else f"{q.min:,}–{q.max:,} บาท"


def _describe_animal(i: int, a: Animal) -> list[str]:
    head = f"ตัวที่ {i}: {a.species_name or a.species}"
    if a.breed_guess:
        head += f" (น่าจะเป็น {a.breed_guess})"

    if a.species == "other":
        return [f"{head} — ร้านรับเฉพาะสุนัขและแมว จึงให้บริการสัตว์ชนิดนี้ไม่ได้"]
    if a.wound:
        return [f"{head} — เห็นร่องรอยแผลหรือปัญหาผิวหนังในรูป: ร้านงดรับบริการ ให้แนะนำพบสัตวแพทย์ก่อน (ไม่ต้องแจ้งราคา)"]

    if a.species == "cat":
        size_key, size_text = "cat", "แมว (ราคาเดียวทุกขนาด)"
    elif a.size in _SIZE_TH:
        size_key, size_text = a.size, _SIZE_TH[a.size]
    else:
        return [f"{head} — ประเมินขนาดจากรูปไม่ได้ ให้ถามน้ำหนักของน้องก่อนแจ้งราคา"]

    addons = ("dematting",) if a.matting in ("mild", "severe") else ()
    bath = pricing.quote("bath", size_key, addons)
    groom = pricing.quote("full_groom", size_key, addons)
    lines = [
        f"{head} — ขนาดที่ประเมินจากรูป: {size_text}, {_COAT_TH[a.coat_length]}, {_MATTING_TH[a.matting]}",
        f"  - อาบน้ำ + เป่าขน: {_range(bath)}",
        f"  - ตัดขนทั้งตัว (รวมอาบน้ำ): {_range(groom)}",
    ]
    if addons:
        lines.append("  (รวมค่ากำจัดขนพันแล้ว ราคาจริงประเมินหน้างานตามความรุนแรง)")
    elif a.matting == "unknown":
        lines.append("  (ถ้าขนพันจะมีค่าเพิ่มตามรายการกำจัดขนพัน)")
    return lines


def estimate_text(analysis: ImageAnalysis) -> str:
    animals = analysis.animals
    if not animals:
        return "ผลวิเคราะห์รูป: ไม่พบสัตว์ในรูป ให้ขอรูปใหม่ที่เห็นตัวน้องชัด ๆ"
    lines = [
        f"ผลวิเคราะห์รูปสัตว์เลี้ยงที่ลูกค้าส่งมา (พบ {len(animals)} ตัว) — "
        "ราคาคำนวณโดยระบบของร้านจากตารางราคาแล้ว ใช้ตัวเลขนี้ตอบได้เลย:"
    ]
    for i, a in enumerate(animals, 1):
        lines += _describe_animal(i, a)
    if any(a.species in ("dog", "cat") and not a.wound for a in animals):
        lines.append(
            "หมายเหตุสำหรับตอบลูกค้า: ขนาดประเมินจากรูปเท่านั้น ให้ขอน้ำหนักจริงของน้องเพื่อยืนยัน "
            "และแจ้งว่าเป็นราคาประเมินเบื้องต้น ราคาจริงอาจเปลี่ยนหน้างาน"
        )
    return "\n".join(lines)


def _animal_reply(a: Animal) -> str:
    name = a.species_name or "สัตว์ชนิดนี้"
    if a.species == "other":
        return f"ขออภัยค่ะ ร้านรับอาบน้ำ-ตัดขนเฉพาะสุนัขและแมว จึงให้บริการ{name}ไม่ได้ค่ะ"
    if a.wound:
        return (
            f"จากรูป {name}ดูเหมือนจะมีแผลหรือปัญหาผิวหนัง แนะนำพาน้องไปพบสัตวแพทย์ก่อนนะคะ "
            "ร้านของดรับบริการจนกว่าน้องจะหายค่ะ"
        )
    if a.species == "cat":
        size_key, size_text = "cat", "แมว"
    elif a.size in _SIZE_TH:
        size_key, size_text = a.size, _SIZE_TH[a.size]
    else:
        return f"ประเมินขนาดของ{name}จากรูปไม่ได้ค่ะ รบกวนแจ้งน้ำหนักของน้องด้วยนะคะ"

    addons = ("dematting",) if a.matting in ("mild", "severe") else ()
    bath = pricing.quote("bath", size_key, addons)
    groom = pricing.quote("full_groom", size_key, addons)
    breed = f" ({a.breed_guess})" if a.breed_guess else ""
    lines = [
        f"น้อง{name}{breed} ดูจากรูปเป็น{size_text}ค่ะ",
        f"- อาบน้ำ + เป่าขน {_range(bath)}",
        f"- ตัดขนทั้งตัว (รวมอาบน้ำ) {_range(groom)}",
    ]
    if addons:
        lines.append("  (รวมค่ากำจัดขนพันแล้ว ประเมินหน้างานตามความรุนแรง)")
    return "\n".join(lines)


def customer_reply(analysis: ImageAnalysis) -> str:
    """ข้อความตอบลูกค้าทันทีที่ส่งรูปมา — สร้างด้วยโค้ดทั้งหมด (ไม่ผ่าน LLM) จึงถูกต้องแน่นอนทุกครั้ง
    ทดสอบจริงแล้วถ้าให้ LLM เล่าผลวิเคราะห์เอง ผลไม่สม่ำเสมอ (บางรอบตอบว่ารับอาบน้ำจระเข้)"""
    animals = analysis.animals
    if not animals:
        return "ได้รับรูปแล้วค่ะ แต่ไม่เห็นตัวน้องชัด ๆ รบกวนส่งรูปใหม่ที่เห็นตัวน้องทั้งตัวได้ไหมคะ"
    parts = []
    for i, a in enumerate(animals, 1):
        text = _animal_reply(a)
        parts.append(f"ตัวที่ {i}: {text}" if len(animals) > 1 else text)
    if any(a.species in ("dog", "cat") and not a.wound and (a.species == "cat" or a.size in _SIZE_TH)
           for a in animals):
        parts.append(
            "ราคานี้ประเมินจากรูปเบื้องต้นนะคะ รบกวนแจ้งน้ำหนักจริงของน้องเพื่อยืนยัน "
            "ราคาจริงอาจเปลี่ยนหน้างานถ้าขนพันมากค่ะ"
        )
    return "\n\n".join(parts)

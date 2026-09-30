"""ช่องเวลาที่เปิดให้จอง — คำนวณจาก shop/catalog.json ส่วน "booking"

เวลาทั้งหมดเป็นเวลาไทย (UTC+7) แบบ offset คงที่ เพราะ Vercel รันเป็น UTC และ zoneinfo บน
Windows ต้องลงแพ็กเกจ tzdata เพิ่ม — ประเทศไทยไม่มี daylight saving จึงใช้ offset ตรง ๆ ได้
"""

from datetime import date, datetime, time, timedelta, timezone

from shop import pricing

TZ = timezone(timedelta(hours=7))

_WEEKDAYS = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]
_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
           "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def config() -> dict:
    return pricing.load_catalog()["booking"]


def now() -> datetime:
    return datetime.now(TZ)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def day_slots(d: date) -> list[datetime]:
    """ช่องเวลาทั้งหมดของวันนั้น (วันปิดร้าน = ว่างเปล่า) — closed_weekdays ใช้เลขแบบ
    date.weekday(): 0 = จันทร์ … 6 = อาทิตย์"""
    cfg = config()
    if d.weekday() in cfg["closed_weekdays"]:
        return []
    step = timedelta(minutes=cfg["slot_minutes"])
    t = datetime.combine(d, _hhmm(cfg["open"]), TZ)
    last = datetime.combine(d, _hhmm(cfg["last_start"]), TZ)
    out = []
    while t <= last:
        out.append(t)
        t += step
    return out


def bookable_days(at: datetime | None = None) -> list[date]:
    """วันที่จองได้: ล่วงหน้าอย่างน้อย min_days_ahead ถึง max_days_ahead วัน (ตามนโยบายร้าน)"""
    cfg = config()
    today = (at or now()).astimezone(TZ).date()
    return [today + timedelta(days=i) for i in range(cfg["min_days_ahead"], cfg["max_days_ahead"] + 1)]


def slot_key(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%dT%H:%M")


def parse_key(key: str) -> datetime:
    """แปลง key กลับเป็น datetime โดยไม่ตรวจว่ายังจองได้ไหม (ใช้กับการจองที่บันทึกไว้แล้ว)"""
    return datetime.strptime(key, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)


def parse_slot(key: str, at: datetime | None = None) -> datetime | None:
    """คืน datetime ถ้า key เป็นช่องที่เปิดให้จองจริงตอนนี้ — ไม่งั้น None (กันส่งเวลามั่วมาเอง)"""
    try:
        dt = parse_key(key)
    except (TypeError, ValueError):
        return None
    if dt.date() not in bookable_days(at):
        return None
    return dt if dt in day_slots(dt.date()) else None


def all_keys(at: datetime | None = None) -> list[str]:
    return [slot_key(s) for d in bookable_days(at) for s in day_slots(d)]


def availability(counts: dict[str, int], at: datetime | None = None) -> list[dict]:
    """ตารางให้หน้าเว็บ: [{date, label, open, slots: [{key, time, left}]}] — วันปิดส่งมาด้วย
    (open=False) ให้ปฏิทินแสดงเป็นวันหยุดได้"""
    cap = config()["capacity_per_slot"]
    out = []
    for d in bookable_days(at):
        slots = [
            {"key": slot_key(s), "time": s.strftime("%H:%M"), "left": max(0, cap - counts.get(slot_key(s), 0))}
            for s in day_slots(d)
        ]
        out.append({"date": d.isoformat(), "label": day_label(d), "open": bool(slots), "slots": slots})
    return out


def day_label(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year + 543}"


def slot_label(dt: datetime) -> str:
    """เช่น "ส. 4 ต.ค. 2569 10:00 น." — ใช้บนใบจองและหลังบ้าน"""
    dt = dt.astimezone(TZ)
    return f"{day_label(dt.date())} {dt.strftime('%H:%M')} น."

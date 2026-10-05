"""ด่านที่ 3 (ขาออก): ตรวจคำตอบของบอทด้วยโค้ดก่อนถึงลูกค้า — ด่านที่กันเรื่องสำคัญของร้านจริง ๆ

ต่อให้ลูกค้าหลอกบอทผ่านด่านขาเข้าได้ คำตอบที่มีสิ่งต่อไปนี้จะไม่ถูกส่งออก (แทนด้วยข้อความ fallback):

1. ราคาที่ไม่มีในร้าน — ทุกตัวเลขที่ตามด้วย "บาท" ต้องเป็นราคาใน catalog, ผลรวมของราคา 1–3 รายการ
   (เช่น ตัดขน + สปา) หรือราคาหลังลดตามแพ็กเกจสมาชิก
2. ส่วนลดที่ไม่มีในร้าน — ทุกตัวเลขที่ตามด้วย "%" ต้องเป็นส่วนลดที่ประกาศไว้
   ยกเว้นประโยคที่ปฏิเสธชัดเจน เช่น "ส่วนลด 50% ไม่มีในนโยบายของร้าน" (บอทกำลังปฏิเสธ ไม่ได้ให้)
3. ข้อมูลส่วนตัว — เบอร์โทร/เลขบัตรประชาชน/อีเมล ที่ไม่ใช่ของร้าน และไม่ใช่ที่ลูกค้าคนนี้พิมพ์มาเอง
   (OWASP LLM02 Sensitive Information Disclosure)
4. กฎภายในหลุด — คำตอบพูดถึง "คำสั่งระบบ", "ข้อความเมื่อไม่มีข้อมูล", "ต้องทำข้อ 4" ฯลฯ
   (พบจริงระหว่างทดสอบ: บอทอธิบายกฎให้ลูกค้าฟังในวงเล็บ)

ตรวจทีละประโยค: โหมดสตรีมจะปล่อยข้อความให้ลูกค้าเห็นทีละประโยคที่ตรวจผ่านแล้วเท่านั้น
(ดู OutputGuard.feed) ลูกค้าจึงไม่มีทางเห็นประโยคที่ไม่ผ่าน แม้แต่ชั่วขณะ

ข้อจำกัด (ตอบ Q&A): อ่านได้แค่ตัวเลขอารบิก/เลขไทย ไม่อ่านตัวเลขที่สะกดเป็นคำ ("ห้าสิบเปอร์เซ็นต์")
จึงสั่งใน prompt ให้เขียนราคาเป็นตัวเลขเสมอ
"""

import itertools
import re
from functools import lru_cache

from shop import pricing

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_THAI_RE = re.compile(r"[ก-๛]")

_BAHT_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(?:บาท|฿|baht)", re.IGNORECASE)
_BAHT_PREFIX_RE = re.compile(r"฿\s*(\d{1,3}(?:,\d{3})+|\d+)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|เปอร์เซ็นต์|เปอร์เซ็น|percent)", re.IGNORECASE)

_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-\s]?\d{3}[-\s]?\d{3,4}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d[-\s]?\d{4}[-\s]?\d{5}[-\s]?\d{2}[-\s]?\d(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# คำปฏิเสธที่ชัดเจน (ไม่ใช้แค่ "ไม่" เดี่ยว ๆ เพราะ "ไม่ต้องจ่ายเต็ม ลด 50%" คือการให้ส่วนลด)
_NEGATION_RE = re.compile(
    r"ไม่มี|ไม่ได้|ไม่สามารถ|ไม่ใช่|ไม่อยู่ใน|ไม่รองรับ|ยืนยัน\S{0,6}ไม่ได้|ให้ไม่ได้"
    r"|\bnot\b|\bno\b|cannot|can't|unavailable",
    re.IGNORECASE,
)

# วลีที่มีแต่ในคำสั่งระบบ ถ้าโผล่ในคำตอบแปลว่าบอทกำลังเล่ากฎภายในให้ลูกค้าฟัง
# (OWASP LLM07/LLM08 — เปิดเผย system prompt / hidden context)
_LEAK_RE = re.compile(
    r"คำสั่งระบบ|system\s*prompt|เมื่อไม่มีข้อมูล|ข้อมูลร้านที่ค้นได้|ข้อมูลหลักของร้าน|"
    r"(ตาม|ใน)\s*(กฎ)?\s*(ข้อ)?\s*(ต้องทำ|ห้ามทำ)|ต้องทำ\s*ข้อ|ห้ามทำ\s*ข้อ",
    re.IGNORECASE,
)

# ขอบประโยค: ขึ้นบรรทัดใหม่ / คำลงท้าย "ค่ะ คะ ครับ" ตามด้วยช่องว่าง / . ! ? ตามด้วยช่องว่าง
_BOUNDARY_RE = re.compile(r"\n|(?:ค่ะ|คะ|ครับ)(?=\s)|[.!?](?=\s)")
_MAX_PENDING = 300  # ข้อความค้างเกินนี้โดยไม่เจอขอบประโยค ให้ตัดที่ช่องว่างสุดท้ายแทน


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@lru_cache
def allowed_baht() -> frozenset[float]:
    c = pricing.load_catalog()
    base: set[int] = {c["payment"]["deposit"]}
    for s in c["services"]:
        base |= set(s["prices"].values()) if "prices" in s else {s["price"]}
    for a in c["addons"]:
        base |= {a[k] for k in ("price", "price_min", "price_max") if k in a}
    base |= {d["price"] for d in c["delivery"]} | {p["price"] for p in c["products"]}

    sums = {sum(combo) for r in (1, 2, 3) for combo in itertools.combinations_with_replacement(sorted(base), r)}
    discounts = [p["discount_percent"] for p in c["packages"]]
    discounted = {round(s * (100 - d) / 100, 2) for s in sums for d in discounts}
    return frozenset({float(x) for x in sums} | discounted)


@lru_cache
def allowed_percent() -> frozenset[float]:
    return frozenset(float(p["discount_percent"]) for p in pricing.load_catalog()["packages"])


def _shop_contacts() -> set[str]:
    return {_digits(pricing.load_catalog()["shop"]["contacts"]["phone"])}


def check_sentence(
    sentence: str, user_pii: set[str] = frozenset(), extra_amounts: set[float] = frozenset()
) -> str | None:
    """คืนเหตุผลที่ไม่ผ่าน (LEAK / PRICE / DISCOUNT / PII) หรือ None ถ้าผ่าน"""
    text = sentence.translate(_THAI_DIGITS)
    if _LEAK_RE.search(text):
        return "LEAK"
    negated = bool(_NEGATION_RE.search(text))

    amounts = [
        float(f"{m.group(1).replace(',', '')}.{m.group(2) or 0}") for m in _BAHT_RE.finditer(text)
    ] + [float(m.group(1).replace(",", "")) for m in _BAHT_PREFIX_RE.finditer(text)]
    if any(a not in allowed_baht() and a not in extra_amounts for a in amounts) and not negated:
        return "PRICE"

    if any(float(m.group(1)) not in allowed_percent() for m in _PERCENT_RE.finditer(text)) and not negated:
        return "DISCOUNT"

    allowed_pii = _shop_contacts() | set(user_pii)
    for m in list(_PHONE_RE.finditer(text)) + list(_ID_CARD_RE.finditer(text)):
        if _digits(m.group(0)) not in allowed_pii:
            return "PII"
    for m in _EMAIL_RE.finditer(text):
        if m.group(0).lower() not in allowed_pii:
            return "PII"
    return None


# ประโยคที่ไม่อันตรายแต่ร้านไม่ให้พูด: ส่งลูกค้าไปร้านอื่น / แต่งเหตุผลทางการแพทย์เอง
# prompt สั่งห้ามแล้วแต่ Typhoon ยังหลุดเป็นบางรอบ (ทดสอบ 4 ต.ค. 2569) → ตัดเฉพาะประโยคนั้นทิ้ง ไม่บล็อกทั้งคำตอบ
_DROP_RE = re.compile(r"ร้านอื่น|ร้านที่มีบริการ|ที่อื่นที่มีบริการ|ติดเชื้อ|แพร่เชื้อ|แพร่กระจาย|การแพร่")


_PRICE_MENTION_RE = re.compile(r"\d\s*(บาท|baht|THB)", re.IGNORECASE)
_ESTIMATE_NOTE_RE = re.compile(r"ราคาประเมินเบื้องต้น|estimated price", re.IGNORECASE)


_LONE_PARTICLES = {"ค่ะ", "คะ", "นะคะ", "ครับ"}  # Typhoon บางรอบสตรีม "ค่ะ" ซ้ำท้ายคำตอบ ("…ได้ค่ะ ค่ะ")


_DOUBLE_PARTICLE_RE = re.compile(r"(นะคะ|ค่ะ|คะ)\s*ค่ะ")
_APOLOGY_RE = re.compile(r"ขออภัย(ด้วย)?(นะ)?(ค่ะ|คะ|ครับ)")
_NO_DATA_RE = re.compile(r"ยังไม่มีข้อมูล")
_ANSWERED_CHARS = 30  # ปล่อยเนื้อหาไปแล้วเกินนี้ = บอทตอบคำถามได้แล้ว


def _contact_tail() -> str:
    c = pricing.load_catalog()["shop"]["contacts"]
    return f"\nหากมีข้อสงสัยเพิ่มเติม สอบถามร้านได้ทาง LINE {c['line']} หรือโทร {c['phone']} นะคะ"


# บอทยืนยันเองว่าเวลานั้นว่าง/เต็ม — แชทไม่เห็นตารางคิวจริง (prompt ต้องทำข้อ 5 ห้ามไว้ แต่หลุดเป็นบางรอบ:
# "พรุ่งนี้เวลา 10:00 น. มีคิวว่างค่ะ") · ไม่จับประโยคเงื่อนไข เช่น "walk-in ได้ถ้ามีคิวว่าง", "เลือกวันเวลาที่ว่าง"
_AVAILABILITY_RE = re.compile(
    r"(?<!ถ้า)(?<!หาก)(?<!เมื่อ)(?<!ที่)มีคิวว่าง(ค่ะ|นะคะ|ครับ|อยู่)"
    r"|(?<!มี)คิวว่าง(ค่ะ|นะคะ|ครับ|อยู่)"
    r"|(เวลา|โมง|น\.|วัน)[^\n]{0,25}(?<!ที่)(ยังว่าง|ว่างอยู่|ว่างค่ะ|ว่างนะคะ|เต็มแล้ว|คิวเต็ม)"
)


def droppable(sentence: str) -> bool:
    return (bool(_DROP_RE.search(sentence)) or bool(_AVAILABILITY_RE.search(sentence))
            or sentence.strip() in _LONE_PARTICLES)


def pii_from_user(texts: list[str]) -> set[str]:
    """ข้อมูลติดต่อที่ลูกค้าคนนี้พิมพ์มาเอง — บอททวนกลับให้เจ้าของได้ (เช่น ยืนยันเบอร์ตอนจองคิว)"""
    out: set[str] = set()
    for t in texts:
        t = t.translate(_THAI_DIGITS)
        out |= {_digits(m.group(0)) for m in _PHONE_RE.finditer(t)}
        out |= {_digits(m.group(0)) for m in _ID_CARD_RE.finditer(t)}
        out |= {m.group(0).lower() for m in _EMAIL_RE.finditer(t)}
    return out


def split_sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in _BOUNDARY_RE.finditer(text):
        out.append(text[start : m.end()])
        start = m.end()
    if start < len(text):
        out.append(text[start:])
    return [s for s in out if s]


class OutputGuard:
    """ตรวจคำตอบทีละประโยค ใช้ได้ทั้งแบบสตรีม (feed/flush) และแบบข้อความเต็ม (check_text)"""

    def __init__(self, user_texts: list[str] | None = None, extra_amounts: set[float] | None = None):
        """extra_amounts = ยอดเงินที่ระบบอ่านได้จากสลิปของลูกค้าเอง (บอททวนได้ เช่น "โอนมา 500 บาท")"""
        self.user_pii = pii_from_user(user_texts or [])
        self.extra_amounts = set(extra_amounts or ())
        self.pending = ""
        self.blocked_reason: str | None = None
        self.said_price = False  # คำตอบมีตัวเลขราคา (… บาท / baht) แล้วหรือยัง
        self.released = 0        # จำนวนตัวอักษรเนื้อหาที่ปล่อยไปแล้ว
        self.held = ""           # "ขออภัยค่ะ" ที่รอดูว่าประโยคถัดไปเป็นข้อความไม่มีข้อมูลหรือไม่

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None

    def _release(self, text: str) -> list[str]:
        out = []
        for sentence in split_sentences(text):
            reason = check_sentence(sentence, self.user_pii, self.extra_amounts)
            if reason:
                self.blocked_reason = reason
                return out
            if droppable(sentence):
                continue
            if _PRICE_MENTION_RE.search(sentence):
                self.said_price = True
            elif _ESTIMATE_NOTE_RE.search(sentence) and not self.said_price:
                # prompt ให้พูดประโยคนี้เฉพาะคำตอบที่มีราคา แต่ Typhoon ติดพูดท้ายคำตอบที่ไม่มีราคาด้วย
                # (ทดสอบ 4 ต.ค. 2569: คำถามเห็บหมัด/โรคประจำตัว) → ตัดทิ้งเฉพาะประโยค
                continue
            self._emit(out, sentence)
        return out

    def _emit(self, out: list[str], sentence: str) -> None:
        """ปล่อยประโยคที่ผ่านแล้ว — ยกเว้น fallback "ยังไม่มีข้อมูล" ที่ Typhoon ติดต่อท้ายคำตอบที่ตอบได้แล้ว
        (ทดสอบ 4 ต.ค. 2569: ตอบเรื่องโรคประจำตัว/ยี่ห้อแชมพูถูกแล้ว แต่ปิดด้วย "เรื่องนี้น้องหอมยังไม่มีข้อมูล")
        ลูกค้าจะงงว่าตกลงมีข้อมูลหรือไม่ → แทนด้วยประโยคชวนติดต่อร้านถ้ามีข้อสงสัยเพิ่ม"""
        core = sentence.strip()
        if not core:
            if self.held:
                self.held += sentence
            else:
                out.append(sentence)
            return
        if _APOLOGY_RE.fullmatch(core):
            if self.held:
                out.append(self.held)
            self.held = sentence
            return
        if _NO_DATA_RE.search(core) and self.released >= _ANSWERED_CHARS:
            self.held = ""
            out.append(_contact_tail())
            return
        if self.held:
            out.append(self.held)
            self.held = ""
        # ประโยคภาษาอังกฤษที่ยังเขียนหน่วยเป็น "บาท" (prompt สั่งให้ใช้ baht แต่ทำตามไม่ทุกรอบ) → แปลงหน่วยให้
        if "บาท" in sentence and re.search(r"[A-Za-z]{3,}", sentence) and not _THAI_RE.search(sentence.replace("บาท", "")):
            sentence = sentence.replace("บาท", "baht")
        # คำลงท้ายซ้ำ ("…นะคะค่ะ", "…ค่ะค่ะ") — โมเดลเติม "ค่ะ" ต่อท้ายประโยคที่ลงท้ายอยู่แล้ว
        sentence = _DOUBLE_PARTICLE_RE.sub(r"\1", sentence)
        out.append(sentence)
        self.released += len(core)

    def feed(self, delta: str) -> list[str]:
        """รับข้อความที่สตรีมเข้ามา คืนส่วนที่ครบประโยคและตรวจผ่านแล้ว (พร้อมส่งให้ลูกค้า)"""
        if self.blocked:
            return []
        self.pending += delta
        last = None
        for m in _BOUNDARY_RE.finditer(self.pending):
            last = m.end()
        if last is None and len(self.pending) > _MAX_PENDING:
            cut = self.pending.rfind(" ")
            last = cut + 1 if cut > 0 else None
        if last is None:
            return []
        ready, self.pending = self.pending[:last], self.pending[last:]
        return self._release(ready)

    def flush(self) -> list[str]:
        """เรียกตอนสตรีมจบ — ตรวจข้อความที่ค้างอยู่"""
        if self.blocked:
            return []
        ready, self.pending = self.pending, ""
        out = self._release(ready)
        if self.held and not self.blocked:
            out.append(self.held)
            self.held = ""
        return out

    def check_text(self, text: str) -> str | None:
        """โหมดไม่สตรีม: คืนเหตุผลที่ไม่ผ่าน หรือ None"""
        self._release(text)
        return self.blocked_reason

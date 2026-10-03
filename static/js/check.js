/* หน้าเช็คคิว: เบอร์โทรที่ใช้จอง → รายการคิว (ชื่อน้อง วันเวลา เลขจอง สถานะ + สถานะคืนเงิน)
 * ไม่มีชื่อเจ้าของ รูป หรือสลิป เพราะค้นด้วยเบอร์อย่างเดียว (กันคนอื่นที่รู้เบอร์เห็นข้อมูลมากเกินไป)
 * สลิปโอนคืนจากร้านดูได้หลังยืนยันชื่อเจ้าของอีกชั้น (สลิปมีชื่อ/เลขบัญชีของลูกค้า)
 */
(function () {
  "use strict";

  const form = document.getElementById("check-form");
  const input = document.getElementById("check-phone");
  const errorEl = document.getElementById("check-error");
  const submit = document.getElementById("check-submit");
  const results = document.getElementById("check-results");
  const PHONE_RE = /^0\d{9}$/;
  const MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
  let lastPhone = ""; // เบอร์ที่ค้นล่าสุด — ใช้ยืนยันตัวตนตอนขอดูสลิปโอนคืน

  // "2026-10-03T20:19:00" → "3 ต.ค. 2569 20:19 น."
  function thaiStamp(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(iso || "");
    return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${Number(m[1]) + 543} ${m[4]} น.` : "";
  }

  function refundBlock(b) {
    const box = document.createElement("div");
    box.className = "check-refund";
    box.dataset.state = b.refund_status;
    const line = document.createElement("p");
    line.className = "check-refund__line";
    const amount = `${Number(b.refund_amount).toLocaleString("th-TH")} บาท`;
    line.innerHTML = "<span>คืนเงิน</span> <b></b>";
    line.querySelector("b").textContent =
      `${b.refund_status_label} ${amount}` + (b.refunded_at ? ` · ${thaiStamp(b.refunded_at)}` : "");
    box.appendChild(line);
    if (b.refund_status !== "done") {
      const wait = document.createElement("p");
      wait.className = "check-refund__hint";
      wait.textContent = "ร้านกำลังดำเนินการโอนคืนเข้าบัญชีที่แจ้งไว้ โอนแล้วจะแนบสลิปให้ดูที่นี่ค่ะ";
      box.appendChild(wait);
      return box;
    }
    if (!b.refund_proof) return box;

    const open = document.createElement("button");
    open.type = "button";
    open.className = "btn btn--ghost btn--small";
    open.textContent = "ดูสลิปโอนคืน";
    const form = document.createElement("form");
    form.className = "check-refund__form";
    form.noValidate = true;
    form.hidden = true;
    form.innerHTML = `
      <label class="field">
        <span>ยืนยันชื่อเจ้าของ (ตามที่กรอกตอนจอง)</span>
        <input name="owner_name" maxlength="40" autocomplete="name" required />
      </label>
      <p class="field__error" role="alert"></p>
      <button type="submit" class="btn btn--small">ดูสลิป</button>`;
    const img = document.createElement("img");
    img.className = "check-refund__img";
    img.alt = `สลิปโอนคืน ${b.id}`;
    img.hidden = true;
    const err = form.querySelector(".field__error");

    open.addEventListener("click", () => {
      open.hidden = true;
      form.hidden = false;
      form.elements.owner_name.focus();
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const owner = form.elements.owner_name.value.replace(/\s+/g, " ").trim();
      if (!owner) { err.textContent = "กรุณากรอกชื่อเจ้าของ"; return; }
      const btn = form.querySelector("button");
      btn.disabled = true;
      err.textContent = "";
      try {
        const r = await fetch("/api/v1/booking/refund-proof", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ booking_id: b.id, phone: lastPhone, owner_name: owner }),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          err.textContent = body.message || "เปิดสลิปไม่สำเร็จ ลองใหม่อีกครั้งนะคะ";
          return;
        }
        img.src = URL.createObjectURL(await r.blob());
        img.hidden = false;
        form.hidden = true;
      } catch (e2) {
        console.error("[check] refund proof:", e2);
        err.textContent = "เชื่อมต่อไม่ได้ เช็กอินเทอร์เน็ตแล้วลองใหม่";
      } finally {
        btn.disabled = false;
      }
    });
    box.append(open, form, img);
    return box;
  }

  function digits() {
    return input.value.replace(/\D/g, "");
  }

  function setError(message) {
    errorEl.textContent = message || "";
    if (message) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }

  function card(b) {
    const el = document.createElement("article");
    el.className = "check-item";
    el.dataset.status = b.status;
    el.innerHTML = `
      <div class="check-item__main">
        <p class="check-item__pet"></p>
        <p class="check-item__when"></p>
        <p class="check-item__id"></p>
      </div>
      <div class="check-item__state">
        <span class="check-item__badge"></span>
        <p class="check-item__hint"></p>
      </div>`;
    el.querySelector(".check-item__pet").textContent = `น้อง${b.pet_name}`;
    el.querySelector(".check-item__when").textContent =
      b.slot_label + (b.pickup_time ? ` · ร้านไปรับน้อง ${b.pickup_time} น.` : "");
    el.querySelector(".check-item__id").textContent = `เลขจอง ${b.id}`;
    el.querySelector(".check-item__badge").textContent = b.status_label;
    el.querySelector(".check-item__hint").textContent = b.status_hint;
    if (b.refund_status) el.appendChild(refundBlock(b));
    return el;
  }

  function render(list) {
    results.innerHTML = "";
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "check__empty";
      empty.innerHTML =
        "<p><b>ไม่พบคิวของเบอร์นี้</b></p>" +
        "<p>ตรวจว่าเป็นเบอร์เดียวกับที่กรอกตอนจอง หรือจองคิวใหม่ได้เลย</p>" +
        '<a class="btn btn--small" href="/?book=1">จองคิว</a>';
      results.appendChild(empty);
      return;
    }
    const title = document.createElement("h2");
    title.className = "check__title";
    title.textContent = `คิวของคุณ ${list.length} รายการ`;
    results.appendChild(title);
    list.forEach((b) => results.appendChild(card(b)));
  }

  input.addEventListener("input", () => setError(""));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const phone = digits();
    if (!PHONE_RE.test(phone)) {
      setError("เบอร์โทรต้องเป็นตัวเลข 10 หลัก ขึ้นต้นด้วย 0");
      input.focus();
      return;
    }
    setError("");
    submit.disabled = true;
    submit.textContent = "กำลังค้นหา…";
    try {
      const r = await fetch("/api/v1/booking/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(body.message || "ค้นหาไม่สำเร็จ ลองใหม่อีกครั้ง");
        return;
      }
      lastPhone = phone;
      render(body.bookings || []);
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      console.error("[check] lookup failed:", err);
      setError("เชื่อมต่อไม่ได้ เช็กอินเทอร์เน็ตแล้วลองใหม่");
    } finally {
      submit.disabled = false;
      submit.textContent = "ดูคิวของฉัน";
    }
  });
})();

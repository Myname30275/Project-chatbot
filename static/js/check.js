/* หน้าเช็คคิว: เบอร์โทรที่ใช้จอง → รายการคิว (ชื่อน้อง วันเวลา เลขจอง สถานะ)
 * ไม่มีชื่อเจ้าของ รูป หรือสลิป เพราะค้นด้วยเบอร์อย่างเดียว (กันคนอื่นที่รู้เบอร์เห็นข้อมูลมากเกินไป)
 */
(function () {
  "use strict";

  const form = document.getElementById("check-form");
  const input = document.getElementById("check-phone");
  const errorEl = document.getElementById("check-error");
  const submit = document.getElementById("check-submit");
  const results = document.getElementById("check-results");
  const PHONE_RE = /^0\d{9}$/;

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

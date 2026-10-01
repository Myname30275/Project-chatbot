/* จองคิวในแชท: ป๊อปอัป 3 ขั้น → POST /api/v1/booking → การ์ดใบจองในแชท
 *
 * ข้อตกลงของร้าน (docs/booking-plan.md): ฟอร์มมีแค่ชื่อน้อง ชื่อเจ้าของ เบอร์โทร + เลือกช่องเวลา + สลิป
 * ใบจองไม่มีราคา (ร้านชั่งน้ำหนักจริงหน้าร้าน) และสถานะเริ่มที่ "รอร้านยืนยัน" เสมอ
 * รูปถูกย่อในเบราว์เซอร์ก่อนส่ง (เซิร์ฟเวอร์ไม่ต้องมี Pillow และเก็บใน Redis ได้พอดี)
 */
(function () {
  "use strict";

  const sheet = document.getElementById("booking-sheet");
  const form = document.getElementById("booking-form");
  const backBtn = document.getElementById("bk-back");
  const nextBtn = document.getElementById("bk-next");
  const submitBtn = document.getElementById("bk-submit");
  const statusEl = document.getElementById("bk-status");
  const daysEl = document.getElementById("bk-days");
  const timesEl = document.getElementById("bk-times");
  const summaryEl = document.getElementById("bk-summary");
  const pick = {
    pet: { input: document.getElementById("bk-pet-file"), preview: document.getElementById("bk-pet-preview"), blob: null, max: 800 },
    // สลิปย่อน้อยกว่า ให้ตัวหนังสือในสลิปยังอ่านออกตอนส่งให้ Vision ตรวจ
    slip: { input: document.getElementById("bk-slip-file"), preview: document.getElementById("bk-slip-preview"), blob: null, max: 1200 },
  };

  const DRAFT_KEY = "hh.bookingDraft";
  const ID_RE = /^HH-\d{4}-\d{2,}$/;
  const PHONE_RE = /^0\d{9}$/;
  const BOOK_WORDS = /จอง|นัด|คิว/;

  let step = 1;
  let days = [];
  let chosenDay = null;
  let chosenSlot = null; // { key, label }
  let lastTrigger = null;
  let busy = false;

  /* ---------------- ย่อรูปในเบราว์เซอร์ ---------------- */

  async function shrink(file, maxSide) {
    try {
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close && bmp.close();
      return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    } catch (err) {
      console.warn("[booking] ย่อรูปไม่สำเร็จ ใช้ไฟล์เดิม:", err);
      return file;
    }
  }

  async function setPhoto(kind, file) {
    if (!file) return;
    const p = pick[kind];
    p.blob = await shrink(file, p.max);
    if (p.preview.src) URL.revokeObjectURL(p.preview.src);
    p.preview.src = URL.createObjectURL(p.blob);
    p.preview.hidden = false;
    clearError(kind === "pet" ? "pet_photo" : "slip");
  }

  Object.entries(pick).forEach(([kind, p]) => {
    p.input.addEventListener("change", () => {
      const file = p.input.files[0];
      p.input.value = "";
      setPhoto(kind, file);
    });
  });

  /* ---------------- ข้อความผิดพลาดใต้ช่อง ---------------- */

  function errorEl(field) {
    return form.querySelector(`[data-error-for="${field}"]`);
  }
  function showError(field, message) {
    const el = errorEl(field);
    if (el) el.textContent = message;
    const input = form.elements[field];
    if (input && input.setAttribute) input.setAttribute("aria-invalid", "true");
  }
  function clearError(field) {
    const el = errorEl(field);
    if (el) el.textContent = "";
    const input = form.elements[field];
    if (input && input.removeAttribute) input.removeAttribute("aria-invalid");
  }
  function clearAllErrors() {
    form.querySelectorAll("[data-error-for]").forEach((el) => (el.textContent = ""));
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    statusEl.textContent = "";
    statusEl.classList.remove("is-error");
  }

  function value(name) {
    return (form.elements[name].value || "").replace(/\s+/g, " ").trim();
  }
  function phoneDigits() {
    return form.elements.phone.value.replace(/\D/g, "");
  }

  function validateStep(n) {
    let ok = true;
    if (n === 1) {
      if (!pick.pet.blob) { showError("pet_photo", "กรุณาเลือกรูปน้อง"); ok = false; }
      if (!value("pet_name")) { showError("pet_name", "กรุณากรอกชื่อน้อง"); ok = false; }
      if (!value("owner_name")) { showError("owner_name", "กรุณากรอกชื่อเจ้าของ"); ok = false; }
      if (!PHONE_RE.test(phoneDigits())) { showError("phone", "เบอร์โทรต้องเป็นตัวเลข 10 หลัก ขึ้นต้นด้วย 0"); ok = false; }
    } else if (n === 2) {
      if (!chosenSlot) { showError("slot", "กรุณาเลือกวันและเวลา"); ok = false; }
    } else if (n === 3) {
      if (!pick.slip.blob) { showError("slip", "กรุณาแนบสลิปมัดจำ"); ok = false; }
    }
    return ok;
  }

  ["pet_name", "owner_name", "phone"].forEach((name) => {
    form.elements[name].addEventListener("input", () => {
      clearError(name);
      saveDraft();
    });
  });

  /* ---------------- ร่างข้อมูล (ปิดกลางคันแล้วไม่หาย) ---------------- */

  function saveDraft() {
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({
        pet_name: form.elements.pet_name.value,
        owner_name: form.elements.owner_name.value,
        phone: form.elements.phone.value,
      }));
    } catch {}
  }
  function loadDraft() {
    try {
      const d = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "{}");
      ["pet_name", "owner_name", "phone"].forEach((k) => { if (d[k]) form.elements[k].value = d[k]; });
    } catch {}
  }
  function clearDraft() {
    try { sessionStorage.removeItem(DRAFT_KEY); } catch {}
  }

  /* ---------------- ขั้นตอน ---------------- */

  function goStep(n) {
    step = n;
    form.querySelectorAll("[data-step]").forEach((el) => (el.hidden = Number(el.dataset.step) !== n));
    sheet.querySelectorAll("[data-dot]").forEach((el) => {
      const d = Number(el.dataset.dot);
      el.classList.toggle("is-current", d === n);
      el.classList.toggle("is-done", d < n);
      if (d === n) el.setAttribute("aria-current", "step");
      else el.removeAttribute("aria-current");
    });
    backBtn.hidden = n === 1;
    nextBtn.hidden = n === 3;
    submitBtn.hidden = n !== 3;
    if (n === 2 && !days.length) loadSlots();
    if (n === 3) {
      summaryEl.textContent =
        `น้อง${value("pet_name")} · ${chosenSlot ? chosenSlot.label : ""}`;
    }
    const first = form.querySelector(`[data-step="${n}"] input:not([type=file]), [data-step="${n}"] button`);
    if (first) first.focus({ preventScroll: true });
  }

  nextBtn.addEventListener("click", () => {
    if (validateStep(step)) goStep(step + 1);
  });
  backBtn.addEventListener("click", () => goStep(Math.max(1, step - 1)));

  /* ---------------- วัน / เวลา ---------------- */

  async function loadSlots() {
    daysEl.innerHTML = '<p class="sheet__muted">กำลังโหลดวันว่าง…</p>';
    timesEl.innerHTML = "";
    try {
      const r = await fetch("/api/v1/booking/slots", { cache: "no-store" });
      const body = await r.json();
      if (!r.ok) throw new Error(body.message || r.status);
      days = body.days || [];
    } catch (err) {
      console.error("[booking] loadSlots:", err);
      days = [];
      daysEl.innerHTML = "";
      showError("slot", "โหลดวันว่างไม่สำเร็จ กดย้อนกลับแล้วลองใหม่อีกครั้ง");
      return;
    }
    renderDays();
  }

  function renderDays() {
    daysEl.innerHTML = "";
    // ถ้าวันที่เคยเลือกไว้ยังเปิดอยู่ให้คงไว้ ไม่งั้นเลือกวันแรกที่ยังมีช่องว่าง
    const hasRoom = (d) => d.open && d.slots.some((s) => s.left > 0);
    if (!chosenDay || !days.some((d) => d.date === chosenDay && hasRoom(d))) {
      const first = days.find(hasRoom);
      chosenDay = first ? first.date : null;
    }
    days.forEach((d) => {
      const [wd, ...rest] = d.label.split(" ");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "day-chip";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", String(d.date === chosenDay));
      btn.disabled = !hasRoom(d);
      btn.innerHTML = '<span class="day-chip__wd"></span><span class="day-chip__date"></span><span class="day-chip__note"></span>';
      btn.querySelector(".day-chip__wd").textContent = wd;
      btn.querySelector(".day-chip__date").textContent = rest.slice(0, 2).join(" ");
      btn.querySelector(".day-chip__note").textContent = !d.open ? "ร้านปิด" : hasRoom(d) ? "" : "เต็ม";
      btn.addEventListener("click", () => {
        chosenDay = d.date;
        if (chosenSlot && !chosenSlot.key.startsWith(d.date)) chosenSlot = null;
        renderDays();
      });
      daysEl.appendChild(btn);
    });
    renderTimes();
  }

  function renderTimes() {
    timesEl.innerHTML = "";
    const day = days.find((d) => d.date === chosenDay);
    if (!day) {
      timesEl.innerHTML = '<p class="sheet__muted">ช่วง 14 วันนี้คิวเต็มแล้ว ติดต่อร้านทาง LINE ได้เลยค่ะ</p>';
      return;
    }
    day.slots.forEach((s) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "time-chip";
      btn.setAttribute("role", "radio");
      const selected = chosenSlot && chosenSlot.key === s.key;
      btn.setAttribute("aria-checked", String(!!selected));
      btn.disabled = s.left <= 0;
      btn.innerHTML = '<span class="time-chip__t"></span><span class="time-chip__left"></span>';
      btn.querySelector(".time-chip__t").textContent = s.time;
      btn.querySelector(".time-chip__left").textContent = s.left <= 0 ? "เต็ม" : s.left === 1 ? "เหลือ 1" : "ว่าง";
      btn.addEventListener("click", () => {
        chosenSlot = { key: s.key, label: `${day.label} ${s.time} น.` };
        clearError("slot");
        renderTimes();
      });
      timesEl.appendChild(btn);
    });
  }

  /* ---------------- ส่งจอง ---------------- */

  const STEP_OF_FIELD = { pet_photo: 1, pet_name: 1, owner_name: 1, phone: 1, slot: 2, slip: 3 };

  function setBusy(on) {
    busy = on;
    [backBtn, submitBtn].forEach((b) => (b.disabled = on));
    sheet.classList.toggle("is-busy", on);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    clearAllErrors();
    for (const n of [1, 2, 3]) {
      if (!validateStep(n)) { goStep(n); return; }
    }
    const data = new FormData();
    data.append("pet_name", value("pet_name"));
    data.append("owner_name", value("owner_name"));
    data.append("phone", phoneDigits());
    data.append("slot", chosenSlot.key);
    data.append("pet_photo", pick.pet.blob, "pet.jpg");
    data.append("slip", pick.slip.blob, "slip.jpg");

    setBusy(true);
    statusEl.textContent = "กำลังตรวจสลิป… อาจใช้เวลา 10–20 วินาที";
    try {
      const r = await fetch("/api/v1/booking", { method: "POST", body: data });
      const body = await r.json().catch(() => ({}));
      if (r.ok && body.booking) {
        clearDraft();
        setBusy(false); // close() ไม่ยอมปิดตอน busy (กันปิดกลางคันระหว่างส่ง) — จองเสร็จแล้วต้องปลดก่อน
        close();
        resetForm();
        showTicketInChat(body.booking, "จองคิวเรียบร้อยค่ะ นี่คือใบจองของน้อง แสดงที่หน้าร้านได้เลย ร้านจะยืนยันคิวให้อีกครั้งนะคะ");
        return;
      }
      statusEl.textContent = "";
      const field = body.field;
      if (field === "slot") {
        chosenSlot = null;
        days = [];
      }
      if (field && STEP_OF_FIELD[field]) {
        goStep(STEP_OF_FIELD[field]);
        showError(field, body.message || "ข้อมูลช่องนี้ไม่ถูกต้อง");
      } else {
        statusEl.classList.add("is-error");
        statusEl.textContent = body.message || "จองไม่สำเร็จ ลองใหม่อีกครั้งนะคะ";
      }
    } catch (err) {
      console.error("[booking] submit:", err);
      statusEl.classList.add("is-error");
      statusEl.textContent = "ติดต่อร้านไม่ได้ เช็กอินเทอร์เน็ตแล้วกดยืนยันอีกครั้ง ข้อมูลที่กรอกยังอยู่ครบ";
    } finally {
      setBusy(false);
    }
  });

  function resetForm() {
    form.reset();
    Object.values(pick).forEach((p) => {
      p.blob = null;
      p.preview.hidden = true;
      p.preview.removeAttribute("src");
    });
    chosenSlot = null;
    chosenDay = null;
    days = [];
  }

  /* ---------------- เปิด / ปิด ---------------- */

  function open(trigger) {
    lastTrigger = trigger || document.activeElement;
    clearAllErrors();
    loadDraft();
    const chat = window.hhChat || {};
    if (!pick.pet.blob && chat.lastPetFile) setPhoto("pet", chat.lastPetFile);
    sheet.hidden = false;
    document.body.classList.add("sheet-open");
    goStep(1);
  }

  function close() {
    if (busy) return;
    sheet.hidden = true;
    document.body.classList.remove("sheet-open");
    if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
  }

  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-booking]");
    if (opener) { e.preventDefault(); open(opener); return; }
    if (e.target.closest("[data-close-booking]")) { close(); return; }
    const picker = e.target.closest("[data-pick]");
    if (picker && sheet.contains(picker)) pick[picker.dataset.pick].input.click();
    if (e.target.closest("[data-my-bookings]")) showMyBookings();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !sheet.hidden) close();
  });

  /* ---------------- ใบจอง ---------------- */

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) { existing.dataset.loaded ? resolve() : existing.addEventListener("load", resolve); return; }
      const s = document.createElement("script");
      s.src = src;
      s.onload = () => { s.dataset.loaded = "1"; resolve(); };
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  const QR_LIB = "https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js";
  const PNG_LIB = "https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js";

  async function drawQr(box, id) {
    if (!ID_RE.test(id)) return;
    try {
      await loadScript(QR_LIB);
      const qr = window.qrcode(0, "M");
      qr.addData(id);
      qr.make();
      box.innerHTML = qr.createSvgTag({ cellSize: 3, margin: 0, scalable: true });
    } catch (err) {
      console.warn("[booking] วาด QR ไม่สำเร็จ:", err);
    }
  }

  async function saveAsImage(card, id, btn) {
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "กำลังสร้างรูป…";
    try {
      await loadScript(PNG_LIB);
      const bg = getComputedStyle(card).backgroundColor;
      // ซ่อนปุ่มจริง ๆ ระหว่างถ่าย (filter ตัดแค่ปุ่มแต่เหลือช่องว่างท้ายรูป)
      card.classList.add("is-capturing");
      let url;
      try {
        url = await window.htmlToImage.toPng(card, { pixelRatio: 2, backgroundColor: bg });
      } finally {
        card.classList.remove("is-capturing");
      }
      const a = document.createElement("a");
      a.href = url;
      a.download = `ใบจอง-${id}.png`;
      a.click();
      btn.textContent = "บันทึกแล้ว";
    } catch (err) {
      console.error("[booking] บันทึกรูปไม่สำเร็จ:", err);
      btn.textContent = "บันทึกไม่สำเร็จ ลองอีกครั้ง";
    } finally {
      setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 2000);
    }
  }

  function ticketCard(b) {
    const card = document.createElement("article");
    card.className = "ticket";
    card.dataset.status = b.status;
    card.innerHTML = `
      <header class="ticket__head">
        <img src="/static/img/logo.svg" alt="" width="36" height="36" />
        <span class="ticket__shop">Hom Hom Grooming</span>
        <span class="ticket__kind">ใบจองคิว</span>
      </header>
      <div class="ticket__photos">
        <figure><img class="ticket__pet" alt="รูปน้อง" /><figcaption>น้อง</figcaption></figure>
        <figure><img class="ticket__slip" alt="สลิปมัดจำ" /><figcaption>สลิปมัดจำ</figcaption></figure>
      </div>
      <dl class="ticket__info">
        <dt>น้อง</dt><dd data-f="pet_name"></dd>
        <dt>เจ้าของ</dt><dd data-f="owner"></dd>
        <dt>วันเวลา</dt><dd data-f="slot_label" class="ticket__when"></dd>
        <dt>เลขจอง</dt><dd data-f="id" class="ticket__id"></dd>
      </dl>
      <div class="ticket__foot">
        <div>
          <p class="ticket__status"><span class="ticket__dot"></span><span data-f="status_label"></span></p>
          <p class="ticket__note">ราคาจริงแจ้งหลังชั่งน้ำหนักที่หน้าร้าน · แสดงใบนี้ที่หน้าร้าน</p>
        </div>
        <div class="ticket__qr" aria-label="QR เลขจอง"></div>
      </div>
      <div class="ticket__actions"><button type="button" class="btn btn--small">บันทึกเป็นรูป</button></div>`;
    card.querySelector('[data-f="pet_name"]').textContent = b.pet_name;
    card.querySelector('[data-f="owner"]').textContent = `คุณ${b.owner_name} · ${b.phone}`;
    card.querySelector('[data-f="slot_label"]').textContent = b.slot_label;
    card.querySelector('[data-f="id"]').textContent = b.id;
    card.querySelector('[data-f="status_label"]').textContent = b.status_label;
    card.querySelector(".ticket__pet").src = b.pet_image;
    card.querySelector(".ticket__slip").src = b.slip_image;
    drawQr(card.querySelector(".ticket__qr"), b.id);
    const btn = card.querySelector(".ticket__actions button");
    btn.addEventListener("click", () => saveAsImage(card, b.id, btn));
    return card;
  }

  function showTicketInChat(b, intro) {
    const chat = window.hhChat;
    if (!chat) return;
    chat.ensureOpen(); // จองจากปุ่มบนหน้าแรกตอนแชทปิดอยู่ ก็ยังเห็นใบจอง
    if (intro) chat.createAiBubble().textContent = intro;
    chat.appendAiNode(ticketCard(b));
  }

  async function showMyBookings() {
    const chat = window.hhChat;
    if (!chat) return;
    try {
      const r = await fetch("/api/v1/booking/mine", { cache: "no-store" });
      const body = await r.json();
      const list = body.bookings || [];
      if (!list.length) {
        const bubble = chat.createAiBubble();
        bubble.textContent = "ยังไม่มีใบจองค่ะ กดปุ่มด้านล่างเพื่อจองคิวได้เลย";
        addCta(bubble);
        return;
      }
      chat.createAiBubble().textContent = `ใบจองของคุณ ${list.length} ใบค่ะ`;
      list.slice(0, 5).forEach((b) => chat.appendAiNode(ticketCard(b)));
    } catch (err) {
      console.error("[booking] mine:", err);
      chat.createAiBubble().textContent = "เปิดใบจองไม่สำเร็จ ลองกดอีกครั้งนะคะ";
    }
  }

  /* ---------------- ปุ่ม "จองคิว" ใต้คำตอบของบอท ---------------- */

  function addCta(bubble) {
    const wrap = bubble && bubble.parentElement;
    if (!wrap || wrap.querySelector(".book-cta")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn--small book-cta";
    btn.dataset.openBooking = "";
    btn.textContent = "จองคิว";
    wrap.appendChild(btn);
  }

  window.hhBooking = {
    open,
    addCta,
    // เรียกจาก chat.js หลังบอทตอบ — ลูกค้าพูดถึงการจอง/นัด/คิว ก็ต่อปุ่มจองให้เลย (ไม่ใช้ LLM ตัดสิน)
    maybeAddCta(userText, bubble) {
      if (BOOK_WORDS.test(userText || "")) addCta(bubble);
    },
  };

  // มาจากปุ่ม "จองคิว" ในหน้าอวตาร (/?book=1) → เปิดแชท + ป๊อปอัปจองทันที แล้วล้าง ?book ออกจาก URL
  // (กดรีเฟรชจะได้ไม่เด้งซ้ำ) — ใบจองที่ได้จะขึ้นในแชท ซึ่งมีบทสนทนาจากโหมดเสียงอยู่แล้ว (session เดียวกัน)
  if (new URLSearchParams(location.search).has("book")) {
    history.replaceState(null, "", location.pathname + location.hash);
    window.hhChat?.ensureOpen();
    open();
  }
})();

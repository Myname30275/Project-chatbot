/* จองคิวในแชท: ป๊อปอัป 3 ขั้น → POST /api/v1/booking → การ์ดใบจองในแชท
 *
 * ข้อตกลงของร้าน (docs/booking-plan.md): ฟอร์มมีแค่ชื่อน้อง ชื่อเจ้าของ เบอร์โทร + เลือกช่องเวลา + สลิป
 * ใบจองในแชทมีปุ่ม "ยกเลิกคิว" (ก่อนนัด 3 ชม.) → กรอกพร้อมเพย์/บัญชี → ร้านโอนคืนยอดที่โอนมา
 * ติ๊ก "รับ-ส่งน้อง" ได้ (ขั้น 2): ปักหมุดบนแผนที่ → ค่ารับส่งตามระยะ → ยอดโอน = มัดจำ + ค่ารับส่ง
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
  const PHONE_RE = /^0\d{9}$/;
  const BOOK_WORDS = /จอง|นัด|คิว/;
  const CANCEL_WORDS = /ยกเลิก|cancel/i;

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
      if (wantPickup()) {
        if (!ride) { showError("pickup", "กรุณาปักหมุดจุดรับน้องในระยะที่ร้านให้บริการ"); ok = false; }
        else if (!value("pickup_address")) { showError("pickup", "กรุณากรอกที่อยู่หรือจุดสังเกตให้คนขับ"); ok = false; }
      }
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

  /* ---------------- รับ-ส่งน้อง (แผนที่ Leaflet + OpenStreetMap — ฟรี ไม่ต้องใช้ API key) ---------------- */

  const pickupToggle = document.getElementById("bk-pickup");
  const pickupBox = document.getElementById("bk-pickup-box");
  const quoteEl = document.getElementById("bk-pickup-quote");
  const dueEl = document.getElementById("bk-due");
  const DEPOSIT = Number(form.dataset.deposit) || 50;
  const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
  let map = null;
  let pin = null;
  let pickupCfg = null;
  let ride = null; // { lat, lng, km, fee } — ค่าที่เซิร์ฟเวอร์คิดให้ (ตอนจองเซิร์ฟเวอร์คิดซ้ำเองอีกรอบ)
  let quoteSeq = 0;

  function wantPickup() {
    return pickupToggle.checked;
  }

  function loadCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }

  async function ensureMap() {
    if (map) { map.invalidateSize(); return; }
    try {
      loadCss(LEAFLET + "leaflet.min.css");
      const [cfg] = await Promise.all([
        fetch("/api/v1/booking/pickup", { cache: "no-store" }).then((r) => r.json()),
        loadScript(LEAFLET + "leaflet.min.js"),
      ]);
      pickupCfg = cfg;
    } catch (err) {
      console.error("[booking] โหลดแผนที่ไม่สำเร็จ:", err);
      showError("pickup", "โหลดแผนที่ไม่สำเร็จ ลองติ๊กใหม่อีกครั้ง หรือติดต่อร้านทาง LINE");
      return;
    }
    if (map) return; // ติ๊กรัว ๆ ระหว่างโหลด
    const L = window.L;
    const shop = [pickupCfg.shop.lat, pickupCfg.shop.lng];
    map = L.map("bk-map", { scrollWheelZoom: false }).setView(shop, 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    L.marker(shop, {
      icon: L.icon({ iconUrl: "/static/img/logo-badge.png", iconSize: [40, 40], className: "pickup__shop" }),
      title: "ร้าน",
      keyboard: false,
    }).addTo(map);
    // วงระยะให้บริการ (เส้นตรง) — ระยะถนนโดยประมาณ = เส้นตรง × road_factor
    const maxKm = pickupCfg.zones[pickupCfg.zones.length - 1].max_km;
    L.circle(shop, {
      radius: (maxKm / pickupCfg.road_factor) * 1000,
      color: "#5c3d2e", weight: 2, dashArray: "6 6", fillColor: "#e8a840", fillOpacity: 0.08,
      interactive: false,
    }).addTo(map);
    map.on("click", (e) => setPin(e.latlng));
    requestAnimationFrame(() => map.invalidateSize());
  }

  function setPin(latlng) {
    const L = window.L;
    if (!pin) {
      pin = L.marker(latlng, {
        draggable: true,
        title: "จุดรับน้อง",
        icon: L.divIcon({ className: "pickup__pin", html: "<span></span>", iconSize: [28, 28], iconAnchor: [14, 28] }),
      }).addTo(map);
      pin.on("dragend", () => fetchQuote(pin.getLatLng()));
    } else {
      pin.setLatLng(latlng);
    }
    fetchQuote(latlng);
  }

  async function fetchQuote(latlng) {
    const seq = ++quoteSeq;
    ride = null;
    updateDue();
    clearError("pickup");
    quoteEl.textContent = "กำลังคำนวณระยะทาง…";
    try {
      const r = await fetch(`/api/v1/booking/pickup?lat=${latlng.lat.toFixed(6)}&lng=${latlng.lng.toFixed(6)}`, { cache: "no-store" });
      const body = await r.json();
      if (seq !== quoteSeq) return; // ลากหมุดต่อแล้ว ผลเก่าทิ้ง
      if (!r.ok) {
        quoteEl.textContent = "";
        showError("pickup", body.message || "จุดนี้คิดค่ารับส่งไม่ได้");
        return;
      }
      ride = { lat: latlng.lat, lng: latlng.lng, km: body.km, fee: body.fee };
      quoteEl.innerHTML = "";
      const b = document.createElement("b");
      b.textContent = `ค่ารับส่ง ${body.fee} บาท`;
      quoteEl.append(`ระยะทางประมาณ ${body.km} กม. · `, b, " (ไป-กลับ)");
    } catch (err) {
      if (seq !== quoteSeq) return;
      console.error("[booking] quote:", err);
      quoteEl.textContent = "";
      showError("pickup", "คำนวณค่ารับส่งไม่สำเร็จ ลองแตะแผนที่อีกครั้ง");
    }
    updateDue();
  }

  function pickupFee() {
    return wantPickup() && ride ? ride.fee : 0;
  }

  function updateDue() {
    const fee = pickupFee();
    dueEl.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = `${DEPOSIT + fee} บาท`;
    if (fee) dueEl.append("ยอด ", b, ` (มัดจำ ${DEPOSIT} + ค่ารับส่ง ${fee})`);
    else dueEl.append("มัดจำ ", b);
  }

  // เวลาที่ร้านไปรับ = เวลานัด − lead_minutes (ตรงกับที่เซิร์ฟเวอร์คิด)
  function pickupTime() {
    if (!chosenSlot || !pickupCfg) return "";
    const [h, m] = chosenSlot.key.slice(11).split(":").map(Number);
    const t = h * 60 + m - pickupCfg.lead_minutes;
    return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
  }

  pickupToggle.addEventListener("change", () => {
    pickupBox.hidden = !wantPickup();
    clearError("pickup");
    if (wantPickup()) ensureMap();
    updateDue();
  });
  form.elements.pickup_address.addEventListener("input", () => clearError("pickup"));

  document.getElementById("bk-locate").addEventListener("click", () => {
    if (!navigator.geolocation || !map) {
      showError("pickup", "อุปกรณ์นี้หาตำแหน่งไม่ได้ แตะแผนที่ตรงบ้านแทนได้เลยค่ะ");
      return;
    }
    quoteEl.textContent = "กำลังหาตำแหน่ง…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const ll = window.L.latLng(pos.coords.latitude, pos.coords.longitude);
        map.setView(ll, 15);
        setPin(ll);
      },
      () => {
        quoteEl.textContent = "";
        showError("pickup", "เปิดตำแหน่งไม่ได้ แตะแผนที่ตรงบ้านแทนได้เลยค่ะ");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
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
    if (n === 2 && map) requestAnimationFrame(() => map.invalidateSize());
    if (n === 3) {
      summaryEl.textContent =
        `น้อง${value("pet_name")} · ${chosenSlot ? chosenSlot.label : ""}` +
        (wantPickup() && ride ? ` · ร้านไปรับน้อง ${pickupTime()} น.` : "");
      updateDue();
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

  const STEP_OF_FIELD = { pet_photo: 1, pet_name: 1, owner_name: 1, phone: 1, slot: 2, pickup: 2, slip: 3 };

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
    if (wantPickup() && ride) {
      data.append("want_pickup", "1");
      data.append("pickup_lat", ride.lat.toFixed(6));
      data.append("pickup_lng", ride.lng.toFixed(6));
      data.append("pickup_address", form.elements.pickup_address.value.trim());
    }

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
    pickupBox.hidden = true;
    ride = null;
    quoteSeq++;
    quoteEl.textContent = "";
    if (pin) { pin.remove(); pin = null; }
    updateDue();
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
    if (e.target.closest("[data-cancel-booking]")) showMyBookings({ forCancel: true });
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
  const PNG_LIB = "https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js";

  async function saveAsImage(card, id, btn) {
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "กำลังสร้างรูป…";
    try {
      await loadScript(PNG_LIB);
      // เว้นขอบรอบการ์ดทุกด้านให้กรอบไม่ชนขอบรูป: วางสำเนาการ์ดในกรอบชั่วคราวที่มี padding
      // (สีพื้นกระดาษของเว็บ) แล้วถ่ายกรอบนั้นแทน — สำเนาซ่อนปุ่ม "บันทึกเป็นรูป" ด้วย is-capturing
      const pad = 32;
      const paper = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim() || "#fffbf3";
      const frame = document.createElement("div");
      frame.style.cssText =
        `position:fixed;left:0;top:0;z-index:-1;pointer-events:none;box-sizing:content-box;` +
        `width:${card.offsetWidth}px;padding:${pad}px;background:${paper}`;
      const copy = card.cloneNode(true);
      copy.classList.add("is-capturing");
      frame.appendChild(copy);
      document.body.appendChild(frame);
      let url;
      try {
        await Promise.all([...copy.querySelectorAll("img")].map((img) => (img.decode ? img.decode().catch(() => {}) : null)));
        url = await window.htmlToImage.toPng(frame, {
          pixelRatio: 2,
          backgroundColor: paper,
          // สไตล์ fixed/z-index ของกรอบชั่วคราวไม่ต้องติดไปในรูป
          style: { position: "static", zIndex: "auto" },
        });
      } finally {
        frame.remove();
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
    card.innerHTML = `
      <header class="ticket__head">
        <img src="/static/img/logo-badge.png" alt="" width="44" height="44" />
        <span class="ticket__shop">Hom Hom Grooming</span>
        <span class="ticket__kind">ใบจองคิว</span>
      </header>
      <div class="ticket__hero">
        <figure class="ticket__photo"><img class="ticket__pet" alt="รูปน้อง" /></figure>
        <div>
          <p class="ticket__pet-name" data-f="pet_name"></p>
          <p class="ticket__when-label">วันเวลานัด</p>
          <p class="ticket__when" data-f="slot_label"></p>
        </div>
      </div>
      <dl class="ticket__info">
        <dt>เจ้าของ</dt><dd data-f="owner"></dd>
        <dt>เบอร์โทร</dt><dd data-f="phone"></dd>
        <dt>เลขจอง</dt><dd data-f="id" class="ticket__id"></dd>
      </dl>
      <div class="ticket__foot">
        <p class="ticket__note">แสดงใบนี้ที่หน้าร้าน · ราคาจริงแจ้งหลังชั่งน้ำหนักน้องที่ร้าน</p>
      </div>
      <div class="ticket__actions"><button type="button" class="btn btn--small">บันทึกเป็นรูป</button></div>`;
    // สลิปไม่อยู่บนใบจอง (เก็บไว้ให้ร้านดูในหลังบ้านเท่านั้น)
    card.querySelector('[data-f="pet_name"]').textContent = b.pet_name;
    card.querySelector('[data-f="owner"]').textContent = `คุณ ${b.owner_name}`;
    card.querySelector('[data-f="phone"]').textContent = b.phone;
    card.querySelector('[data-f="slot_label"]').textContent = b.slot_label;
    card.querySelector('[data-f="id"]').textContent = b.id;
    if (b.pickup_time) {
      // ติ๊กรับ-ส่ง: บอกแค่เวลารับ (ที่อยู่อยู่เฉพาะหลังบ้าน) แทรกก่อนเลขจอง
      const dt = document.createElement("dt");
      dt.textContent = "รับ-ส่ง";
      const dd = document.createElement("dd");
      dd.textContent = `ร้านไปรับ ${b.pickup_time} น.`;
      card.querySelector('[data-f="id"]').previousElementSibling.before(dt, dd);
    }
    card.querySelector(".ticket__pet").src = b.pet_image;
    const actions = card.querySelector(".ticket__actions");
    const btn = actions.querySelector("button");
    btn.addEventListener("click", () => saveAsImage(card, b.id, btn));
    if (b.status === "cancelled") {
      markCancelled(card, "คิวนี้ถูกยกเลิกแล้ว");
    } else if (b.can_cancel) {
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn--ghost btn--small";
      cancelBtn.textContent = "ยกเลิกคิว";
      cancelBtn.addEventListener("click", () => openCancel(card, b, cancelBtn));
      actions.prepend(cancelBtn);
    } else if (b.cancel_note) {
      const note = document.createElement("p");
      note.className = "ticket__cancel-note";
      note.textContent = b.cancel_note;
      card.appendChild(note);
    }
    return card;
  }

  /* ---------------- ยกเลิกคิว (เฉพาะคิวที่จองจากแชทนี้) ---------------- */

  let bankList = null;

  async function loadBanks() {
    if (!bankList) {
      const r = await fetch("/api/v1/booking/cancel-options", { cache: "no-store" });
      bankList = (await r.json()).banks || [];
    }
    return bankList;
  }

  function markCancelled(card, text) {
    card.classList.add("ticket--cancelled");
    card.querySelector(".ticket__actions").remove();
    const box = card.querySelector(".cancel-box");
    if (box) box.remove();
    const note = document.createElement("p");
    note.className = "ticket__cancel-note";
    note.textContent = text;
    card.appendChild(note);
  }

  function openCancel(card, b, cancelBtn) {
    if (card.querySelector(".cancel-box")) return;
    cancelBtn.hidden = true;
    const box = document.createElement("form");
    box.className = "cancel-box";
    box.noValidate = true;
    box.innerHTML = `
      <p class="cancel-box__title">ยกเลิกคิวนี้?</p>
      <p class="cancel-box__lead">ช่องเวลาจะว่างให้คนอื่นจองทันที ร้านจะโอนคืน <b></b> เข้าบัญชีที่กรอกด้านล่าง</p>
      <div class="cancel-box__methods" role="radiogroup" aria-label="ช่องทางรับเงินคืน">
        <label><input type="radio" name="method" value="promptpay" checked /> พร้อมเพย์</label>
        <label><input type="radio" name="method" value="bank" /> บัญชีธนาคาร</label>
      </div>
      <label class="field" data-bank hidden>
        <span>ธนาคาร</span>
        <select name="bank"><option value="">เลือกธนาคาร</option></select>
      </label>
      <label class="field">
        <span data-account-label>เบอร์พร้อมเพย์ หรือเลขบัตรประชาชน</span>
        <input name="account" inputmode="numeric" maxlength="20" autocomplete="off" />
      </label>
      <label class="field">
        <span>ชื่อบัญชี</span>
        <input name="account_name" maxlength="40" autocomplete="name" />
      </label>
      <p class="field__error" role="alert"></p>
      <div class="cancel-box__actions">
        <button type="button" class="btn btn--ghost btn--small" data-keep>ไม่ยกเลิก</button>
        <button type="submit" class="btn btn--small btn--danger">ยืนยันยกเลิกคิว</button>
      </div>`;
    box.querySelector(".cancel-box__lead b").textContent = `${Number(b.refund_amount).toLocaleString("th-TH")} บาท`;
    box.elements.account_name.value = b.owner_name || "";
    const errEl = box.querySelector(".field__error");
    const bankField = box.querySelector("[data-bank]");
    const select = box.elements.bank;
    loadBanks().then((list) => list.forEach((name) => select.add(new Option(name, name)))).catch(() => {});

    box.addEventListener("change", (e) => {
      if (e.target.name !== "method") return;
      const isBank = e.target.value === "bank";
      bankField.hidden = !isBank;
      box.querySelector("[data-account-label]").textContent = isBank ? "เลขบัญชี" : "เบอร์พร้อมเพย์ หรือเลขบัตรประชาชน";
      errEl.textContent = "";
    });
    box.querySelector("[data-keep]").addEventListener("click", () => {
      box.remove();
      cancelBtn.hidden = false;
      cancelBtn.focus();
    });
    box.addEventListener("submit", async (e) => {
      e.preventDefault();
      const method = box.elements.method.value;
      const payload = {
        method,
        bank: method === "bank" ? select.value : null,
        account: box.elements.account.value.replace(/\D/g, ""),
        account_name: box.elements.account_name.value.trim(),
      };
      if (method === "bank" && !payload.bank) { errEl.textContent = "กรุณาเลือกธนาคาร"; return; }
      if (!payload.account) { errEl.textContent = "กรุณากรอกเลขบัญชีหรือพร้อมเพย์"; return; }
      if (!payload.account_name) { errEl.textContent = "กรุณากรอกชื่อบัญชี"; return; }
      const submit = box.querySelector("[type=submit]");
      submit.disabled = true;
      errEl.textContent = "";
      try {
        const r = await fetch(`/api/v1/booking/${encodeURIComponent(b.id)}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) {
          errEl.textContent = body.message || "ยกเลิกไม่สำเร็จ ลองใหม่อีกครั้งนะคะ";
          submit.disabled = false;
          return;
        }
        const amount = `${Number(body.refund_amount).toLocaleString("th-TH")} บาท`;
        markCancelled(card, `ยกเลิกแล้ว · ร้านจะโอนคืน ${amount}`);
        const chat = window.hhChat;
        if (chat) {
          chat.createAiBubble().textContent =
            `ยกเลิกคิวของน้อง${b.pet_name}เรียบร้อยค่ะ ร้านจะโอนคืน ${amount} เข้าบัญชีที่แจ้งไว้ ` +
            "ดูสถานะการโอนคืนได้ที่หน้าเช็คคิวนะคะ";
        }
      } catch (err) {
        console.error("[booking] cancel:", err);
        errEl.textContent = "ติดต่อร้านไม่ได้ เช็กอินเทอร์เน็ตแล้วลองอีกครั้งนะคะ";
        submit.disabled = false;
      }
    });
    card.appendChild(box);
    box.elements.account.focus({ preventScroll: true });
  }

  function showTicketInChat(b, intro) {
    const chat = window.hhChat;
    if (!chat) return;
    chat.ensureOpen(); // จองจากปุ่มบนหน้าแรกตอนแชทปิดอยู่ ก็ยังเห็นใบจอง
    if (intro) chat.createAiBubble().textContent = intro;
    chat.appendAiNode(ticketCard(b));
  }

  async function showMyBookings({ forCancel = false } = {}) {
    const chat = window.hhChat;
    if (!chat) return;
    chat.ensureOpen();
    try {
      const r = await fetch("/api/v1/booking/mine", { cache: "no-store" });
      const body = await r.json();
      // ใบที่ยกเลิกแล้วไม่ต้องโชว์ซ้ำ · โหมดยกเลิกโชว์เฉพาะคิวที่ยังไม่ถึงวันนัด
      const list = (body.bookings || []).filter((b) =>
        forCancel ? b.can_cancel || b.cancel_note : b.status !== "cancelled");
      if (forCancel) {
        if (!list.length) {
          chat.createAiBubble().textContent =
            "ไม่พบคิวที่ยกเลิกได้ในแชทนี้ค่ะ ถ้าจองจากเครื่องอื่นหรือเหลือไม่ถึง 3 ชั่วโมงก่อนนัด " +
            "รบกวนติดต่อร้านทาง LINE หรือโทรได้เลยนะคะ";
          return;
        }
        chat.createAiBubble().textContent = "เลือกคิวที่ต้องการยกเลิก แล้วกดปุ่ม “ยกเลิกคิว” ใต้ใบจองได้เลยค่ะ";
        list.slice(0, 5).forEach((b) => chat.appendAiNode(ticketCard(b)));
        return;
      }
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

  // ลูกค้าพิมพ์ "ยกเลิก…" → ปุ่มเปิดใบจองที่ยกเลิกได้ใต้คำตอบของบอท
  function addCancelCta(bubble) {
    const wrap = bubble && bubble.parentElement;
    if (!wrap || wrap.querySelector(".book-cta")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn--small btn--ghost book-cta";
    btn.dataset.cancelBooking = "";
    btn.textContent = "ยกเลิกคิว";
    wrap.appendChild(btn);
  }

  window.hhBooking = {
    open,
    addCta,
    // เรียกจาก chat.js หลังบอทตอบ — ลูกค้าพูดถึงการจอง/นัด/คิว ก็ต่อปุ่มจองให้เลย (ไม่ใช้ LLM ตัดสิน)
    maybeAddCta(userText, bubble) {
      if (CANCEL_WORDS.test(userText || "")) addCancelCta(bubble);
      else if (BOOK_WORDS.test(userText || "")) addCta(bubble);
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

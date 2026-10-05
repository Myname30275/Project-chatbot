/* หลังบ้านเจ้าของร้าน: ตารางคิวรายสัปดาห์ / ปฏิทินรายเดือน / แผงรายละเอียด + เปลี่ยนสถานะ
 *
 * วันที่ทั้งหมดจัดการเป็นสตริง YYYY-MM-DD แล้วคำนวณผ่าน Date แบบ UTC — กันวันเลื่อนตาม timezone
 * ของเครื่องที่เปิด (เวลานัดจริงเป็นเวลาไทยอยู่ใน key ของช่องเวลาแล้ว เช่น 2026-10-03T10:00)
 */
(function () {
  "use strict";

  const board = document.getElementById("board");
  const rangeLabel = document.getElementById("range-label");
  const summaryEl = document.getElementById("summary");
  const msgEl = document.getElementById("admin-msg");
  const drawer = document.getElementById("drawer");
  const drawerBody = document.getElementById("drawer-body");
  const searchForm = document.getElementById("search");
  const searchInput = document.getElementById("search-id");

  const WD = ["อา.", "จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส."];
  const MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"];
  const MON_SHORT = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
  const ACTION = {
    confirmed: { label: "ยืนยันคิว", cls: "" },
    done: { label: "มาใช้บริการแล้ว", cls: "btn--ghost" },
    cancelled: { label: "ยกเลิกคิว", cls: "btn--danger", ask: "ยกเลิกคิวนี้? ช่องเวลาจะว่างให้ลูกค้าคนอื่นจองได้ทันที" },
  };
  const refundPending = (b) => !!(b.refund && b.refund.status === "pending");
  // ยกเลิกก่อนร้านยืนยันยอดมัดจำ — เงินอาจไม่เคยเข้าจริง (สลิปแก้ชื่อ/สลิปปลอม) ต้องตรวจบัญชีก่อนโอนคืน
  const refundUnverified = (b) => refundPending(b) && !b.refund.payment_verified;

  let view = "week";
  let anchor = null; // YYYY-MM-DD วันที่อ้างอิงของหน้าที่แสดง
  let data = null; // ผลล่าสุดจาก API
  let openId = null; // การจองที่เปิดในแผงรายละเอียด
  let lastTrigger = null;

  /* ---------------- วันที่ ---------------- */

  const toDate = (s) => new Date(s + "T00:00:00Z");
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (s, n) => { const d = toDate(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const weekday = (s) => toDate(s).getUTCDay(); // 0 = อาทิตย์
  const mondayOf = (s) => addDays(s, -((weekday(s) + 6) % 7));
  const shortLabel = (s) => { const d = toDate(s); return `${d.getUTCDate()} ${MON_SHORT[d.getUTCMonth()]}`; };
  const pyWeekday = (s) => (weekday(s) + 6) % 7; // แบบ Python: 0 = จันทร์ (ตรงกับ closed_weekdays)

  function range() {
    if (view === "week") {
      const start = mondayOf(anchor);
      return [start, addDays(start, 7)];
    }
    const d = toDate(anchor);
    const first = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)));
    const next = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)));
    const start = mondayOf(first);
    const end = addDays(mondayOf(addDays(next, -1)), 7);
    return [start, end];
  }

  /* ---------------- โหลดข้อมูล ---------------- */

  async function load({ quiet = false } = {}) {
    const [start, end] = anchor ? range() : ["", ""];
    const qs = anchor ? `?start=${start}&end=${end}` : "";
    if (!quiet) msgEl.textContent = "กำลังโหลด…";
    try {
      const r = await fetch(`/api/v1/admin/bookings${qs}`, { cache: "no-store" });
      if (r.status === 401) { location.reload(); return; }
      const body = await r.json();
      if (!r.ok) throw new Error(body.message || r.status);
      if (!anchor) { anchor = body.today; return load(); }
      data = body;
      msgEl.textContent = "";
      render();
    } catch (err) {
      console.error("[admin] load:", err);
      msgEl.textContent = "โหลดตารางคิวไม่สำเร็จ ตรวจอินเทอร์เน็ตแล้วกด “วันนี้” อีกครั้ง";
    }
  }

  function byDay() {
    const map = {};
    for (const b of data.bookings) (map[b.slot.slice(0, 10)] ||= []).push(b);
    return map;
  }

  function times() {
    const [oh, om] = data.hours.open.split(":").map(Number);
    const [lh, lm] = data.hours.last_start.split(":").map(Number);
    const out = [];
    for (let m = oh * 60 + om; m <= lh * 60 + lm; m += data.hours.slot_minutes) {
      out.push(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`);
    }
    return out;
  }

  /* ---------------- วาด ---------------- */

  function render() {
    const [start, end] = range();
    if (view === "week") {
      const last = addDays(end, -1);
      rangeLabel.textContent = `${shortLabel(start)} – ${shortLabel(last)} ${toDate(last).getUTCFullYear() + 543}`;
      renderWeek(start);
    } else {
      const d = toDate(anchor);
      rangeLabel.textContent = `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear() + 543}`;
      renderMonth(start, end);
    }
    renderSummary();
    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  }

  function renderSummary() {
    const inView = view === "month"
      ? data.bookings.filter((b) => b.slot.slice(0, 7) === anchor.slice(0, 7))
      : data.bookings;
    const n = (s) => inView.filter((b) => b.status === s).length;
    const items = [
      ["คิวทั้งหมด", inView.filter((b) => b.status !== "cancelled").length, ""],
      ["รอยืนยัน", n("pending"), "pending"],
      ["ยืนยันแล้ว", n("confirmed"), "confirmed"],
      ["มาแล้ว", n("done"), "done"],
      ["ยกเลิก", n("cancelled"), "cancelled"],
      ["รอโอนคืน", inView.filter(refundPending).length, "refund"],
      ["รอตรวจยอดก่อนคืน", inView.filter(refundUnverified).length, "refund-check"],
    ];
    summaryEl.innerHTML = "";
    for (const [label, count, status] of items) {
      const li = document.createElement("li");
      li.dataset.status = status;
      li.innerHTML = "<b></b><span></span>";
      li.querySelector("b").textContent = count;
      li.querySelector("span").textContent = label;
      summaryEl.appendChild(li);
    }
  }

  function chip(b) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bk-chip";
    btn.dataset.status = b.status;
    btn.dataset.id = b.id;
    const flag = (b.status === "pending" && b.slip && b.slip.auto_ok === false ? " ⚠" : "") +
      (b.pickup ? " 🚗" : "") + (refundUnverified(b) ? " 💸⚠" : refundPending(b) ? " 💸" : "");
    btn.innerHTML = '<span class="bk-chip__name"></span><span class="bk-chip__meta"></span>';
    btn.querySelector(".bk-chip__name").textContent = b.pet_name + (b.pets > 1 ? ` ×${b.pets}` : "") + flag;
    btn.querySelector(".bk-chip__meta").textContent = b.status_label;
    btn.title = `${b.id} · ${b.owner_name} · ${b.status_label}${flag ? " · ต้องตรวจสลิปเอง" : ""}`;
    return btn;
  }

  function renderWeek(start) {
    const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
    const map = byDay();
    const table = document.createElement("table");
    table.className = "week";
    const head = table.createTHead().insertRow();
    head.appendChild(document.createElement("th"));
    for (const d of days) {
      const th = document.createElement("th");
      th.scope = "col";
      const active = (map[d] || []).filter((b) => b.status !== "cancelled").length;
      const closed = data.closed_weekdays.includes(pyWeekday(d));
      th.className = [d === data.today ? "is-today" : "", closed ? "is-closed" : ""].join(" ");
      th.innerHTML = '<span class="week__wd"></span><span class="week__date"></span><span class="week__count"></span>';
      th.querySelector(".week__wd").textContent = WD[weekday(d)];
      th.querySelector(".week__date").textContent = shortLabel(d);
      th.querySelector(".week__count").textContent = closed ? "ร้านปิด" : `${active} คิว`;
      head.appendChild(th);
    }
    const body = table.createTBody();
    for (const t of times()) {
      const row = body.insertRow();
      const th = document.createElement("th");
      th.scope = "row";
      th.textContent = t;
      row.appendChild(th);
      for (const d of days) {
        const cell = row.insertCell();
        if (data.closed_weekdays.includes(pyWeekday(d))) { cell.className = "is-closed"; continue; }
        if (d < data.today) cell.classList.add("is-past");
        const here = (map[d] || []).filter((b) => b.slot.slice(11) === t);
        // คิวที่ยังนับอยู่ขึ้นก่อน คิวที่ยกเลิกแล้วต่อท้าย (จางลง)
        here.sort((a, b) => (a.status === "cancelled") - (b.status === "cancelled"));
        here.forEach((b) => cell.appendChild(chip(b)));
        // จองหลายตัวที่กินชั่วโมงถัดไป: แสดงชิป "ต่อ" ในชั่วโมงนั้นด้วย (กดเปิดรายละเอียดเดียวกัน)
        const key = `${d}T${t}`;
        (map[d] || []).forEach((b) => {
          if (b.status === "cancelled" || b.slot === key) return;
          if ((b.slots_used || []).some(([k]) => k === key)) {
            const c = chip(b);
            c.classList.add("bk-chip--cont");
            c.querySelector(".bk-chip__meta").textContent = `ต่อจาก ${b.slot.slice(11)}`;
            cell.appendChild(c);
          }
        });
        // ช่องเต็ม = จำนวนช่างที่ถูกใช้ในชั่วโมงนี้ครบ (นับตามจำนวนน้อง ไม่ใช่จำนวนการจอง)
        const used = (map[d] || []).filter((b) => b.status !== "cancelled").reduce((sum, b) =>
          sum + (b.slots_used || [[b.slot, 1]]).filter(([k]) => k === key).reduce((x, [, u]) => x + u, 0), 0);
        if (used >= data.capacity) cell.classList.add("is-full");
      }
    }
    board.innerHTML = "";
    board.appendChild(table);
    // จอแคบ (ตารางเลื่อนแนวนอน): เลื่อนให้เห็นคอลัมน์วันนี้ก่อน ไม่ต้องปัดผ่านวันจันทร์ที่ร้านปิด
    const todayTh = table.querySelector("thead th.is-today");
    const timeCol = table.querySelector("thead th");
    board.scrollLeft = todayTh ? Math.max(0, todayTh.offsetLeft - timeCol.offsetWidth) : 0;
  }

  function renderMonth(start, end) {
    const map = byDay();
    const month = anchor.slice(0, 7);
    const grid = document.createElement("div");
    grid.className = "month";
    ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."].forEach((w) => {
      const h = document.createElement("div");
      h.className = "month__wd";
      h.textContent = w;
      grid.appendChild(h);
    });
    for (let d = start; d < end; d = addDays(d, 1)) {
      const list = map[d] || [];
      const active = list.filter((b) => b.status !== "cancelled");
      const pending = list.filter((b) => b.status === "pending").length;
      const closed = data.closed_weekdays.includes(pyWeekday(d));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "month__day";
      if (d.slice(0, 7) !== month) btn.classList.add("is-other");
      if (d === data.today) btn.classList.add("is-today");
      if (closed) btn.classList.add("is-closed");
      btn.dataset.date = d;
      btn.innerHTML = '<span class="month__num"></span><span class="month__count"></span><span class="month__pending"></span>';
      btn.querySelector(".month__num").textContent = toDate(d).getUTCDate();
      btn.querySelector(".month__count").textContent = closed ? "ปิด" : active.length ? `${active.length} คิว` : "";
      btn.querySelector(".month__pending").textContent = pending ? `รอยืนยัน ${pending}` : "";
      btn.setAttribute("aria-label", `${d} ${active.length} คิว${pending ? ` รอยืนยัน ${pending}` : ""}`);
      grid.appendChild(btn);
    }
    board.innerHTML = "";
    board.appendChild(grid);
  }

  /* ---------------- แผงรายละเอียด ---------------- */

  function row(label, value, cls) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    if (value instanceof Node) dd.appendChild(value);
    else dd.textContent = value;
    if (cls) dd.className = cls;
    return [dt, dd];
  }

  function baht(n) {
    return `${Number(n).toLocaleString("th-TH")} บาท`;
  }

  function slipText(s, due) {
    if (!s || s.auto_ok === undefined) return "—";
    if (s.auto_ok) return `✓ ยอด ${baht(due)} และชื่อบัญชีตรงกับร้าน (ตรวจอัตโนมัติ)`;
    const bits = ["⚠ ระบบตรวจอัตโนมัติไม่ครบ — ตรวจยอดเข้าบัญชีเอง"];
    if (s.amount != null) bits.push(`ยอดที่อ่านได้ ${baht(s.amount)} (ต้องได้ ${baht(due)})`);
    if (s.receiver_ok == null) bits.push("อ่านชื่อผู้รับไม่ได้");
    return bits.join(" · ");
  }

  // รับ-ส่งน้อง: เวลารับ ที่อยู่ ระยะทาง + ลิงก์เปิด Google Maps นำทางไปหมุดที่ลูกค้าปัก
  function pickupRows(b) {
    const p = b.pickup;
    if (!p) return [row("รับ-ส่ง", "ไม่ใช้ (มาที่ร้านเอง)")];
    const nav = document.createElement("a");
    nav.href = `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lng}`;
    nav.target = "_blank";
    nav.rel = "noopener";
    nav.textContent = `เปิดแผนที่ (~${p.km} กม.)`;
    const addr = document.createElement("span");
    addr.className = "pre";
    addr.textContent = p.address;
    return [row("รับ-ส่ง", `รับที่บ้าน ${p.time} น. · ไป-กลับ`), row("ที่อยู่รับ", addr), row("หมุด", nav)];
  }

  // ลูกค้ายกเลิกเองในแชท → ช่องทางที่ให้ร้านโอนคืน
  function refundRows(b) {
    const r = b.refund;
    if (!r) return b.status === "cancelled" ? [row("ยกเลิกโดย", "ร้าน")] : [];
    const where = r.method === "bank" ? `บัญชี${r.bank} ${r.account}` : `พร้อมเพย์ ${r.account}`;
    const state = r.status === "done"
      ? `✓ โอนคืนแล้ว ${baht(r.amount)} (${(r.refunded_at || "").replace("T", " ").slice(0, 16)})`
      : r.status === "rejected" ? "✕ ไม่คืนเงิน — ตรวจบัญชีแล้วไม่พบยอดมัดจำของคิวนี้"
      : r.payment_verified ? `💸 รอโอนคืน ${baht(r.amount)}`
      : `⚠ รอตรวจยอดก่อนโอนคืน ${baht(r.amount)}`;
    const paid = r.payment_verified ? "✓ ร้านยืนยันยอดเข้าบัญชีแล้ว"
      : r.status === "rejected" ? "✕ ไม่พบยอดเข้าบัญชี"
      : "⚠ ยังไม่เคยยืนยันยอด — ลูกค้ายกเลิกก่อนร้านตรวจ สลิปอาจถูกแก้ไข ตรวจบัญชีก่อนโอนคืน";
    return [
      row("ยกเลิกโดย", `ลูกค้า (${(r.requested_at || "").replace("T", " ").slice(0, 16)})`),
      row("คืนเงิน", state),
      row("ยอดมัดจำ", paid),
      row("โอนคืนเข้า", where, "mono"),
      row("ชื่อบัญชี", r.account_name),
      // กันสวมรอย: โอนคืนเข้าบัญชีชื่อเดียวกับผู้โอนมัดจำเท่านั้น
      row("ผู้โอนมัดจำ", r.payer_name || "อ่านจากสลิปไม่ได้ — เทียบชื่อกับรูปสลิปเอง"),
      row("ตรวจชื่อ", r.payer_match === true ? "✓ ชื่อบัญชีตรงกับผู้โอนมัดจำ"
        : r.payer_match === false ? "⚠ ชื่อไม่ตรงกับผู้โอนมัดจำ — อย่าเพิ่งโอนคืน โทรยืนยันกับลูกค้าก่อน"
        : "? ตรวจอัตโนมัติไม่ได้ — ดูชื่อผู้โอนในรูปสลิป"),
    ];
  }

  /* ---------------- ยืนยันโอนคืน: ต้องแนบสลิปโอนคืนก่อน ---------------- */

  // ย่อรูปในเบราว์เซอร์ก่อนส่ง (เหมือนหน้าจองคิว) — สลิปย่อน้อยให้ตัวหนังสือยังอ่านออก
  async function shrink(file, maxSide = 1200) {
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
      console.warn("[admin] ย่อรูปไม่สำเร็จ ใช้ไฟล์เดิม:", err);
      return file;
    }
  }

  function refundBox(b) {
    const box = document.createElement("div");
    box.className = "refund-proof";
    box.innerHTML = `
      <p class="refund-proof__title">ยืนยันโอนคืน <b></b></p>
      <div class="refund-proof__warn" data-unverified hidden>
        <p><strong>คิวนี้ถูกยกเลิกก่อนร้านยืนยันยอดมัดจำ</strong> — ระบบอ่านสลิปจากรูปเท่านั้น สลิปที่ถูกแก้ชื่อผู้รับหรือยอดเงินอาจผ่านได้
          เปิดบัญชีร้านตรวจว่ามียอดนี้เข้าจริงก่อนโอนคืน</p>
        <label><input type="checkbox" data-checked /> ตรวจบัญชีแล้ว มียอดมัดจำของคิวนี้เข้าจริง</label>
        <button type="button" class="btn btn--small btn--danger" data-reject>ไม่พบยอดเงินเข้า (ไม่คืนเงิน)</button>
      </div>
      <p class="refund-proof__hint">แนบสลิปที่โอนคืนให้ลูกค้าก่อน ลูกค้าดูสลิปนี้ได้ที่หน้าเช็คคิว (หลังยืนยันตัวตน)</p>
      <img class="refund-proof__img" alt="สลิปโอนคืนที่แนบ" hidden />
      <input type="file" accept="image/jpeg,image/png,image/webp" hidden />
      <div class="refund-proof__actions">
        <button type="button" class="btn btn--ghost btn--small" data-pick>แนบสลิปโอนคืน</button>
        <button type="button" class="btn btn--small" data-confirm disabled>ยืนยันโอนคืนแล้ว</button>
      </div>`;
    box.querySelector("b").textContent = baht(b.refund.amount);
    const input = box.querySelector('input[type="file"]');
    const img = box.querySelector("img");
    const pickBtn = box.querySelector("[data-pick]");
    const confirmBtn = box.querySelector("[data-confirm]");
    const checked = box.querySelector("[data-checked]");
    const unverified = !b.refund.payment_verified;
    box.querySelector("[data-unverified]").hidden = !unverified;
    let blob = null;
    // ยืนยันโอนคืนได้เมื่อแนบสลิปแล้ว และ (ถ้ายอดยังไม่เคยถูกยืนยัน) ติ๊กว่าตรวจบัญชีแล้ว
    const ready = () => !!blob && (!unverified || checked.checked);
    checked.addEventListener("change", () => { confirmBtn.disabled = !ready(); });
    box.querySelector("[data-reject]").addEventListener("click", () =>
      save(b, "refund-rejected", null,
        "ยืนยันว่าตรวจบัญชีแล้วไม่พบยอดมัดจำของคิวนี้? ระบบจะไม่คืนเงิน และแจ้งลูกค้าให้ติดต่อร้าน",
        "บันทึกแล้ว: ไม่พบยอดเงินเข้า ไม่คืนเงิน"));

    pickBtn.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
      const file = input.files[0];
      input.value = "";
      if (!file) return;
      blob = await shrink(file);
      if (img.src) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(blob);
      img.hidden = false;
      pickBtn.textContent = "เปลี่ยนสลิป";
      confirmBtn.disabled = !ready();
    });
    confirmBtn.addEventListener("click", async () => {
      if (!ready()) return;
      if (!window.confirm(`ยืนยันว่าโอนคืน ${baht(b.refund.amount)} ให้ลูกค้าแล้ว?`)) return;
      const note = drawerBody.querySelector(".drawer__msg");
      drawerBody.querySelectorAll(".drawer__actions button").forEach((x) => (x.disabled = true));
      note.textContent = "กำลังบันทึก…";
      const upload = new FormData();
      upload.append("proof", blob, "refund.jpg");
      if (unverified) upload.append("payment_checked", "1");
      try {
        const r = await fetch(`/api/v1/admin/bookings/${encodeURIComponent(b.id)}/refunded`, { method: "POST", body: upload });
        if (r.status === 401) { location.reload(); return; }
        const body = await r.json();
        if (!r.ok) throw new Error(body.message || "บันทึกไม่สำเร็จ");
        replaceBooking(body.booking);
        drawerBody.querySelector(".drawer__msg").textContent = "บันทึกแล้ว: โอนคืนแล้ว (แนบสลิปแล้ว)";
      } catch (err) {
        note.textContent = err.message || "บันทึกไม่สำเร็จ ลองอีกครั้ง";
        drawerBody.querySelectorAll(".drawer__actions button").forEach((x) => (x.disabled = false));
        confirmBtn.disabled = !ready();
      }
    });
    return box;
  }

  function replaceBooking(updated) {
    const i = data.bookings.findIndex((x) => x.id === updated.id);
    if (i >= 0) data.bookings[i] = updated;
    render();
    openDrawer(updated, lastTrigger);
  }

  function openDrawer(b, trigger) {
    openId = b.id;
    lastTrigger = trigger || document.activeElement;
    drawerBody.innerHTML = "";

    const photos = document.createElement("div");
    photos.className = "drawer__photos";
    const kinds = [["pet", "รูปน้อง"], ["slip", "สลิปมัดจำ"]];
    if (b.refund && b.refund.proof) kinds.push(["refund", "สลิปโอนคืน"]);
    for (const [kind, label] of kinds) {
      const a = document.createElement("a");
      a.href = `/api/v1/admin/bookings/${encodeURIComponent(b.id)}/image/${kind}`;
      a.target = "_blank";
      a.rel = "noopener";
      const img = document.createElement("img");
      img.src = a.href;
      img.alt = label;
      const cap = document.createElement("span");
      cap.textContent = label;
      a.append(img, cap);
      photos.appendChild(a);
    }

    const status = document.createElement("p");
    status.className = "drawer__status";
    status.dataset.status = b.status;
    status.textContent = b.status_label;

    const tel = document.createElement("a");
    tel.href = `tel:${b.phone}`;
    tel.textContent = b.phone.replace(/(\d{3})(\d{3})(\d{4})/, "$1-$2-$3");

    const dl = document.createElement("dl");
    dl.className = "drawer__info";
    [
      row("เลขจอง", b.id, "mono"),
      row("วันเวลา", b.slot_label),
      ...(b.service_label ? [row("บริการ", b.service_label)] : []),
      row("น้อง", b.pet_name + (b.pets > 1 ? ` (${b.pets} ตัว)` : "")),
      row("เจ้าของ", b.owner_name),
      row("เบอร์โทร", tel),
      ...pickupRows(b),
      row("ยอดที่ต้องโอน", baht(b.amount_due) + (b.pets > 1 || b.pickup
        ? ` (มัดจำ${b.pets > 1 ? ` × ${b.pets} ตัว` : ""}${b.pickup ? ` + ค่ารับส่ง ${baht(b.pickup.fee)}` : ""})` : "")),
      row("สลิป", slipText(b.slip, b.amount_due)),
      row("เลขอ้างอิงสลิป", (b.slip && b.slip.reference) || "—", "mono"),
      row("จองเมื่อ", (b.created_at || "").replace("T", " ").slice(0, 16)),
      ...refundRows(b),
    ].forEach(([dt, dd]) => dl.append(dt, dd));

    const actions = document.createElement("div");
    actions.className = "drawer__actions";
    (b.next_status || []).forEach((s) => {
      const conf = ACTION[s];
      if (!conf) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn btn--small ${conf.cls}`.trim();
      btn.textContent = conf.label;
      btn.addEventListener("click", () => changeStatus(b, s, btn));
      actions.appendChild(btn);
    });
    if (refundPending(b)) actions.appendChild(refundBox(b));
    if (!actions.children.length) {
      const p = document.createElement("p");
      p.className = "drawer__done";
      p.textContent = "คิวนี้ปิดแล้ว ไม่มีอะไรต้องทำเพิ่ม";
      actions.appendChild(p);
    }
    const note = document.createElement("p");
    note.className = "drawer__msg";
    note.setAttribute("role", "status");

    drawerBody.append(status, photos, dl, actions, note);
    drawer.hidden = false;
    document.body.classList.add("sheet-open");
    drawer.querySelector("[data-close-drawer].icon-btn").focus();
  }

  function closeDrawer() {
    drawer.hidden = true;
    openId = null;
    document.body.classList.remove("sheet-open");
    if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
  }

  function changeStatus(b, status) {
    const conf = ACTION[status];
    return save(b, "status", { status }, conf.ask, null);
  }

  async function save(b, action, payload, ask, doneText) {
    if (ask && !window.confirm(ask)) return;
    const note = drawerBody.querySelector(".drawer__msg");
    drawerBody.querySelectorAll(".drawer__actions button").forEach((x) => (x.disabled = true));
    note.textContent = "กำลังบันทึก…";
    try {
      const r = await fetch(`/api/v1/admin/bookings/${encodeURIComponent(b.id)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      if (r.status === 401) { location.reload(); return; }
      const body = await r.json();
      if (!r.ok) throw new Error(body.message || "บันทึกไม่สำเร็จ");
      const i = data.bookings.findIndex((x) => x.id === b.id);
      if (i >= 0) data.bookings[i] = body.booking;
      render();
      openDrawer(body.booking, lastTrigger);
      drawerBody.querySelector(".drawer__msg").textContent = doneText || `บันทึกแล้ว: ${body.booking.status_label}`;
    } catch (err) {
      note.textContent = err.message || "บันทึกไม่สำเร็จ ลองอีกครั้ง";
      drawerBody.querySelectorAll(".drawer__actions button").forEach((x) => (x.disabled = false));
    }
  }

  /* ---------------- เหตุการณ์ ---------------- */

  document.addEventListener("click", (e) => {
    const chipEl = e.target.closest(".bk-chip");
    if (chipEl) {
      const b = data.bookings.find((x) => x.id === chipEl.dataset.id);
      if (b) openDrawer(b, chipEl);
      return;
    }
    const day = e.target.closest(".month__day");
    if (day) { view = "week"; anchor = day.dataset.date; load(); return; }
    if (e.target.closest("[data-close-drawer]")) { closeDrawer(); return; }
    const v = e.target.closest("[data-view]");
    if (v && v.dataset.view !== view) { view = v.dataset.view; load(); return; }
    const nav = e.target.closest("[data-nav]");
    if (nav && data) {
      const step = Number(nav.dataset.nav);
      if (step === 0) anchor = data.today;
      else if (view === "week") anchor = addDays(anchor, 7 * step);
      else {
        const d = toDate(anchor);
        anchor = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + step, 1)));
      }
      load();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !drawer.hidden) closeDrawer();
  });

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = searchInput.value.trim().toUpperCase();
    if (!id) return;
    msgEl.textContent = "กำลังค้นหา…";
    try {
      const r = await fetch(`/api/v1/admin/bookings/${encodeURIComponent(id)}`, { cache: "no-store" });
      if (r.status === 401) { location.reload(); return; }
      const body = await r.json();
      if (!r.ok) { msgEl.textContent = body.message || "ไม่พบเลขจองนี้"; return; }
      view = "week";
      anchor = body.booking.slot.slice(0, 10);
      await load({ quiet: true });
      openDrawer(body.booking, searchInput);
    } catch (err) {
      msgEl.textContent = "ค้นหาไม่สำเร็จ ลองอีกครั้ง";
    }
  });

  // คิวใหม่เข้ามาระหว่างเปิดหน้าไว้ — รีเฟรชทุก 60 วินาทีเมื่อแท็บนี้เปิดอยู่และไม่ได้ดูรายละเอียดคิวไหนอยู่
  setInterval(() => {
    if (document.visibilityState === "visible" && drawer.hidden && anchor) load({ quiet: true });
  }, 60000);

  load();
})();

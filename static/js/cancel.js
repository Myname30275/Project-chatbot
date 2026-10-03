/* ยกเลิกคิว: ป๊อปอัป 2 ขั้น — ยืนยันตัวตน → ช่องทางรับเงินคืน → POST /api/v1/booking/cancel
 *
 * ไม่ผูกกับประวัติแชท (ยกเลิกจากเครื่องไหนก็ได้) แต่ต้องกรอกเลขจอง + เบอร์โทร + ชื่อเจ้าของให้ตรงกับใบจอง
 * กันสวมรอยเอาเงินคืน: ผิดครบ 5 ครั้งล็อก 24 ชม. และร้านโอนคืนเข้าบัญชีชื่อเดียวกับผู้โอนมัดจำเท่านั้น
 * เปิดได้จาก: ปุ่มลัด/ปุ่มใต้คำตอบในแชท (data-cancel-booking), ปุ่มใต้ใบจอง, หน้าเช็คคิว (/?cancel=1)
 */
(function () {
  "use strict";

  const sheet = document.getElementById("cancel-sheet");
  if (!sheet) return;
  const verifyForm = document.getElementById("cancel-verify");
  const refundForm = document.getElementById("cancel-refund");
  const doneEl = document.getElementById("cancel-done");
  const summaryEl = document.getElementById("cancel-summary");
  const refundFields = document.getElementById("cancel-refund-fields");
  const bankField = refundForm.querySelector("[data-bank]");
  const accountLabel = refundForm.querySelector("[data-account-label]");
  const PHONE_RE = /^0\d{9}$/;

  let who = null; // { booking_id, phone, owner_name } ที่ยืนยันผ่านแล้ว — ส่งซ้ำตอนยกเลิกจริง
  let banksLoaded = false;
  let lastTrigger = null;
  let busy = false;

  /* ---------------- ทั่วไป ---------------- */

  function show(step) {
    verifyForm.hidden = step !== "verify";
    refundForm.hidden = step !== "refund";
    doneEl.hidden = step !== "done";
    const panel = sheet.querySelector(".sheet__panel");
    if (panel) panel.scrollTop = 0;
  }

  function setError(form, field, message) {
    const el = form.querySelector(`[data-error-for="${field}"]`);
    if (el) el.textContent = message;
    else form.querySelector("[data-status]").textContent = message;
    const input = form.elements[field];
    if (input && input.setAttribute) input.setAttribute("aria-invalid", "true");
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-error-for], [data-status]").forEach((el) => (el.textContent = ""));
    form.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
  }

  function setBusy(form, on) {
    busy = on;
    form.querySelectorAll("button").forEach((b) => (b.disabled = on));
  }

  async function post(url, payload) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { ok: r.ok, body: await r.json().catch(() => ({})) };
  }

  const baht = (n) => `${Number(n).toLocaleString("th-TH")} บาท`;

  /* ---------------- ขั้น 1: ยืนยันตัวตน ---------------- */

  verifyForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    clearErrors(verifyForm);
    const payload = {
      booking_id: verifyForm.elements.booking_id.value.trim().toUpperCase(),
      phone: verifyForm.elements.phone.value.replace(/\D/g, ""),
      owner_name: verifyForm.elements.owner_name.value.replace(/\s+/g, " ").trim(),
    };
    let ok = true;
    if (!payload.booking_id) { setError(verifyForm, "booking_id", "กรุณากรอกเลขจอง (อยู่บนใบจอง เช่น HH-1004-01)"); ok = false; }
    if (!PHONE_RE.test(payload.phone)) { setError(verifyForm, "phone", "เบอร์โทรต้องเป็นตัวเลข 10 หลัก ขึ้นต้นด้วย 0"); ok = false; }
    if (!payload.owner_name) { setError(verifyForm, "owner_name", "กรุณากรอกชื่อเจ้าของตามที่กรอกตอนจอง"); ok = false; }
    if (!ok) return;

    setBusy(verifyForm, true);
    verifyForm.querySelector("[data-status]").textContent = "กำลังตรวจสอบ…";
    try {
      const { ok: passed, body } = await post("/api/v1/booking/cancel/verify", payload);
      verifyForm.querySelector("[data-status]").textContent = "";
      if (!passed) {
        setError(verifyForm, body.field || "_", body.message || "ตรวจสอบไม่สำเร็จ ลองใหม่อีกครั้งนะคะ");
        return;
      }
      who = payload;
      renderRefundStep(body.booking);
    } catch (err) {
      console.error("[cancel] verify:", err);
      verifyForm.querySelector("[data-status]").textContent = "ติดต่อร้านไม่ได้ เช็กอินเทอร์เน็ตแล้วลองอีกครั้งนะคะ";
    } finally {
      setBusy(verifyForm, false);
    }
  });

  /* ---------------- ขั้น 2: ช่องทางรับเงินคืน ---------------- */

  function renderRefundStep(b) {
    clearErrors(refundForm);
    summaryEl.innerHTML = "";
    const rows = [
      ["เลขจอง", b.id],
      ["น้อง", b.pet_name],
      ["วันเวลานัด", b.slot_label],
      ["สถานะ", b.status_label],
    ];
    if (b.pickup_time) rows.push(["รับ-ส่ง", `ร้านไปรับ ${b.pickup_time} น.`]);
    for (const [label, value] of rows) {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      summaryEl.append(dt, dd);
    }

    const submit = refundForm.querySelector("[type=submit]");
    const note = refundForm.querySelector("[data-cancel-note]");
    if (!b.can_cancel) {
      // ยืนยันตัวตนผ่าน แต่คิวนี้ยกเลิกออนไลน์ไม่ได้แล้ว (ยกเลิกไปแล้ว / เลยกำหนด / ผ่านวันนัด)
      refundFields.hidden = true;
      submit.hidden = true;
      note.hidden = false;
      note.textContent = b.status === "cancelled"
        ? "คิวนี้ถูกยกเลิกไปแล้ว ดูสถานะการโอนคืนได้ที่หน้าเช็คคิวค่ะ"
        : b.cancel_note || "คิวนี้ยกเลิกออนไลน์ไม่ได้แล้ว ติดต่อร้านทาง LINE หรือโทรได้เลยค่ะ";
    } else {
      refundFields.hidden = false;
      submit.hidden = false;
      note.hidden = true;
      refundForm.querySelector("[data-amount]").textContent = baht(b.refund_amount);
      // ไม่เติมชื่อให้ — ต้องเป็นชื่อเจ้าของบัญชีที่โอนมัดจำ ซึ่งอาจไม่ใช่ชื่อที่กรอกตอนจอง
      loadBanks();
    }
    show("refund");
  }

  async function loadBanks() {
    if (banksLoaded) return;
    try {
      const r = await fetch("/api/v1/booking/cancel-options", { cache: "no-store" });
      const body = await r.json();
      (body.banks || []).forEach((name) => refundForm.elements.bank.add(new Option(name, name)));
      banksLoaded = true;
    } catch (err) {
      console.error("[cancel] banks:", err);
    }
  }

  refundForm.addEventListener("change", (e) => {
    if (e.target.name !== "method") return;
    const isBank = e.target.value === "bank";
    bankField.hidden = !isBank;
    accountLabel.textContent = isBank ? "เลขบัญชี" : "เบอร์พร้อมเพย์ หรือเลขบัตรประชาชน";
    clearErrors(refundForm);
  });

  refundForm.querySelector("[data-back]").addEventListener("click", () => show("verify"));

  refundForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy || !who) return;
    clearErrors(refundForm);
    const method = refundForm.elements.method.value;
    const refund = {
      method,
      bank: method === "bank" ? refundForm.elements.bank.value : null,
      account: refundForm.elements.account.value.replace(/\D/g, ""),
      account_name: refundForm.elements.account_name.value.replace(/\s+/g, " ").trim(),
    };
    let ok = true;
    if (method === "bank" && !refund.bank) { setError(refundForm, "bank", "กรุณาเลือกธนาคาร"); ok = false; }
    if (!refund.account) { setError(refundForm, "account", "กรุณากรอกเลขบัญชีหรือพร้อมเพย์"); ok = false; }
    if (!refund.account_name) { setError(refundForm, "account_name", "กรุณากรอกชื่อบัญชี"); ok = false; }
    if (!ok) return;

    setBusy(refundForm, true);
    refundForm.querySelector("[data-status]").textContent = "กำลังยกเลิกคิว…";
    try {
      const { ok: done, body } = await post("/api/v1/booking/cancel", { ...who, ...refund });
      refundForm.querySelector("[data-status]").textContent = "";
      if (!done) {
        setError(refundForm, body.field || "_", body.message || "ยกเลิกไม่สำเร็จ ลองใหม่อีกครั้งนะคะ");
        return;
      }
      finish(body.booking, body.refund_amount);
    } catch (err) {
      console.error("[cancel] submit:", err);
      refundForm.querySelector("[data-status]").textContent = "ติดต่อร้านไม่ได้ เช็กอินเทอร์เน็ตแล้วลองอีกครั้งนะคะ";
    } finally {
      setBusy(refundForm, false);
    }
  });

  /* ---------------- เสร็จ ---------------- */

  function finish(b, amount) {
    const text =
      `ยกเลิกคิวของน้อง${b.pet_name} (${b.id}) เรียบร้อยค่ะ ร้านจะโอนคืน ${baht(amount)} ` +
      "เข้าบัญชีที่แจ้งไว้ ดูสถานะการโอนคืนได้ที่หน้าเช็คคิวนะคะ";
    doneEl.querySelector("[data-done-text]").textContent = text;
    show("done");
    document.dispatchEvent(new CustomEvent("hh:cancelled", { detail: { id: b.id, refund_amount: amount } }));
    const chat = window.hhChat;
    if (chat && chat.createAiBubble) {
      chat.ensureOpen();
      chat.createAiBubble().textContent = text;
    }
    doneEl.querySelector("button").focus();
  }

  /* ---------------- เปิด / ปิด ---------------- */

  function open({ bookingId } = {}) {
    lastTrigger = document.activeElement;
    who = null;
    verifyForm.reset();
    refundForm.reset();
    bankField.hidden = true;
    accountLabel.textContent = "เบอร์พร้อมเพย์ หรือเลขบัตรประชาชน";
    clearErrors(verifyForm);
    clearErrors(refundForm);
    if (bookingId) verifyForm.elements.booking_id.value = bookingId;
    show("verify");
    sheet.hidden = false;
    document.body.classList.add("sheet-open");
    const first = [...verifyForm.querySelectorAll("input")].find((i) => !i.value);
    (first || verifyForm.elements.booking_id).focus({ preventScroll: true });
  }

  function close() {
    if (busy) return;
    sheet.hidden = true;
    document.body.classList.remove("sheet-open");
    if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
  }

  sheet.addEventListener("click", (e) => {
    if (e.target.closest("[data-close-cancel]")) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !sheet.hidden) close();
  });

  window.hhCancel = { open, close };

  // มาจากหน้าเช็คคิว (/?cancel=1) → เปิดป๊อปอัปทันที แล้วล้าง ?cancel ออกจาก URL
  if (new URLSearchParams(location.search).has("cancel")) {
    history.replaceState(null, "", location.pathname + location.hash);
    open();
  }
})();

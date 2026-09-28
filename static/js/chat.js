const chatWindow = document.getElementById("chat-window");
const emptyState = document.getElementById("empty-state");
const loadingIndicator = document.getElementById("loading-indicator");
const errorBanner = document.getElementById("error-banner");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const stopButton = document.getElementById("stop-button");
const newChatButton = document.getElementById("new-chat-button");
const attachmentsBar = document.getElementById("attachments");
const attachButton = document.getElementById("attach-button");
const fileInput = document.getElementById("file-input");

// เก็บ AbortController ของ request ที่กำลังทำงานอยู่ ไว้ให้ปุ่ม "หยุด" เรียกยกเลิกได้
// (นี่คือส่วนที่เติมให้ตรงกับ Usability Heuristic "User Control & Freedom" ที่สอนในสไลด์)
let activeAbortController = null;

function renderMarkdown(rawText) {
  // .trim() กัน trailing newline จากโมเดลบางตัว (เช่น Typhoon) ที่ทำให้บับเบิลสูงลอย
  const html = marked.parse(rawText.trim(), { breaks: true });
  return DOMPurify.sanitize(html);
}

// ค่าจากหน้า Settings (temperature / ความยาวคำตอบ) เก็บใน localStorage — แนบไปกับทุกข้อความ
function chatOptions() {
  const opts = {};
  try {
    const t = localStorage.getItem("ts.temp");
    const m = localStorage.getItem("ts.maxTokens");
    if (t !== null && t !== "") opts.temperature = Number(t);
    if (m !== null && m !== "") opts.max_tokens = Number(m);
    opts.web_search = localStorage.getItem("ts.search") !== "0"; // ค่าเริ่มต้น = เปิด
  } catch (err) {
    /* localStorage ปิดอยู่ก็ไม่เป็นไร ใช้ค่า default ฝั่ง server */
  }
  return opts;
}

function hideEmptyState() {
  emptyState.classList.add("hidden");
}

function showEmptyState() {
  emptyState.classList.remove("hidden");
}

function appendUserMessage(text) {
  hideEmptyState();
  const wrapper = document.createElement("div");
  wrapper.className = "message user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrapper.appendChild(bubble);
  chatWindow.insertBefore(wrapper, loadingIndicator);
  scrollToBottom();
}

function createAiBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "message ai";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrapper.appendChild(bubble);
  chatWindow.insertBefore(wrapper, loadingIndicator);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

// ---- ค้นเว็บ: แถบสถานะระหว่างค้น (อยู่ในบับเบิล) + ชิปแหล่งอ้างอิงใต้คำตอบ ----
function showSearchStatus(bubble, query) {
  const text = query ? `กำลังค้นเว็บ: ${query}` : "กำลังตรวจสอบข้อมูลล่าสุด…";
  bubble.classList.add("bubble--searching");
  bubble.innerHTML =
    '<span class="search-status"><span class="search-status__spin"></span>' +
    '<span class="search-status__text"></span></span>';
  bubble.querySelector(".search-status__text").textContent = text;
  scrollToBottom();
}

function clearSearchStatus(bubble) {
  if (bubble.classList.contains("bubble--searching")) {
    bubble.classList.remove("bubble--searching");
    bubble.innerHTML = "";
  }
}

function renderSources(bubble, sources) {
  const wrapper = bubble.parentElement;
  if (wrapper.querySelector(".sources")) return;
  const box = document.createElement("div");
  box.className = "sources";
  sources.forEach((s, i) => {
    const a = document.createElement("a");
    a.className = "source-chip";
    a.href = s.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.title = s.title || s.url;
    a.innerHTML = '<span class="source-chip__n"></span><span class="source-chip__t"></span>';
    a.querySelector(".source-chip__n").textContent = `[${i + 1}]`;
    a.querySelector(".source-chip__t").textContent = s.title || s.url;
    box.appendChild(a);
  });
  wrapper.appendChild(box);
  scrollToBottom();
}

function showError(message) {
  errorBanner.classList.remove("notice");
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
  console.error("[chat] error:", message);
}

function showNotice(message) {
  errorBanner.classList.add("notice");
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

function clearError() {
  errorBanner.classList.add("hidden");
  errorBanner.classList.remove("notice");
  errorBanner.textContent = "";
}

function setBusy(isBusy) {
  messageInput.disabled = isBusy;
  // ตอนกำลังตอบ: สลับปุ่ม "ส่ง" เป็นปุ่ม "หยุด" แทนที่จะปิดการใช้งานเฉยๆ
  // ผู้ใช้จึงมีทางเลือกที่จะยกเลิกการรอได้เสมอ ไม่ใช่แค่ถูกบล็อกอย่างเดียว
  sendButton.classList.toggle("hidden", isBusy);
  stopButton.classList.toggle("hidden", !isBusy);
  loadingIndicator.classList.toggle("hidden", !isBusy);
}

async function sendMessage(message) {
  clearError();
  appendUserMessage(message);
  setBusy(true);

  activeAbortController = new AbortController();
  const aiBubble = createAiBubble();
  let accumulatedText = "";
  let receivedDone = false;
  let wasAborted = false;
  let pendingSources = null;

  try {
    const response = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, ...chatOptions() }),
      signal: activeAbortController.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`เซิร์ฟเวอร์ตอบกลับด้วยสถานะ ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const rawEvent of events) {
        const dataLine = rawEvent
          .split("\n")
          .find((line) => line.startsWith("data:"));
        if (!dataLine) continue;

        let payload;
        try {
          payload = JSON.parse(dataLine.slice("data:".length).trim());
        } catch (err) {
          console.warn("[chat] ข้าม event ที่ parse ไม่ได้:", rawEvent);
          continue;
        }

        if (payload.search !== undefined) {
          showSearchStatus(aiBubble, payload.search);
        } else if (payload.search_done) {
          clearSearchStatus(aiBubble);
        } else if (payload.sources !== undefined) {
          pendingSources = payload.sources;
        } else if (payload.delta) {
          clearSearchStatus(aiBubble);
          accumulatedText += payload.delta;
          aiBubble.innerHTML = renderMarkdown(accumulatedText);
          scrollToBottom();
        } else if (payload.error) {
          showError(payload.message || "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ");
        } else if (payload.done) {
          receivedDone = true;
          console.log("[chat] stream done");
        }
      }
    }

    clearSearchStatus(aiBubble);

    if (!receivedDone) {
      showError("การเชื่อมต่อถูกตัดกลางทาง กรุณาลองใหม่อีกครั้ง");
    }

    if (!accumulatedText) {
      aiBubble.remove();
    } else if (pendingSources && pendingSources.length) {
      renderSources(aiBubble, pendingSources);
    }
  } catch (err) {
    clearSearchStatus(aiBubble);
    if (err.name === "AbortError") {
      // ผู้ใช้กด "หยุด" เอง ไม่ถือเป็น error ของระบบ — เก็บข้อความบางส่วนที่ได้มาแล้วไว้
      // (ไม่ลบทิ้ง) แล้วแจ้งเป็น notice เฉยๆ แทน error banner สีแดง
      wasAborted = true;
      console.log("[chat] ผู้ใช้กดหยุดการตอบกลับ");
      showNotice("หยุดการตอบกลับแล้ว");
      if (!accumulatedText) {
        aiBubble.remove();
      }
    } else {
      console.error("[chat] sendMessage failed:", err);
      showError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ กรุณาตรวจสอบว่า backend และผู้ให้บริการ AI เปิดอยู่");
      if (!accumulatedText) {
        aiBubble.remove();
      }
    }
  } finally {
    activeAbortController = null;
    setBusy(false);
    messageInput.focus();
    refreshConversations(); // อัปเดตชื่อ/ลำดับบทสนทนาใน sidebar
  }
}

// วาดข้อความที่โหลดมาจาก backend ลงหน้าจอ (ตอนเปิดหน้า / สลับบทสนทนา)
function renderStored(messages) {
  chatWindow.querySelectorAll(".message").forEach((el) => el.remove());
  const list = messages || [];
  for (const m of list) {
    if (m.role === "user") {
      appendUserMessage(m.content);
    } else if (m.role === "assistant") {
      const bubble = createAiBubble();
      bubble.innerHTML = renderMarkdown(m.content || "");
    }
  }
  if (list.length) hideEmptyState();
  else showEmptyState();
  scrollToBottom();
}

async function startNewConversation() {
  newChatButton.disabled = true;
  try {
    const response = await fetch("/api/v1/conversations", { method: "POST" });
    if (!response.ok) throw new Error(`สถานะ ${response.status}`);
    renderStored([]);
    attachments = [];
    renderAttachments();
    clearError();
    messageInput.value = "";
    messageInput.focus();
    refreshConversations();
  } catch (err) {
    console.error("[chat] startNewConversation failed:", err);
    showError("เริ่มบทสนทนาใหม่ไม่สำเร็จ กรุณาลองอีกครั้ง");
  } finally {
    newChatButton.disabled = false;
  }
}

// ============ ไฟล์แนบ (PDF / รูปภาพ / ข้อความ) ============
// เก็บรายการไฟล์ที่อัปโหลดแล้ว (metadata อย่างเดียว เนื้อหาอยู่ที่ backend)
let attachments = [];
let pendingUpload = false;

const KIND_ICON = { pdf: "📄", image: "🖼️", text: "📝" };

function renderAttachments() {
  attachmentsBar.innerHTML = "";
  const hasAny = attachments.length > 0 || pendingUpload;
  attachmentsBar.classList.toggle("hidden", !hasAny);

  attachments.forEach((att, index) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    const meta = att.meta || {};
    const bits = [`${att.chars.toLocaleString("th-TH")} ตัวอักษร`];
    if (meta.ocr_pages) bits.push(`OCR ${meta.ocr_pages} หน้า`);
    if (meta.vision_used) bits.push("อ่านภาพแล้ว");
    if (meta.truncated) bits.push("ตัดบางส่วน");
    chip.innerHTML =
      `<span class="attach-chip__icon">${KIND_ICON[att.kind] || "📎"}</span>` +
      `<span class="attach-chip__body"><span class="attach-chip__name"></span>` +
      `<span class="attach-chip__meta"></span></span>` +
      `<button class="attach-chip__remove" type="button" title="เอาไฟล์ออก">✕</button>`;
    chip.querySelector(".attach-chip__name").textContent = att.name;
    chip.querySelector(".attach-chip__meta").textContent = bits.join(" · ");
    chip.querySelector(".attach-chip__remove").addEventListener("click", () =>
      deleteAttachment(index)
    );
    attachmentsBar.appendChild(chip);
  });

  if (pendingUpload) {
    const chip = document.createElement("div");
    chip.className = "attach-chip is-pending";
    chip.innerHTML =
      `<span class="attach-chip__spin"></span>` +
      `<span class="attach-chip__body"><span class="attach-chip__name">กำลังอ่านไฟล์…</span></span>`;
    attachmentsBar.appendChild(chip);
  }
}

function setAttachBusy(busy) {
  pendingUpload = busy;
  attachButton.disabled = busy;
  renderAttachments();
}

async function uploadFile(file) {
  if (!file) return;
  clearError();
  setAttachBusy(true);
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/v1/attachments", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (payload.error) {
      showError(payload.message || "อัปโหลดไฟล์ไม่สำเร็จ");
    } else if (payload.ok && payload.attachment) {
      attachments.push(payload.attachment);
    } else {
      showError("อัปโหลดไฟล์ไม่สำเร็จ กรุณาลองใหม่");
    }
  } catch (err) {
    console.error("[chat] uploadFile failed:", err);
    showError("อัปโหลดไฟล์ไม่สำเร็จ กรุณาตรวจสอบการเชื่อมต่อ");
  } finally {
    setAttachBusy(false);
  }
}

async function deleteAttachment(index) {
  try {
    const response = await fetch(`/api/v1/attachments/${index}`, { method: "DELETE" });
    const payload = await response.json().catch(() => ({}));
    attachments = payload.attachments || attachments.filter((_, i) => i !== index);
  } catch (err) {
    console.error("[chat] deleteAttachment failed:", err);
    attachments = attachments.filter((_, i) => i !== index);
  } finally {
    renderAttachments();
  }
}

async function loadAttachments() {
  try {
    const response = await fetch("/api/v1/attachments");
    if (!response.ok) return;
    const payload = await response.json();
    attachments = payload.attachments || [];
    renderAttachments();
  } catch (err) {
    console.warn("[chat] loadAttachments failed:", err);
  }
}

attachButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  fileInput.value = ""; // ให้เลือกไฟล์ชื่อเดิมซ้ำได้
  uploadFile(file);
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;
  messageInput.value = "";
  sendMessage(message);
});

stopButton.addEventListener("click", () => {
  activeAbortController?.abort();
});

newChatButton.addEventListener("click", startNewConversation);

// ============ ประวัติ (รายการบทสนทนาใน sidebar) ============
const historyList = document.getElementById("history-list");

function relativeTime(ts) {
  const s = Math.max(0, Date.now() / 1000 - Number(ts));
  if (s < 60) return "เมื่อสักครู่";
  if (s < 3600) return `${Math.floor(s / 60)} นาทีที่แล้ว`;
  if (s < 86400) return `${Math.floor(s / 3600)} ชม.ที่แล้ว`;
  if (s < 172800) return "เมื่อวาน";
  return `${Math.floor(s / 86400)} วันก่อน`;
}

function renderConversations(conversations) {
  if (!historyList) return;
  historyList.innerHTML = "";
  if (!conversations || !conversations.length) {
    historyList.innerHTML = '<p class="history-empty">ยังไม่มีบทสนทนา</p>';
    return;
  }
  for (const c of conversations) {
    const row = document.createElement("div");
    row.className = "history-row" + (c.active ? " is-active" : "");
    row.innerHTML =
      '<button class="history-row__open" type="button">' +
      '<span class="history-row__title"></span>' +
      '<span class="history-row__meta"></span></button>' +
      '<button class="history-row__del" type="button" title="ลบ">✕</button>';
    row.querySelector(".history-row__title").textContent = c.title;
    row.querySelector(".history-row__meta").textContent =
      `${relativeTime(c.updated)} · ${c.count} ข้อความ`;
    row.querySelector(".history-row__open").addEventListener("click", () => openConversation(c.id));
    row.querySelector(".history-row__del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(c.id);
    });
    historyList.appendChild(row);
    if (c.active) row.scrollIntoView({ block: "nearest" });
  }
}

async function refreshConversations() {
  try {
    const r = await fetch("/api/v1/conversations");
    if (!r.ok) return;
    renderConversations((await r.json()).conversations);
  } catch (err) {
    console.warn("[chat] refreshConversations failed:", err);
  }
}

async function openConversation(id) {
  try {
    const r = await fetch(`/api/v1/conversations/${id}/activate`, { method: "POST" });
    const payload = await r.json().catch(() => ({}));
    if (payload.error || !payload.ok) {
      showError(payload.message || "เปิดบทสนทนาไม่สำเร็จ");
      return;
    }
    renderStored(payload.messages);
    attachments = payload.attachments || [];
    renderAttachments();
    clearError();
    refreshConversations();
    messageInput.focus();
  } catch (err) {
    console.error("[chat] openConversation failed:", err);
    showError("เปิดบทสนทนาไม่สำเร็จ กรุณาลองใหม่");
  }
}

async function deleteConversation(id) {
  try {
    const r = await fetch(`/api/v1/conversations/${id}`, { method: "DELETE" });
    const payload = await r.json().catch(() => ({}));
    renderConversations(payload.conversations);
    // ถ้าเผลอลบบทที่กำลังเปิดอยู่ ให้โหลดบทที่ active ใหม่มาแสดง
    const active = (payload.conversations || []).find((c) => c.active);
    if (active) openConversation(active.id);
  } catch (err) {
    console.error("[chat] deleteConversation failed:", err);
  }
}

// โหลดบทที่ active + รายการบทสนทนาใหม่จากเซิร์ฟเวอร์ — ใช้ตอนกลับจากโหมดเสียง
// (โหมดเสียงคุยผ่าน /chat/stream เดิม ประวัติถูกบันทึกฝั่ง server แล้ว แค่ต้องรีเฟรชหน้า)
async function reloadFromServer() {
  try {
    const r = await fetch("/api/v1/history");
    if (r.ok) renderStored((await r.json()).messages);
  } catch (err) {
    console.warn("[chat] reloadFromServer failed:", err);
  }
  loadAttachments();
  refreshConversations();
}
window.voiceSyncChat = reloadFromServer;

// ============ โหลดสถานะเริ่มต้น ============
(async function init() {
  loadAttachments();
  try {
    const r = await fetch("/api/v1/history");
    if (r.ok) renderStored((await r.json()).messages);
  } catch (err) {
    console.warn("[chat] load history failed:", err);
  }
  refreshConversations();
})();

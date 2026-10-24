const chatPanel = document.getElementById("chat-panel");
const chatStatus = document.getElementById("chat-status");
const launcher = document.getElementById("chat-launcher");
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

// ข้อความที่ assistant บันทึกแทนการส่งรูป (chatbot/assistant.py: IMAGE_MARKER)
const IMAGE_MARKER = "(ส่งรูปภาพ)";

// เก็บ AbortController ของ request ที่กำลังทำงานอยู่ ไว้ให้ปุ่ม "หยุด" เรียกยกเลิกได้
// (Usability Heuristic "User Control & Freedom")
let activeAbortController = null;
let lastMessage = "";

function renderMarkdown(rawText) {
  // .trim() กัน trailing newline จากโมเดลบางตัว (เช่น Typhoon) ที่ทำให้บับเบิลสูงลอย
  const html = marked.parse(rawText.trim(), { breaks: true });
  return DOMPurify.sanitize(html);
}

// ============ เปิด/ปิดหน้าต่างแชท ============
function openChat({ pickPhoto = false } = {}) {
  chatPanel.hidden = false;
  // เว้น 1 เฟรมให้ transition เลื่อนเข้าทำงาน (hidden → แสดง แล้วค่อยเติม is-open)
  requestAnimationFrame(() => chatPanel.classList.add("is-open"));
  document.body.classList.add("chat-open");
  launcher.setAttribute("aria-expanded", "true");
  if (pickPhoto) fileInput.click();
  else setTimeout(() => messageInput.focus(), 250);
}

function closeChat() {
  chatPanel.classList.remove("is-open");
  document.body.classList.remove("chat-open");
  launcher.setAttribute("aria-expanded", "false");
  setTimeout(() => {
    if (!chatPanel.classList.contains("is-open")) chatPanel.hidden = true;
  }, 320);
  launcher.focus();
}

document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-open-chat]");
  if (opener) {
    openChat({ pickPhoto: opener.hasAttribute("data-pick-photo") });
    return;
  }
  const picker = e.target.closest("[data-pick-photo]");
  if (picker) fileInput.click();
  const ask = e.target.closest("[data-ask]");
  if (ask && !activeAbortController) sendMessage(ask.dataset.ask);
});
document.getElementById("chat-close").addEventListener("click", closeChat);
document.addEventListener("keydown", (e) => {
  // Escape ตอนป๊อปอัปจองเปิดอยู่ = ปิดป๊อปอัปอย่างเดียว (booking.js จัดการ) ไม่ปิดหน้าต่างแชท
  if (document.querySelector(".sheet:not([hidden])")) return;
  if (e.key === "Escape" && chatPanel.classList.contains("is-open")) closeChat();
});
if (location.hash === "#chat") openChat();

// ============ สถานะของน้องหอม (หัวแชทขยับตาม) ============
const STATUS_TEXT = {
  idle: "พร้อมตอบ",
  thinking: "กำลังพิมพ์…",
  looking: "กำลังดูรูปน้อง…",
};
function setMascot(state) {
  chatPanel.dataset.state = state;
  chatStatus.textContent = STATUS_TEXT[state] || STATUS_TEXT.idle;
}

// ============ บับเบิลข้อความ ============
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
  return bubble;
}

// บับเบิลรูปที่ลูกค้าส่ง (ภาพย่อจากเครื่องลูกค้าเอง ไม่ได้โหลดกลับจากเซิร์ฟเวอร์)
function appendPhotoMessage(file) {
  const bubble = appendUserMessage("");
  bubble.classList.add("bubble--photo");
  if (file && file.type.startsWith("image/")) {
    const img = document.createElement("img");
    img.alt = "รูปที่ส่ง";
    img.src = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(img.src);
      scrollToBottom();
    };
    bubble.appendChild(img);
  } else {
    bubble.textContent = file ? `ส่งไฟล์ ${file.name}` : "ส่งรูปแล้ว";
  }
  return bubble;
}

function createAiBubble() {
  hideEmptyState();
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

// การ์ด/องค์ประกอบอื่นที่ไม่ใช่บับเบิลข้อความ (เช่น ใบจองจาก booking.js) ในฝั่งบอท
function appendAiNode(node) {
  hideEmptyState();
  const wrapper = document.createElement("div");
  wrapper.className = "message ai message--card";
  wrapper.appendChild(node);
  chatWindow.insertBefore(wrapper, loadingIndicator);
  scrollToBottom();
  return wrapper;
}

// ให้ booking.js ใช้วาดข้อความ/ใบจองลงแชท และหยิบรูปน้องที่ลูกค้าส่งไว้ไปใส่ฟอร์มจอง
window.hhChat = {
  createAiBubble,
  appendAiNode,
  scrollToBottom,
  lastPetFile: null,
  ensureOpen() {
    if (!chatPanel.classList.contains("is-open")) openChat();
  },
};

// ============ แจ้งเตือน ============
function showError(message, { retry = false } = {}) {
  errorBanner.classList.remove("alert--notice");
  errorBanner.innerHTML = "";
  const text = document.createElement("span");
  text.textContent = message;
  errorBanner.appendChild(text);
  if (retry && lastMessage) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "alert__action";
    btn.textContent = "ส่งอีกครั้ง";
    btn.addEventListener("click", () => sendMessage(lastMessage));
    errorBanner.appendChild(btn);
  }
  errorBanner.classList.remove("hidden");
  console.error("[chat] error:", message);
}

function showNotice(message) {
  errorBanner.classList.add("alert--notice");
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

function clearError() {
  errorBanner.classList.add("hidden");
  errorBanner.classList.remove("alert--notice");
  errorBanner.textContent = "";
}

function setBusy(isBusy) {
  messageInput.disabled = isBusy;
  // ตอนกำลังตอบ: สลับปุ่ม "ส่ง" เป็นปุ่ม "หยุด" ผู้ใช้จึงยกเลิกการรอได้เสมอ
  sendButton.classList.toggle("hidden", isBusy);
  stopButton.classList.toggle("hidden", !isBusy);
  loadingIndicator.classList.toggle("hidden", !isBusy);
  setMascot(isBusy ? "thinking" : "idle");
  if (isBusy) scrollToBottom();
}

// ============ ส่งข้อความ (สตรีม SSE) ============
async function sendMessage(message) {
  clearError();
  lastMessage = message;
  appendUserMessage(message);
  setBusy(true);

  activeAbortController = new AbortController();
  const aiBubble = createAiBubble();
  let accumulatedText = "";
  let receivedDone = false;
  let actions = null; // ปุ่มทางลัดใต้คำตอบ ("check" / "cancel" / "book") — เซิร์ฟเวอร์เลือกให้

  try {
    const response = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, web_search: false }),
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
        const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data:"));
        if (!dataLine) continue;

        let payload;
        try {
          payload = JSON.parse(dataLine.slice("data:".length).trim());
        } catch (err) {
          console.warn("[chat] ข้าม event ที่ parse ไม่ได้:", rawEvent);
          continue;
        }

        if (payload.knowledge !== undefined) {
          // ชิ้นข้อมูลร้านที่ RAG ใช้ตอบ — ไม่แสดงใต้คำตอบแล้ว (ร้านขอเอาออก 25 ต.ค. 2569)
        } else if (payload.actions) {
          actions = payload.actions;
        } else if (payload.blocked) {
          // guardrails ปฏิเสธคำถามนี้ — ข้อความปฏิเสธตามมาใน delta
          aiBubble.classList.add("bubble--refusal");
        } else if (payload.delta) {
          accumulatedText += payload.delta;
          aiBubble.innerHTML = renderMarkdown(accumulatedText);
          scrollToBottom();
        } else if (payload.replace !== undefined) {
          // output guard บล็อกคำตอบ — แทนข้อความทั้งหมดด้วยข้อความที่ปลอดภัยจากเซิร์ฟเวอร์
          accumulatedText = payload.replace;
          aiBubble.innerHTML = renderMarkdown(accumulatedText);
          scrollToBottom();
        } else if (payload.error) {
          showError(payload.message || "น้องหอมตอบไม่ได้ในตอนนี้ ลองส่งใหม่อีกครั้ง", { retry: true });
        } else if (payload.done) {
          receivedDone = true;
        }
      }
    }

    if (!receivedDone) {
      showError("การเชื่อมต่อหลุดระหว่างตอบ ลองส่งใหม่อีกครั้ง", { retry: true });
    }

    if (!accumulatedText) {
      aiBubble.parentElement.remove();
    } else if (!aiBubble.classList.contains("bubble--refusal")) {
      if (actions) window.hhBooking?.addActions(aiBubble, actions);
      else window.hhBooking?.maybeAddCta(message, aiBubble);
    }
  } catch (err) {
    if (err.name === "AbortError") {
      // ผู้ใช้กด "หยุด" เอง ไม่ใช่ error — เก็บข้อความบางส่วนที่ได้มาแล้วไว้
      showNotice("หยุดตอบแล้ว");
    } else {
      console.error("[chat] sendMessage failed:", err);
      showError("ติดต่อน้องหอมไม่ได้ เช็กอินเทอร์เน็ตแล้วส่งใหม่อีกครั้ง", { retry: true });
    }
    if (!accumulatedText) aiBubble.parentElement.remove();
  } finally {
    activeAbortController = null;
    setBusy(false);
    messageInput.focus();
  }
}

// วาดข้อความที่โหลดมาจาก backend ลงหน้าจอ (ตอนเปิดหน้า / กลับจากโหมดเสียง)
function renderStored(messages) {
  chatWindow.querySelectorAll(":scope > .message").forEach((el) => el.remove());
  const list = messages || [];
  for (const m of list) {
    if (m.role === "user") {
      if (m.content === IMAGE_MARKER) appendPhotoMessage(null);
      else appendUserMessage(m.content);
    } else if (m.role === "assistant") {
      createAiBubble().innerHTML = renderMarkdown(m.content || "");
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
  } catch (err) {
    console.error("[chat] startNewConversation failed:", err);
    showError("เริ่มแชทใหม่ไม่สำเร็จ ลองกดอีกครั้ง");
  } finally {
    newChatButton.disabled = false;
  }
}

// ============ ไฟล์แนบ (รูปน้อง / สลิป / PDF) ============
// เก็บรายการไฟล์ที่อัปโหลดแล้ว (metadata อย่างเดียว เนื้อหาอยู่ที่ backend)
let attachments = [];

const KIND_LABEL = { pdf: "PDF", image: "รูป", text: "ข้อความ" };
const IMAGE_TYPE_LABEL = { pet: "รูปน้อง", slip: "สลิป" };

function renderAttachments() {
  attachmentsBar.innerHTML = "";
  attachmentsBar.classList.toggle("hidden", attachments.length === 0);

  attachments.forEach((att, index) => {
    const meta = att.meta || {};
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    chip.innerHTML =
      '<span class="attach-chip__kind"></span><span class="attach-chip__name"></span>' +
      '<button class="attach-chip__remove" type="button" aria-label="เอาไฟล์นี้ออก">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17" /></svg></button>';
    chip.querySelector(".attach-chip__kind").textContent =
      IMAGE_TYPE_LABEL[meta.image_type] || KIND_LABEL[att.kind] || "ไฟล์";
    chip.querySelector(".attach-chip__name").textContent = att.name;
    chip.querySelector(".attach-chip__remove").addEventListener("click", () => deleteAttachment(index));
    attachmentsBar.appendChild(chip);
  });
}

// Vercel รับ request ได้ไม่เกิน 4.5 MB — รูปจากมือถือมักใหญ่กว่านั้น จึงย่อในเบราว์เซอร์ก่อนส่ง
// (ด้านยาวสุด 1600 px ยังละเอียดพอให้ Vision แยกพันธุ์/อ่านตัวหนังสือในสลิปได้)
const UPLOAD_MAX_BYTES = 4 * 1024 * 1024;
const SHRINK_ABOVE_BYTES = 1.5 * 1024 * 1024;

async function shrinkImage(file, maxSide = 1600) {
  if (!file.type.startsWith("image/") || file.size <= SHRINK_ABOVE_BYTES) return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close && bmp.close();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    // นามสกุลต้องเป็น .jpg — ฝั่งเซิร์ฟเวอร์ดูชนิดไฟล์จากนามสกุล
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch (err) {
    console.warn("[chat] ย่อรูปไม่สำเร็จ ส่งไฟล์เดิม:", err);
    return file;
  }
}

async function uploadFile(original) {
  if (!original) return;
  const file = await shrinkImage(original);
  if (file.size > UPLOAD_MAX_BYTES) {
    showError("ไฟล์ใหญ่เกิน 4 MB ลองส่งไฟล์ที่เล็กลง หรือถ่ายรูปหน้าที่ต้องการแทน");
    return;
  }
  clearError();
  hideEmptyState();
  attachButton.disabled = true;
  appendPhotoMessage(file);
  setMascot("looking");
  loadingIndicator.classList.remove("hidden");
  scrollToBottom();
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/v1/attachments", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (payload.error) {
      showError(payload.message || "อ่านไฟล์นี้ไม่ได้ ลองส่งรูปใหม่อีกครั้ง");
    } else if (payload.ok && payload.attachment) {
      attachments.push(payload.attachment);
      renderAttachments();
      // รูปสัตว์/สลิป: เซิร์ฟเวอร์ตอบกลับทันที (ประเมินราคา / ตรวจสลิป)
      const isPet = (payload.attachment.meta || {}).image_type === "pet";
      if (isPet) window.hhChat.lastPetFile = file; // ใช้เป็นรูปน้องบนใบจองได้เลย ไม่ต้องเลือกใหม่
      if (payload.reply) {
        const bubble = createAiBubble();
        bubble.innerHTML = renderMarkdown(payload.reply);
        if (isPet) window.hhBooking?.addCta(bubble);
      }
    } else {
      showError("ส่งรูปไม่สำเร็จ ลองส่งใหม่อีกครั้ง");
    }
  } catch (err) {
    console.error("[chat] uploadFile failed:", err);
    showError("ส่งรูปไม่สำเร็จ เช็กอินเทอร์เน็ตแล้วลองใหม่");
  } finally {
    attachButton.disabled = false;
    loadingIndicator.classList.add("hidden");
    setMascot("idle");
    scrollToBottom();
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

// ============ โหลดสถานะเริ่มต้น ============
(async function init() {
  loadAttachments();
  try {
    const r = await fetch("/api/v1/history");
    if (r.ok) renderStored((await r.json()).messages);
  } catch (err) {
    console.warn("[chat] load history failed:", err);
  }
})();

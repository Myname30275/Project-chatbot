/* โหมดสนทนาด้วยเสียง
 *
 *   STT : Web Speech API (SpeechRecognition, th-TH) — มีในตัว Chrome / Edge / Chrome-Android
 *   LLM : /api/v1/chat/stream เดิม (ประวัติ/ค้นเว็บ/Settings ใช้ต่อได้เลย)
 *   TTS : เลือกได้ในช่อง "เสียงพูด" — เสียงโคลน Cartesia (ผ่าน /api/v1/tts/stream, ใช้เครดิต)
 *         หรือเสียง speechSynthesis ของเบราว์เซอร์ (ฟรี, ใช้เมื่อ Cartesia ล้มเหลว/ไม่ได้ตั้งค่า)
 *   ภาพ : โครงข่ายเซลล์ประสาทบน <canvas> ที่ขยับตามระดับเสียงจริง
 *
 * ลูป: ฟัง → [ผู้ใช้พูดจบ] → คิด (สตรีมจาก LLM) → พูด → กลับไปฟัง
 * แตะที่วงกลม = พูดแทรก (หยุดเสียง/ยกเลิกคำขอ แล้วฟังใหม่)
 */
(function () {
  "use strict";

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis || null;

  const overlay = document.getElementById("voice-overlay");
  const openBtn = document.getElementById("voice-button");
  if (!overlay || !openBtn) return;

  const exitBtn = document.getElementById("voice-exit");
  const ccBtn = document.getElementById("voice-cc");
  const stageEl = document.getElementById("voice-stage");
  const statusEl = document.getElementById("voice-status");
  const canvas = document.getElementById("voice-canvas");
  const ccBox = document.getElementById("voice-cc-box");
  const saidEl = document.getElementById("voice-said");
  const replyEl = document.getElementById("voice-reply");
  const errEl = document.getElementById("voice-error");
  const voiceSelect = document.getElementById("opt-voice");

  // เสียงโคลน Cartesia ที่เลือกได้จากช่อง "เสียงพูด" เดียวกับเสียง browser (ไม่มี UI แยก
  // ระบบเสียง/provider อีกต่อไป) — เพิ่มเสียงใหม่ได้โดยเติมรายการนี้ ค่า id คือ Cartesia voice ID
  const CARTESIA_VOICES = [
    { id: "096614e2-9381-4012-b4f4-1ce70e33e81f", name: "ASN" },
    { id: "fef31e4e-2299-49e0-a24a-d9f98aa69990", name: "krt" },
    { id: "28447233-a97c-4c87-9c6a-ec6d60d13fca", name: "Dora" },
    { id: "a360d15f-279e-4796-bb8b-54896882c956", name: "Hiso" },
    { id: "cb9de16c-a818-44fc-8e57-91d95ebaf1ee", name: "ASN2" },
    { id: "3594e019-08ed-4e03-8a4a-0a5eb55acfe9", name: "Khudo" },
  ];
  const CARTESIA_PREFIX = "cartesia:";

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  let cartesiaReady = false;
  const cartesiaConfig = fetch("/api/v1/tts/config")
    .then(r => r.ok ? r.json() : {enabled:false})
    .then(c => {
      cartesiaReady = c.enabled;
      populateVoices(); // ติดป้าย "(ยังไม่พร้อม)" ที่ตัวเลือกเสียงโคลนถ้า Cartesia ยังไม่ได้ตั้งค่า
    }).catch(() => {});

  let state = "off";          // off | listening | thinking | speaking | error
  let rec = null;
  let recRunning = false;
  let finalText = "";
  let abortCtrl = null;
  let micStream = null, audioCtx = null, analyser = null, timeBuf = null;
  let level = 0, targetLevel = 0;
  let rafId = 0;

  // สตรีมทีละท่อนคำตอบ: ยิง /tts ทันทีที่ตัดท่อนได้ (ไม่รอคำตอบ LLM จบทั้งก้อน) แล้วต่อคิว
  // เล่นแบบไม่มีช่องว่าง (gapless) — ดูฟังก์ชัน pumpSpeakQueue()
  let speakSession = 0;            // เพิ่มทุกครั้งที่เริ่มคำตอบใหม่/พูดแทรก/ปิดโหมด — ยกเลิกงานค้างของรอบก่อน
  let pendingTexts = [];           // ท่อนข้อความที่ตัดพร้อมแล้ว รอยิง /tts
  let queueDone = false;           // true เมื่อ ask() ส่งท่อนสุดท้ายของคำตอบนี้เข้าคิวแล้ว
  let spokeAnything = false;       // เคยพูดอย่างน้อย 1 ท่อนในรอบนี้ไหม
  let pumping = false;             // กันไม่ให้ pumpSpeakQueue ทำงานซ้อนกัน
  let refillSpeech = null;         // เติมงานได้แม้ consumer กำลัง await เสียงท่อนก่อน
  let serverDownThisTurn = false;  // เซิร์ฟเวอร์เสียงล้มไปแล้วในคำตอบนี้ — ท่อนที่เหลือใช้เบราว์เซอร์เลย กันสลับเสียงไปมา
  let nextPlayTime = 0;            // เวลา (audioCtx.currentTime) ที่จะเริ่มเล่นท่อนถัดไป — ต่อกันไม่มีช่องว่าง
  let activeSources = [];          // AudioBufferSourceNode ที่กำลังเล่น/รอเล่นอยู่ (ไว้หยุดทั้งหมดตอนพูดแทรก)
  let ttsAnalyser = null, ttsTimeBuf = null; // analyser รวมของทั้งคิว (ให้ viz ขยับตามเสียงจริง)
  let ttsFreqBuf = null; // สเปกตรัมความถี่ของ ttsAnalyser (ใช้แยก viseme ให้ avatar ปากขยับสมจริง)
  let ttsAborts = new Set();       // AbortController ของทุกคำขอ /tts ที่ยังค้างอยู่ (ยิงล่วงหน้าได้พร้อมกันหลายท่อน)
  const TTS_PREFETCH = 2;          // ยิง /tts ท่อนถัดไปล่วงหน้าได้สูงสุดกี่ท่อนพร้อมกัน — ซ่อนดีเลย์เครือข่าย
                                    // ไม่ให้บวกเพิ่มระหว่างท่อน ต่อท่อน
  let ssKeepAlive = 0;             // (speechSynthesis) กัน Chrome หยุดเสียงเองหลัง ~15 วิ

  /* ---------------- ตัวเลือกเสียง (หน้า Settings) ---------------- */

  function populateVoices() {
    if (!voiceSelect) return;
    const voices = synth ? synth.getVoices() : [];
    const saved = ls.get("ts.voice", "");
    const isThai = (v) => /^th([-_]|$)/i.test(v.lang);
    const th = voices.filter(isThai);
    const rest = voices.filter((v) => !isThai(v));

    voiceSelect.innerHTML = "";
    const def = document.createElement("option");
    def.value = ""; def.textContent = "— ค่าเริ่มต้นของระบบ —";
    voiceSelect.appendChild(def);

    if (CARTESIA_VOICES.length) {
      const g = document.createElement("optgroup");
      g.label = "เสียงโคลน (Cartesia)";
      CARTESIA_VOICES.forEach((v) => {
        const o = document.createElement("option");
        o.value = CARTESIA_PREFIX + v.id;
        o.textContent = v.name + (cartesiaReady ? "" : " — ยังไม่พร้อม");
        g.appendChild(o);
      });
      voiceSelect.appendChild(g);
    }

    const addGroup = (label, list) => {
      if (!list.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      list.forEach((v) => {
        const o = document.createElement("option");
        o.value = v.voiceURI;
        o.textContent = v.name + " (" + v.lang + ")";
        g.appendChild(o);
      });
      voiceSelect.appendChild(g);
    };
    addGroup("ภาษาไทย", th);
    addGroup("อื่น ๆ", rest);

    let want = saved;
    if (!want) {
      want = CARTESIA_VOICES.length ? CARTESIA_PREFIX + CARTESIA_VOICES[0].id : (th[0] ? th[0].voiceURI : "");
      if (want) ls.set("ts.voice", want);
    }
    // ค่าที่เคยบันทึกไว้อาจเป็นเสียงที่หายไปแล้ว (เช่น browser คนละเครื่อง) — เช็คว่ามีตัวเลือก
    // นั้นอยู่จริงก่อน ไม่งั้น <select> จะโชว์ตัวแรกเฉยๆ ทั้งที่ localStorage ยังเก็บค่าเดิมไว้
    const exists = [...voiceSelect.options].some((o) => o.value === want);
    voiceSelect.value = exists ? want : "";
  }

  populateVoices();
  if (synth && "onvoiceschanged" in synth) synth.addEventListener("voiceschanged", populateVoices);
  voiceSelect && voiceSelect.addEventListener("change", () => ls.set("ts.voice", voiceSelect.value));

  function selectedCartesiaVoiceId() {
    const v = ls.get("ts.voice", "");
    return v.startsWith(CARTESIA_PREFIX) ? v.slice(CARTESIA_PREFIX.length) : null;
  }

  function chosenVoice() {
    if (!synth) return null;
    const uri = ls.get("ts.voice", "");
    if (uri.startsWith(CARTESIA_PREFIX)) return null; // เลือกเสียงโคลนไว้ ไม่ใช่เสียง browser
    const voices = synth.getVoices();
    return (
      voices.find((v) => v.voiceURI === uri) ||
      voices.find((v) => /^th([-_]|$)/i.test(v.lang)) ||
      null
    );
  }

  async function ensureAudioCtx() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === "suspended") {
      try { await audioCtx.resume(); } catch {}
    }
  }

  const TTS_CHUNK_EAGER_LEN = 40;  // ท่อนแรกของคำตอบ: ตัดเร็ว (ไม่ต้องรอจบประโยค) ให้เสียงเริ่มไวสุด
  const TTS_CHUNK_LEN = 160;       // ท่อนถัดไป: ตัดที่ท้ายประโยค หรือถ้ายาวเกินนี้ยังไม่เจอที่ตัดก็ตัดเลย
  const CHUNK_END_RE = /[\n]|[.!?](?=\s|$)/;

  // ดึงท่อนที่ "พร้อมพูด" ออกจาก buffer ข้อความที่สะสมไว้ — คืนท่อนที่ตัดได้ + ส่วนที่เหลือรอท่อนถัดไป
  function popReadyChunks(buf, haveSpokenFirst) {
    const out = [];
    let rest = buf;
    for (;;) {
      const m = CHUNK_END_RE.exec(rest);
      if (m) {
        const idx = m.index + m[0].length;
        const piece = rest.slice(0, idx).trim();
        rest = rest.slice(idx);
        if (piece) { out.push(piece); haveSpokenFirst = true; }
        continue;
      }
      const cap = !haveSpokenFirst && out.length === 0 ? TTS_CHUNK_EAGER_LEN : TTS_CHUNK_LEN;
      if (rest.length >= cap) {
        const piece = rest.slice(0, cap).trim();
        rest = rest.slice(cap);
        if (piece) { out.push(piece); haveSpokenFirst = true; }
        continue;
      }
      break;
    }
    return { out, rest, haveSpokenFirst };
  }

  function resetSpeakQueue() {
    pumping = false;
    refillSpeech = null;
    pendingTexts = [];
    queueDone = false;
    spokeAnything = false;
    serverDownThisTurn = false;
    nextPlayTime = 0;
    ttsAnalyser = null;
    ttsTimeBuf = null;
  }

  // หยุดเสียงที่กำลังเล่น/ยิงอยู่ทั้งหมดทันที (พูดแทรก/ปิดโหมด) — ผู้เรียกต้อง speakSession++
  // เองก่อนเรียกฟังก์ชันนี้ ให้งาน async ที่ค้างอยู่ (fetch/decode ของท่อนก่อนหน้า) รู้ว่าถูกยกเลิก
  function stopAllTts() {
    for (const s of activeSources) {
      try { s.onended = null; s.stop(); } catch {}
    }
    activeSources = [];
    for (const c of ttsAborts) { try { c.abort(); } catch {} }
    ttsAborts.clear();
    if (synth) synth.cancel();
    clearInterval(ssKeepAlive);
    pendingTexts = [];
    queueDone = true;
    nextPlayTime = 0;
  }

  // เล่น AudioBuffer ต่อจากท่อนก่อนหน้าแบบไม่มีช่องว่าง (gapless) — คืนทันทีหลัง "จัดคิวเล่น" แล้ว
  // ไม่รอเล่นจบ เพื่อให้ pump ไปยิง /tts ท่อนถัดไปได้เลยระหว่างท่อนนี้กำลังเล่นอยู่ (pipeline)
  //
  // fadeIn/fadeOut: ใส่เฉพาะตรง "รอยต่อระหว่างเสียงที่มาจากคนละ synthesis call" (เช่น ประโยคที่
  // 1 จบ ต่อประโยคที่ 2) — เพราะเสียงสองก้อนนี้ generate แยกกัน คลื่นเสียงที่ขอบไม่ได้ต่อเนื่องกัน
  // จริง ตัดสลับกันตรงๆ จะได้ยินเป็นเสียง "ตึ๊ด/ป็อก" (discontinuity click) ส่วนก้อนย่อยที่ผ่าเป็น
  // ชิ้นละ ~100ms ภายใน "หนึ่ง" stream เดียวกันของ Cartesia (ดู speakCartesiaChunk) เป็นคลื่นเสียง
  // ต่อเนื่องเดียวกันจริงๆ อยู่แล้ว ไม่ต้อง fade — ใส่ fade ตรงนั้นเพิ่มจะกลายเป็นเสียงสั่น/แผ่วเป็นจังหวะแทน
  const TTS_FADE_S = 0.01; // 10ms พอลบเสียงคลิกแต่สั้นเกินกว่าจะได้ยินเป็น "จางหาย"

  function scheduleBuffer(audioBuf, session, { fadeIn = false, fadeOut = false } = {}) {
    const src = audioCtx.createBufferSource();
    src.buffer = audioBuf;
    if (!ttsAnalyser) {
      ttsAnalyser = audioCtx.createAnalyser();
      ttsAnalyser.fftSize = 512;
      ttsTimeBuf = new Uint8Array(ttsAnalyser.fftSize);
      ttsAnalyser.connect(audioCtx.destination);
    }
    const startAt = Math.max(nextPlayTime, audioCtx.currentTime + 0.02);
    const dur = audioBuf.duration;
    if (fadeIn || fadeOut) {
      const fade = Math.min(TTS_FADE_S, dur / 2);
      const gain = audioCtx.createGain();
      if (fadeIn) {
        gain.gain.setValueAtTime(0, startAt);
        gain.gain.linearRampToValueAtTime(1, startAt + fade);
      }
      if (fadeOut) {
        gain.gain.setValueAtTime(1, startAt + dur - fade);
        gain.gain.linearRampToValueAtTime(0, startAt + dur);
      }
      src.connect(gain);
      gain.connect(ttsAnalyser);
    } else {
      src.connect(ttsAnalyser);
    }
    activeSources.push(src);
    src.onended = () => {
      activeSources = activeSources.filter((s) => s !== src);
      // เล่นจบแล้วและไม่มีท่อนไหนค้างอยู่อีก (กำลังเล่น/รอยิง/รอ LLM) → กลับไปฟังใหม่
      if (session === speakSession && state === "speaking" &&
          activeSources.length === 0 && pendingTexts.length === 0 && !pumping && queueDone) {
        startListening();
      }
    };
    src.start(startAt);
    nextPlayTime = startAt + dur;
  }

  /* ---------------- คำบรรยาย (captions) ---------------- */

  let ccOn = ls.get("ts.captions", "1") !== "0";
  function applyCC() {
    if (ccBox) ccBox.hidden = !ccOn;
    if (ccBtn) {
      ccBtn.setAttribute("aria-pressed", String(ccOn));
      ccBtn.classList.toggle("is-off", !ccOn);
    }
  }
  ccBtn && ccBtn.addEventListener("click", () => {
    ccOn = !ccOn;
    ls.set("ts.captions", ccOn ? "1" : "0");
    applyCC();
  });

  /* ---------------- สถานะ ---------------- */

  const STATUS = {
    listening: "กำลังฟัง…",
    thinking: "กำลังคิด…",
    speaking: "กำลังพูด — แตะเพื่อพูดแทรก",
  };
  function setState(s) {
    state = s;
    overlay.dataset.state = s;
    if (STATUS[s]) statusEl.textContent = STATUS[s];
  }
  function showError(msg) {
    setState("error");
    statusEl.textContent = "";
    errEl.textContent = msg;
    errEl.hidden = false;
  }

  /* ---------------- ลูปสนทนา ---------------- */

  function startListening() {
    if (state === "off") return;
    finalText = "";
    saidEl.textContent = "";
    setState("listening");
    safeRecStart();
  }

  function safeRecStart() {
    if (!rec || recRunning || state === "off") return;
    try {
      rec.start();
      recRunning = true;
    } catch (e) {
      // InvalidStateError = กำลังทำงานอยู่แล้ว — ปล่อยผ่าน
    }
  }

  function enqueueSpeech(text, session) {
    if (session !== speakSession || state === "off" || !text) return;
    pendingTexts.push(text);
    if (refillSpeech) refillSpeech();
    pumpSpeakQueue(session);
  }

  function finishSpeechQueue(session) {
    if (session !== speakSession) return;
    queueDone = true;
    pumpSpeakQueue(session);
  }

  // เริ่มยิง /tts ของท่อนหนึ่งทันที (ไม่รอคิวก่อนหน้าเล่นจบ) — ตัดสินใจ Cartesia/browser ตอน
  // "เริ่มยิง" ไม่ใช่ตอน "ถึงคิวเล่น" เพื่อให้สอดคล้องกับ serverDownThisTurn ที่อาจเพิ่งถูกตั้ง
  // จากท่อนก่อนหน้า (ซึ่งยิงคู่ขนานอยู่และยังไม่รู้ผล)
  //
  // ถ้าผู้ใช้เลือกเสียงโคลน (Cartesia) ไว้ชัดเจนแล้ว จะไม่มีทาง "หลุด" ไปใช้เสียง browser แทนเด็ดขาด
  // — ถ้า Cartesia ใช้งานไม่ได้ตอนนี้ (serverDownThisTurn) ก็แค่ข้ามท่อนนี้ไปเงียบๆ (skip) ไม่พูดเลย
  // ดีกว่าจู่ๆ ได้ยินเสียงคนละคน/คนละเพศมาพูดแทรก — เสียง browser จะถูกใช้ก็ต่อเมื่อผู้ใช้เลือกมันเอง
  // ในหน้าตั้งค่าตั้งแต่แรกเท่านั้น
  function kickoffChunk(text, session) {
    const voiceId = selectedCartesiaVoiceId();
    if (voiceId) {
      if (cartesiaReady && !serverDownThisTurn) return { text, isCartesia: true, voiceId };
      return { text, skip: true };
    }
    return { text, isCartesia: false };
  }

  // consumer: ยิง /tts ท่อนถัดไปล่วงหน้าได้สูงสุด TTS_PREFETCH ท่อนพร้อมกัน (ซ่อนเวลา
  // เครือข่าย/คิวของเซิร์ฟเวอร์ ไม่ให้บวกเพิ่มระหว่างท่อน ต่อท่อน) แต่ยังคง "เล่น" ตามลำดับเดิมเสมอ
  // — await ท่อนที่เก่าที่สุดก่อน แม้ท่อนถัดไปจะเตรียมเสร็จก่อนก็ตาม
  async function pumpSpeakQueue(session) {
    if (pumping) return;
    pumping = true;
    const inFlight = [];
    const refill = () => {
      if (session !== speakSession || state === "off") return;
      while (inFlight.length < TTS_PREFETCH && pendingTexts.length > 0) {
        spokeAnything = true;
        inFlight.push(kickoffChunk(pendingTexts.shift(), session));
      }
    };
    refillSpeech = refill;
    try {
      while (session === speakSession && state !== "off") {
        refill();
        if (inFlight.length === 0) {
          if (queueDone && !spokeAnything) startListening(); // ไม่มีอะไรให้พูดเลยทั้งคำตอบ
          break;
        }
        const item = inFlight[0];
        if (session !== speakSession || state === "off") break;

        if (item.isCartesia) {
          await speakCartesiaChunk(item.text, session, item.voiceId);
          inFlight.shift();
          continue;
        }
        if (item.skip) {
          inFlight.shift();
          continue; // Cartesia ล่มรอบนี้ — ข้ามท่อนนี้ไปเงียบๆ ไม่สลับไปเสียง browser
        }

        inFlight.shift();
        speakBrowserChunk(item.text, session);
      }
    } finally {
      if (session === speakSession) {
        pumping = false;
        refillSpeech = null;
        if (queueDone && activeSources.length === 0 && pendingTexts.length === 0 &&
            !(synth && (synth.speaking || synth.pending)) && state !== "off") {
          startListening();
        }
      }
    }
  }

  function speakBrowserChunk(text, session) {
    if (state === "off" || session !== speakSession) return;
    if (!synth) { console.warn("[voice] เบราว์เซอร์นี้ไม่มี speechSynthesis"); return; }

    const v = chosenVoice();
    const u = new SpeechSynthesisUtterance(text);
    // ตอนเลือกเสียงโคลน (Cartesia) ไว้ v จะเป็น null เสมอ — เดิม fallback เคยฟิกซ์ lang="th-TH"
    // ทุกครั้ง ถ้าข้อความที่หลุดมาเป็นภาษาอังกฤษ (เช่น Cartesia ล้มกลางทาง) จะขอเสียงไทยมาพูดอังกฤษ
    // เพี้ยนๆ แทน ต้องเดาภาษาจากตัวข้อความจริงให้ตรงกับที่ backend ใช้ตัดสินใจส่ง Cartesia (routers/tts.py)
    if (v) { u.voice = v; u.lang = v.lang; }
    else u.lang = /[฀-๿]/.test(text) ? "th-TH" : "en-US";
    u.rate = 1;
    u.pitch = 1;
    const checkDone = () => {
      if (session === speakSession && state === "speaking" &&
          activeSources.length === 0 && pendingTexts.length === 0 && !pumping && queueDone &&
          !synth.speaking && !synth.pending) {
        clearInterval(ssKeepAlive);
        startListening();
      }
    };
    u.onstart = () => setState("speaking");
    u.onboundary = () => { targetLevel = Math.min(1, 0.5 + Math.random() * 0.45); };
    u.onend = checkDone;
    u.onerror = (e) => { console.warn("[voice] speechSynthesis error:", e && e.error); checkDone(); };
    setState("speaking");
    // แก้บั๊ก Chrome: เสียงหยุดเองหลัง ~15 วิ / ค้างสถานะ paused — เตะ resume เป็นระยะ
    clearInterval(ssKeepAlive);
    ssKeepAlive = setInterval(() => {
      if (synth.speaking) synth.resume();
      else clearInterval(ssKeepAlive);
    }, 5000);
    setTimeout(() => { try { synth.resume(); } catch {} }, 80);
    synth.speak(u);
    // ถ้า 1.2 วิ แล้วยังไม่เริ่มพูดและไม่ error — เบราว์เซอร์กลืนเงียบ ข้ามท่อนนี้แล้วไปต่อ
    setTimeout(() => {
      if (session === speakSession && state === "speaking" && !synth.speaking && !synth.pending) {
        console.warn("[voice] speechSynthesis ไม่เริ่มพูด (เบราว์เซอร์อาจไม่มีเสียง TTS)");
        checkDone();
      }
    }, 1200);
  }

  function pcmBytesToBuffer(bytes, count) {
    const buffer = audioCtx.createBuffer(1, count / 2, 24000);
    const floats = buffer.getChannelData(0);
    const data = new DataView(bytes.buffer);
    for (let i = 0; i < floats.length; i++) floats[i] = data.getInt16(i * 2, true) / 32768;
    return buffer;
  }

  // PCM is decoded incrementally; retain incomplete samples between network packets.
  //
  // ~100ms sub-buffer แต่ละก้อนที่ผ่าออกมาจาก stream เดียวกันนี้เป็นคลื่นเสียงต่อเนื่องจริงๆ (ไม่ใช่
  // คนละ synthesis call) จึงไม่ fade ระหว่างกัน — แต่ "กัน" ก้อนล่าสุดไว้หนึ่งก้อนเสมอ (schedule ก้อน
  // ก่อนหน้าแทน) เพื่อให้รู้แน่ชัดว่าก้อนไหนเป็นก้อนแรก/ก้อนสุดท้ายของท่อนนี้ตอนจะ fade ที่ขอบจริงๆ
  // (รอยต่อกับท่อนก่อน/หลัง ซึ่งมาจากคนละ request) โดยไม่ต้องเสียเวลาแฝงเพิ่ม (แค่ช้าไปไม่เกิน ~100ms)
  async function speakCartesiaChunk(text, session, voiceId) {
    // ปกติ kickoffChunk() จะกันไม่ให้เรียกฟังก์ชันนี้เลยตอน serverDownThisTurn (ส่ง skip แทน) —
    // เช็คซ้ำไว้เผื่อเหตุอื่น แต่ไม่สลับไปเสียง browser เหมือนเดิม (ดูเหตุผลใน catch ด้านล่าง)
    if (serverDownThisTurn) return;
    const ctrl = new AbortController();
    ttsAborts.add(ctrl);
    const timer = setTimeout(() => ctrl.abort(), 30000);
    let started = false;
    let reader;
    let held = null;      // sub-buffer ที่เตรียมไว้แล้วแต่ยัง "ไม่รู้" ว่าเป็นก้อนสุดท้ายไหม
    let scheduledAny = false;
    try {
      const res = await fetch("/api/v1/tts/stream", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({text, voice_id: voiceId}), signal:ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
      await ensureAudioCtx();
      reader = res.body.getReader();
      let pending = new Uint8Array(0);
      for (;;) {
        const {value, done} = await reader.read();
        if (session !== speakSession || state === "off") return;
        const bytes = new Uint8Array(pending.length + (value ? value.length : 0));
        bytes.set(pending);
        if (value) bytes.set(value, pending.length);
        // Accumulate 100 ms to avoid scheduling a source for every tiny packet.
        const count = bytes.length - bytes.length % 2;
        if (count && (count >= 4800 || done)) {
          if (held) {
            setState("speaking");
            scheduleBuffer(held, session, { fadeIn: !scheduledAny });
            started = true;
            scheduledAny = true;
          }
          held = pcmBytesToBuffer(bytes, count);
          pending = bytes.slice(count);
        } else pending = bytes;
        if (done) {
          if (pending.length) throw new Error("Incomplete PCM audio");
          if (held) {
            setState("speaking");
            scheduleBuffer(held, session, { fadeIn: !scheduledAny, fadeOut: true });
            started = true;
            scheduledAny = true;
          }
          if (!started) throw new Error("Incomplete PCM audio");
          break;
        }
      }
    } catch (e) {
      if (session !== speakSession || state === "off") return;
      serverDownThisTurn = true;
      console.warn("[voice] Cartesia ใช้งานไม่สำเร็จ → ข้ามข้อความนี้ (ไม่สลับไปเสียง browser):", e);
      const note = document.getElementById("opt-voice-note");
      if (note) note.textContent = "Cartesia ใช้งานไม่สำเร็จรอบนี้ — บางข้อความอาจไม่มีเสียงพูด";
      // ท่อนนี้ยังไม่เริ่มเล่นเสียงเลย (started=false) — ปล่อยผ่านเงียบๆ ไม่พูดท่อนนี้ (ไม่ใช้เสียง
      // browser แทน ผู้ใช้เลือกเสียงโคลนไว้ชัดเจนแล้ว ไม่ต้องการให้สลับเสียง/เพศกลางบทสนทนา) —
      // ท่อนถัดไปจะถูก kickoffChunk() ส่งมาเป็น skip ต่อเนื่องอัตโนมัติเพราะ serverDownThisTurn
      if (started) {
        speakSession++;
        stopAllTts();
        abortCtrl && abortCtrl.abort();
        showError("เสียงขาดช่วง กรุณาปิดแล้วเปิดโหมดเสียงใหม่");
      }
    } finally {
      clearTimeout(timer);
      ttsAborts.delete(ctrl);
      if (reader) { try { await reader.cancel(); } catch {} }
    }
  }

  async function ask(text) {
    setState("thinking");
    saidEl.textContent = text;
    replyEl.textContent = "";
    abortCtrl = new AbortController();
    const session = ++speakSession;
    resetSpeakQueue();
    const opts = typeof window.chatOptions === "function" ? window.chatOptions() : {};
    let reply = "";
    let pendingBuf = "";
    let haveSpokenFirst = false;
    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, ...opts, voice: true }),
        signal: abortCtrl.signal,
      });
      if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

      const reader = res.body.getReader();
      const dec = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let pl;
          try { pl = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (pl.search !== undefined) {
            statusEl.textContent = pl.search ? "กำลังค้นเว็บ: " + pl.search : "กำลังค้นข้อมูลล่าสุด…";
          } else if (pl.delta) {
            reply += pl.delta;
            pendingBuf += pl.delta;
            replyEl.textContent = reply;
            ccBox && (ccBox.scrollTop = ccBox.scrollHeight);
            // ตัดท่อนที่พร้อมพูดได้ออกจาก buffer แล้วยิงเข้าคิวทันที ไม่รอคำตอบจบทั้งก้อน
            const chunked = popReadyChunks(pendingBuf, haveSpokenFirst);
            pendingBuf = chunked.rest;
            haveSpokenFirst = chunked.haveSpokenFirst;
            for (const piece of chunked.out) enqueueSpeech(piece, session);
          } else if (pl.error) {
            throw new Error(pl.message || "stream error");
          }
        }
      }
    } catch (e) {
      abortCtrl = null;
      if (e && e.name === "AbortError") return; // ผู้ใช้พูดแทรก — จัดการที่อื่นแล้ว
      console.error("[voice] ask failed:", e);
      if (session === speakSession) {
        enqueueSpeech("ขออภัย ระบบมีปัญหาในการตอบ ลองพูดใหม่อีกครั้งได้เลย", session);
        finishSpeechQueue(session);
      }
      return;
    }
    abortCtrl = null;
    if (pendingBuf.trim()) enqueueSpeech(pendingBuf.trim(), session);
    finishSpeechQueue(session);
  }

  /* ---------------- พูดแทรก (barge-in) ---------------- */

  stageEl.addEventListener("pointerdown", () => {
    if (state === "speaking") {
      speakSession++;
      stopAllTts();
      abortCtrl && abortCtrl.abort();
      abortCtrl = null;
      startListening();
    } else if (state === "thinking") {
      speakSession++;
      stopAllTts();
      abortCtrl && abortCtrl.abort();
      abortCtrl = null;
      startListening();
    } else if (state === "listening") {
      try { rec && rec.stop(); } catch {} // บังคับให้ประมวลผลสิ่งที่พูดไปแล้ว
    }
  });

  /* ---------------- ตัวรู้จำเสียง ---------------- */

  function buildRec() {
    if (!SR) return null;
    const r = new SR();
    r.lang = "th-TH";
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;

    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interim += res[0].transcript;
      }
      if (state === "listening") {
        saidEl.textContent = (finalText + " " + interim).trim();
        targetLevel = Math.min(1, 0.35 + Math.min(interim.length, 28) / 40);
      }
    };
    r.onspeechstart = () => { if (state === "listening") targetLevel = 0.6; };
    r.onend = () => {
      recRunning = false;
      if (state !== "listening") return;
      if (finalText.trim()) ask(finalText.trim());
      else safeRecStart(); // เงียบ / no-speech → ฟังต่อ
    };
    r.onerror = (e) => {
      recRunning = false;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        showError("ไม่ได้รับอนุญาตให้ใช้ไมโครโฟน — อนุญาตในเบราว์เซอร์แล้วเปิดโหมดเสียงใหม่");
      } else if (e.error === "no-speech" || e.error === "aborted") {
        // onend จะจัดการต่อเอง
      } else {
        console.warn("[voice] recognition error:", e.error);
      }
    };
    return r;
  }

  /* ---------------- มิเตอร์ไมค์ (มีก็ดี ไม่มีก็ได้) ---------------- */

  async function startMeter() {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      timeBuf = new Uint8Array(analyser.fftSize);
      src.connect(analyser);
    } catch (e) {
      micStream = null;
      analyser = null; // ยังใช้งานได้ ระดับเสียงจะมาจาก event ของ recognition แทน
    }
  }
  function micLevel() {
    if (!analyser) return null;
    analyser.getByteTimeDomainData(timeBuf);
    let sum = 0;
    for (let i = 0; i < timeBuf.length; i++) {
      const x = (timeBuf[i] - 128) / 128;
      sum += x * x;
    }
    return Math.min(1, Math.sqrt(sum / timeBuf.length) * 3.4);
  }

  /* ---------------- โครงข่ายเซลล์ประสาท (canvas) ---------------- */

  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1, ox = 0, oy = 0, unit = 1, t0 = 0;
  let nodes = [], edges = [], pulses = [], halos = [];

  function readColor(name, fb) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fb;
  }
  const COL = {
    node: readColor("--blue-deep", "#2563cf"),
    node2: readColor("--blue-bright", "#7cc0f2"),
    core: readColor("--blue", "#3b82f6"),
    edge: "rgba(86,140,195,0.4)",
    pulse: "#ffffff",
  };

  function resizeCanvas() {
    const r = stageEl.getBoundingClientRect();
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = Math.max(1, r.width);
    H = Math.max(1, r.height);
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ox = W / 2;
    oy = H / 2;
    unit = Math.min(W, H) / 2;
  }

  function angDiff(a, b) {
    let d = a - b;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return d;
  }

  function buildNet() {
    nodes = [{ r: 0, a: 0, ring: 0, jitter: 0 }];
    const rings = [[0.27, 6], [0.5, 12], [0.74, 17]];
    rings.forEach(([rad, count], ri) => {
      const offset = ri * 0.45;
      for (let i = 0; i < count; i++) {
        nodes.push({
          r: rad,
          a: (i / count) * Math.PI * 2 + offset,
          ring: ri + 1,
          jitter: Math.random() * 6.283,
        });
      }
    });

    edges = [];
    const byRing = (k) => nodes.map((n, i) => ({ n, i })).filter((o) => o.n.ring === k);
    byRing(1).forEach((o) => edges.push([0, o.i]));
    for (let ri = 1; ri <= 2; ri++) {
      const cur = byRing(ri), nxt = byRing(ri + 1);
      cur.forEach((o) => {
        nxt
          .map((m) => ({ i: m.i, d: Math.abs(angDiff(o.n.a, m.n.a)) }))
          .sort((a, b) => a.d - b.d)
          .slice(0, 2)
          .forEach((m) => edges.push([o.i, m.i]));
      });
      for (let k = 0; k < cur.length; k++) {
        edges.push([cur[k].i, cur[(k + 1) % cur.length].i]);
      }
    }
    pulses = [];
    halos = [];
  }

  function nodePos(n, time) {
    const wob = n.ring ? Math.sin(time * 0.0011 + n.jitter) * unit * 0.016 : 0;
    const rr = n.r * unit * 0.86 + wob;
    return [ox + Math.cos(n.a) * rr, oy + Math.sin(n.a) * rr];
  }

  function spawnPulse() {
    if (!edges.length) return;
    let [from, to] = edges[(Math.random() * edges.length) | 0];
    if (state === "listening" && nodes[from].ring < nodes[to].ring) [from, to] = [to, from];
    else if (state === "speaking" && nodes[from].ring > nodes[to].ring) [from, to] = [to, from];
    pulses.push({ from, to, t: 0, sp: 0.55 + Math.random() * 0.5 });
  }

  function render(now) {
    const time = now - t0;

    if (state === "listening") {
      const m = micLevel();
      const floor = 0.16 + Math.sin(time * 0.0025) * 0.04;
      if (m != null) targetLevel = Math.max(floor, targetLevel * 0.55, m);
      else targetLevel = Math.max(floor, targetLevel * 0.93);
    } else if (state === "thinking") {
      targetLevel = 0.34 + Math.sin(time * 0.005) * 0.1;
    } else if (state === "speaking") {
      if (ttsAnalyser) {
        // เสียงโคลนจากเซิร์ฟเวอร์ — ป้อนระดับเสียงจริง (RMS) ให้ viz ขยับตามคำพูด
        ttsAnalyser.getByteTimeDomainData(ttsTimeBuf);
        let sum = 0;
        for (let i = 0; i < ttsTimeBuf.length; i++) {
          const x = (ttsTimeBuf[i] - 128) / 128;
          sum += x * x;
        }
        const rms = Math.min(1, Math.sqrt(sum / ttsTimeBuf.length) * 3.2);
        targetLevel = Math.max(0.18, rms);
        // สเปกตรัมความถี่ของเสียงที่กำลังเล่นจริง — ให้ avatar (ถ้ามี) ขยับปากตามรูปเสียงจริง
        // (สระเปิด/ปิด/แหลม/ทุ้ม) แทนที่จะอ้าปากตามความดังเบาอย่างเดียว
        if (window.voiceAvatar && window.voiceAvatar.onAudioSpectrum) {
          if (!ttsFreqBuf) ttsFreqBuf = new Uint8Array(ttsAnalyser.frequencyBinCount);
          ttsAnalyser.getByteFrequencyData(ttsFreqBuf);
          window.voiceAvatar.onAudioSpectrum(ttsFreqBuf, audioCtx.sampleRate);
        }
      } else {
        targetLevel = Math.max(0.18, targetLevel * 0.9);
      }
    } else {
      targetLevel = 0.14 + Math.sin(time * 0.0022) * 0.05;
    }
    level += (targetLevel - level) * 0.16;
    if (window.voiceAvatar) window.voiceAvatar.onFrame(level, state);

    ctx.clearRect(0, 0, W, H);

    ctx.lineWidth = 1;
    ctx.strokeStyle = COL.edge;
    for (const [a, b] of edges) {
      const p = nodePos(nodes[a], time), q = nodePos(nodes[b], time);
      ctx.globalAlpha = 0.22 + level * 0.28;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    if (!reduceMotion) {
      const rate =
        state === "listening" ? level * 0.55 :
        state === "speaking" ? 0.22 + level * 0.4 :
        state === "thinking" ? 0.24 : 0.03;
      if (Math.random() < rate) spawnPulse();

      pulses = pulses.filter((pp) => pp.t < 1);
      for (const pp of pulses) {
        pp.t += pp.sp * 0.02;
        const p = nodePos(nodes[pp.from], time), q = nodePos(nodes[pp.to], time);
        const x = p[0] + (q[0] - p[0]) * pp.t;
        const y = p[1] + (q[1] - p[1]) * pp.t;
        ctx.fillStyle = COL.pulse;
        ctx.shadowColor = COL.core;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(x, y, 2.4, 0, 6.283);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (pp.t >= 1 && pp.to === 0) halos.push({ r: unit * 0.05, a: 0.55 });
      }

      if (state === "speaking" && Math.random() < 0.05 + level * 0.12) {
        halos.push({ r: unit * 0.13, a: 0.42 });
      }
    }

    halos = halos.filter((h) => h.a > 0.015);
    for (const h of halos) {
      h.r += unit * 0.013;
      h.a *= 0.95;
      ctx.strokeStyle = COL.node2;
      ctx.globalAlpha = h.a;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(ox, oy, h.r, 0, 6.283);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    for (const n of nodes) {
      const [x, y] = nodePos(n, time);
      const breathe = 1 + Math.sin(time * 0.003 + n.jitter) * 0.12;
      const base = n.ring === 0 ? 9 : n.ring === 1 ? 4.2 : n.ring === 2 ? 3.3 : 2.5;
      const rad = base * breathe * (1 + level * (n.ring === 0 ? 0.95 : 0.5));

      const g = ctx.createRadialGradient(x, y, 0, x, y, rad * 3);
      g.addColorStop(0, n.ring === 0 ? COL.core : COL.node);
      g.addColorStop(1, "rgba(124,192,242,0)");
      ctx.fillStyle = g;
      ctx.globalAlpha = 0.45 + level * 0.4;
      ctx.beginPath();
      ctx.arc(x, y, rad * 3, 0, 6.283);
      ctx.fill();

      ctx.globalAlpha = 1;
      ctx.fillStyle = n.ring === 0 ? "#ffffff" : COL.node2;
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, 6.283);
      ctx.fill();
    }

    rafId = requestAnimationFrame(render);
  }

  function startLoop() {
    if (rafId) return;
    t0 = performance.now();
    rafId = requestAnimationFrame(render);
  }
  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  window.addEventListener("resize", () => {
    if (!overlay.classList.contains("hidden")) {
      resizeCanvas();
      buildNet();
      if (window.voiceAvatar) window.voiceAvatar.onResize();
    }
  });

  /* ---------------- เปิด / ปิด ---------------- */

  async function open() {
    if (!overlay.classList.contains("hidden")) return;
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    errEl.hidden = true;
    saidEl.textContent = "";
    replyEl.textContent = "";
    applyCC();
    document.body.classList.add("voice-open");

    resizeCanvas();
    buildNet();
    startLoop();
    if (window.voiceAvatar) window.voiceAvatar.onOpen();

    if (!SR) {
      showError("โหมดเสียงรองรับเฉพาะ Chrome, Edge และ Chrome บน Android");
      return;
    }
    rec = buildRec();
    setState("listening");
    await startMeter();
    await cartesiaConfig;
    if (state !== "off") startListening();
  }

  function close() {
    const wasOpen = !overlay.classList.contains("hidden");
    state = "off";
    speakSession++;
    stopAllTts();
    try { rec && rec.abort(); } catch {}
    rec = null;
    recRunning = false;
    if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
    if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
    if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
    analyser = null;
    stopLoop();
    if (window.voiceAvatar) window.voiceAvatar.onClose();
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    document.body.classList.remove("voice-open");
    if (wasOpen && typeof window.voiceSyncChat === "function") window.voiceSyncChat();
  }

  openBtn.addEventListener("click", open);
  exitBtn.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) close();
  });
})();

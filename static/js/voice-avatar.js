// โมดูลตัวละคร VRM (พนักงานร้าน) สำหรับหน้า /avatar
//
// รับสัญญาณ level (0–1, ระดับเสียงจริง) กับ state (listening/thinking/speaking/...) จากลูป
// render() ใน voice.js ผ่าน window.voiceAvatar.onFrame() — ไม่ต้องสร้าง audio pipeline ใหม่
//
// ถ้าโหลดไฟล์ .vrm ไม่สำเร็จ จะติด class "is-failed" ที่เวทีให้หน้าเว็บแสดงข้อความแจ้ง —
// โหมดเสียงยังคุยได้ตามปกติแม้ไม่มีตัวละคร
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

// ไฟล์ .vrm ที่ export จาก VRoid Studio (ไฟล์ .vroid เป็นไฟล์โปรเจกต์ เว็บโหลดตรงไม่ได้)
const VRM_URL = "/static/avatar/Avatar%20grooming.vrm";
// ท่าหลัก: Standing Idle (Mixamo) วนตลอดทุกสถานะ (ยืนรอ / ฟัง / คิด / พูด) — ปาก ตา กระพริบตา สีหน้า
// และท่าหัวตามบทสนทนายังทำด้วยโค้ดทับบนท่านี้
const ANIM_TALK_URL = "/static/avatar/anim/Standing%20Idle.fbx";
// ท่าเล่นแก้เบื่อ: สุ่มเล่น 1 ท่า "ครั้งเดียว" แล้วกลับไปยืนรอ — เฉพาะตอนลูกค้าเงียบไปนาน และนาน ๆ ครั้ง
const ANIM_FIDGET_URLS = [
  { name: "bashful", url: "/static/avatar/anim/Bashful.fbx" },
  { name: "yawn", url: "/static/avatar/anim/Yawn.fbx" },
];
// เดินเข้าฉาก: ครั้งแรกที่กด "เริ่มคุย" น้องหอมเดินมาจากซ้ายของกรอบ หยุดกลางเคาน์เตอร์ หันมาหาลูกค้า
// แล้วจึงโค้งทักทาย (voice.js รอ enter() ก่อนพูดคำทักทาย) — ไฟล์นี้มีการเคลื่อนที่จริง (ราว 1.5 ม. ใน 1.5 วิ)
const ANIM_ENTER_URL = "/static/avatar/anim/Female%20Stop%20Walking.fbx";
const ENTER_TURN_SEC = 0.6;     // หมุนตัวจากหันข้างมาหน้าตรงหลังหยุดเดิน
const ENTER_WAIT_MS = 4000;     // กดเริ่มคุยตอนไฟล์ท่ายังโหลดไม่เสร็จ: รอได้เท่านี้ แล้วให้ยืนประจำที่เลย
const FIDGET_AFTER_MS = 15000;               // ลูกค้าเงียบ (ไม่พูด ไม่มีคำตอบค้าง) นานเท่านี้ก่อนจะเริ่มมีท่าแก้เบื่อครั้งแรก
const FIDGET_GAP_MS = 20000;                 // ยังเงียบต่อ: ท่าถัดไปห่างจากท่าก่อนหน้า (นับจากเล่นจบ) เท่านี้

// Mixamo rig → VRM Humanoid bone names (มาตรฐานที่โปรเจกต์ VRM+Mixamo ทั่วไปใช้กัน)
const MIXAMO_VRM_RIG_MAP = {
  mixamorigHips: "hips", mixamorigSpine: "spine", mixamorigSpine1: "chest",
  mixamorigSpine2: "upperChest", mixamorigNeck: "neck", mixamorigHead: "head",
  mixamorigLeftShoulder: "leftShoulder", mixamorigLeftArm: "leftUpperArm",
  mixamorigLeftForeArm: "leftLowerArm", mixamorigLeftHand: "leftHand",
  mixamorigLeftHandThumb1: "leftThumbMetacarpal", mixamorigLeftHandThumb2: "leftThumbProximal",
  mixamorigLeftHandThumb3: "leftThumbDistal", mixamorigLeftHandIndex1: "leftIndexProximal",
  mixamorigLeftHandIndex2: "leftIndexIntermediate", mixamorigLeftHandIndex3: "leftIndexDistal",
  mixamorigLeftHandMiddle1: "leftMiddleProximal", mixamorigLeftHandMiddle2: "leftMiddleIntermediate",
  mixamorigLeftHandMiddle3: "leftMiddleDistal", mixamorigLeftHandRing1: "leftRingProximal",
  mixamorigLeftHandRing2: "leftRingIntermediate", mixamorigLeftHandRing3: "leftRingDistal",
  mixamorigLeftHandPinky1: "leftLittleProximal", mixamorigLeftHandPinky2: "leftLittleIntermediate",
  mixamorigLeftHandPinky3: "leftLittleDistal", mixamorigRightShoulder: "rightShoulder",
  mixamorigRightArm: "rightUpperArm", mixamorigRightForeArm: "rightLowerArm",
  mixamorigRightHand: "rightHand", mixamorigRightHandPinky1: "rightLittleProximal",
  mixamorigRightHandPinky2: "rightLittleIntermediate", mixamorigRightHandPinky3: "rightLittleDistal",
  mixamorigRightHandRing1: "rightRingProximal", mixamorigRightHandRing2: "rightRingIntermediate",
  mixamorigRightHandRing3: "rightRingDistal", mixamorigRightHandMiddle1: "rightMiddleProximal",
  mixamorigRightHandMiddle2: "rightMiddleIntermediate", mixamorigRightHandMiddle3: "rightMiddleDistal",
  mixamorigRightHandIndex1: "rightIndexProximal", mixamorigRightHandIndex2: "rightIndexIntermediate",
  mixamorigRightHandIndex3: "rightIndexDistal", mixamorigRightHandThumb1: "rightThumbMetacarpal",
  mixamorigRightHandThumb2: "rightThumbProximal", mixamorigRightHandThumb3: "rightThumbDistal",
  mixamorigLeftUpLeg: "leftUpperLeg", mixamorigLeftLeg: "leftLowerLeg",
  mixamorigLeftFoot: "leftFoot", mixamorigLeftToeBase: "leftToes",
  mixamorigRightUpLeg: "rightUpperLeg", mixamorigRightLeg: "rightLowerLeg",
  mixamorigRightFoot: "rightFoot", mixamorigRightToeBase: "rightToes",
};

// แปลง AnimationClip ของ Mixamo (กระดูกชื่อ "mixamorigXxx") ให้เล่นกับกระดูก VRM Humanoid ได้ —
// ต้องคูณด้วยการหมุนของ "ท่าเริ่มต้น" (rest pose) ทั้งของกระดูกเองและพ่อของมัน เพราะ Mixamo กับ VRM
// วาง T-pose อ้างอิงคนละมุมกัน ลอกท่ามาตรงๆ (copy quaternion ตรงๆ) จะได้ท่าบิดเพี้ยน ไม่ใช่ท่าที่ตั้งใจ
function remapMixamoAnimationToVrm(vrm, mixamoRoot, clip) {
  const tracks = [];
  const restRotationInverse = new THREE.Quaternion();
  const parentRestWorldRotation = new THREE.Quaternion();
  const _quatA = new THREE.Quaternion();
  const _vec3 = new THREE.Vector3();

  const motionHipsHeight = mixamoRoot.getObjectByName("mixamorigHips").position.y;
  const vrmHipsY = vrm.humanoid.getNormalizedBoneNode("hips").getWorldPosition(_vec3).y;
  const vrmRootY = vrm.scene.getWorldPosition(_vec3).y;
  const vrmHipsHeight = Math.abs(vrmHipsY - vrmRootY);
  const hipsPositionScale = vrmHipsHeight / motionHipsHeight;

  clip.tracks.forEach((track) => {
    const [mixamoRigName, propertyName] = track.name.split(".");
    const vrmBoneName = MIXAMO_VRM_RIG_MAP[mixamoRigName];
    const vrmNode = vrmBoneName && vrm.humanoid.getNormalizedBoneNode(vrmBoneName);
    const mixamoRigNode = mixamoRoot.getObjectByName(mixamoRigName);
    if (!vrmNode || !mixamoRigNode) return;

    if (track instanceof THREE.QuaternionKeyframeTrack) {
      mixamoRigNode.getWorldQuaternion(restRotationInverse).invert();
      mixamoRigNode.parent.getWorldQuaternion(parentRestWorldRotation);
      const values = track.values.slice();
      for (let i = 0; i < values.length; i += 4) {
        _quatA.fromArray(values, i);
        _quatA.premultiply(parentRestWorldRotation).multiply(restRotationInverse);
        _quatA.toArray(values, i);
      }
      tracks.push(new THREE.QuaternionKeyframeTrack(`${vrmNode.name}.${propertyName}`, track.times, values));
    } else if (track instanceof THREE.VectorKeyframeTrack) {
      const values = track.values.map((v) => v * hipsPositionScale);
      tracks.push(new THREE.VectorKeyframeTrack(`${vrmNode.name}.${propertyName}`, track.times, values));
    }
  });

  return new THREE.AnimationClip("vrmAnimation", clip.duration, tracks);
}

const stageEl = document.getElementById("voice-stage");
const fallbackCanvas = document.getElementById("voice-canvas");

if (stageEl && fallbackCanvas) {
  const canvas = document.createElement("canvas");
  canvas.id = "vrm-canvas";
  canvas.className = "voice__canvas hidden";
  fallbackCanvas.insertAdjacentElement("afterend", canvas);

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));

  const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 20);
  camera.position.set(0, 1.4, 1.7);

  const scene = new THREE.Scene();
  const keyLight = new THREE.DirectionalLight(0xfff3e4, 1.9); // แสงโทนอุ่นให้เข้ากับธีมร้าน
  keyLight.position.set(0.6, 1.8, 1.3);
  scene.add(keyLight);
  scene.add(new THREE.AmbientLight(0xfff8f0, 1.2));

  let vrm = null;
  let expr = null;
  let headBone = null;
  let spineBone = null;
  let chestBone = null;
  let rightUpperArmBone = null;
  let rightLowerArmBone = null;
  let neckBone = null;
  let lookAtTarget = null;
  let mixer = null; // ไม่เป็น null เมื่อโหลด animation clip จริงสำเร็จ — ตอนนั้นให้ mixer คุมท่าทาง
                     // ลำตัว/แขน/หัวแทนระบบ procedural ด้านล่าง (ปาก/ตา/กระพริบตายังใช้ระบบเดิม)
  // ท่าทาง: ยืนรอ (Standing Idle วนซ้ำ) เป็นหลัก + ท่าแก้เบื่อเล่นครั้งเดียวเป็นครั้งคราวตอนลูกค้าเงียบนาน
  let talkAction = null;
  let fidgetActions = []; // [{ name, action }]
  let fidget = null;      // ท่าแก้เบื่อที่กำลังเล่นอยู่ { name, action } หรือ null
  let lastFidget = "";
  let lastEngagedAt = performance.now();
  let nextFidgetAt = 0;   // เวลาเร็วสุดที่เล่นท่าแก้เบื่อครั้งถัดไปได้ (นับจากการเล่นครั้งก่อน)

  // เดินเข้าฉาก: ก่อนกดเริ่มคุย เคาน์เตอร์ว่าง (ซ่อนตัวละคร) · ผู้ใช้ตั้งค่าลดการเคลื่อนไหว = ไม่เดิน ยืนรอเลย
  const entranceWanted = stageEl.hasAttribute("data-always-on") &&
    !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  let walkAction = null;
  let walkPath = null;          // { times, dist } ระยะที่เดินไปข้างหน้าตามเวลาในท่า (ดึงออกจากท่าแล้วให้โค้ดเลื่อนตัวแทน)
  let walkTotal = 0;
  let entranceReady = false;    // ไฟล์ท่าเดินพร้อมแล้ว
  let entranceDone = !entranceWanted;
  let enterRequested = false;
  let entering = null;          // { phase: "walk" | "turn", t }
  const entranceWaiters = [];
  const clock = new THREE.Clock();

  let latestLevel = 0;
  let latestState = "off";

  // ปาก: แยกเป็น 5 รูปปาก (viseme) แทนที่จะอ้าปากเดียวตามความดังเบา — เลือกรูปที่เด่นที่สุดจาก
  // สเปกตรัมความถี่เสียงจริงที่กำลังเล่น (ดู onAudioSpectrum) แล้วไล่ค่าน้ำหนักเข้าหารูปนั้นทีละเฟรม
  const VISEMES = ["aa", "ih", "ou", "ee", "oh"];
  const visemeValue = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  let visemeTarget = "aa";
  let lastSpectrumAt = -Infinity;

  let blinkTimer = 2 + Math.random() * 2;
  let blinkValue = 0;
  let blinkClosing = false;
  // หน้า /avatar: ตัวละครยืนอยู่ตลอดตั้งแต่เปิดหน้า ไม่ต้องรอกดเริ่มคุย
  const alwaysOn = stageEl.hasAttribute("data-always-on");
  let running = alwaysOn;
  let rafId = 0;

  // "เหลียวมอง" เป็นช่วงๆ (หันหัว/ส่ายตา) — ไม่ใช่แค่สั่นค้างนิ่งๆ แบบเดิม
  let gazeYaw = 0, gazePitch = 0, gazeTimer = 1 + Math.random() * 2;

  // ---- ชั้น "ปฏิกิริยา" ตามบทสนทนา: สีหน้า + ท่าหัว/ลำตัว บวกทับท่าจาก animation clip ทุกเฟรม ----
  // สีหน้า: voice.js บอกอารมณ์ของคำตอบผ่าน setMood() แล้วไล่น้ำหนัก expression ของ VRM เข้าหาทีละเฟรม
  const MOOD_LEVEL = { happy: 0.55, relaxed: 0.32, sad: 0.65, surprised: 0.5 };
  const moodWeight = { happy: 0, relaxed: 0, sad: 0, surprised: 0 };
  let mood = "relaxed";
  // ท่าหัว: ค่าชดเชยที่ไล่เข้าหาเป้าหมายช้า ๆ (เอียงหัวตอนฟัง เงยมองตอนคิด) + พยักหน้า/โค้งเป็นครั้ง ๆ
  // HEAD_DOWN = ทิศของ rotation.x ที่ทำให้ก้มหน้าในโครงกระดูก normalized ของ VRM โมเดลนี้
  const HEAD_DOWN = 1;
  const pose = { hx: 0, hy: 0, hz: 0, eyeX: 0, eyeY: 0 };
  let nodT = -1, lastNodAt = 0, wasLoud = false;
  let bowT = -1;
  const NOD_DUR = 0.55, BOW_DUR = 1.5;

  // ท่าทางมือเล็กๆ ตอนพูดเน้นคำ (ยกแขนขวาขึ้นนิดหน่อยแล้ววาง)
  let gestureActive = false, gestureT = 0;
  const GESTURE_DUR = 0.9;
  const restRightUpperZ = Math.PI / 2 - 0.18;
  const restRightLowerZ = 0.12;

  function resize() {
    const r = stageEl.getBoundingClientRect();
    const w = Math.max(1, r.width);
    const h = Math.max(1, r.height);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  // จัดกล้องให้เห็นครึ่งตัว (หัวถึงเอว) โดยอิงตำแหน่งกระดูก "head"/"hips" จริง — ทำงานได้ไม่ว่า
  // โมเดลจะสัดส่วน/ท่ายืนแบบไหน เพราะคำนวณระยะจากขนาดจริงของตัวละคร ไม่ใช่ค่าคงที่เดา
  // follow = 1 จัดกล้องทันที, น้อยกว่า 1 = ค่อย ๆ เลื่อนตาม (ใช้ทุกเฟรมตอนมี animation ไม่ให้กล้องสั่นตามท่า)
  const _frameTarget = new THREE.Vector3();
  function frameOnHead(follow = 1) {
    if (!vrm || !vrm.humanoid) return;
    vrm.scene.updateMatrixWorld(true);
    const head = vrm.humanoid.getNormalizedBoneNode("head");
    if (!head) return;
    const hips = vrm.humanoid.getNormalizedBoneNode("hips");

    const headPos = new THREE.Vector3();
    head.getWorldPosition(headPos);
    const hipsPos = new THREE.Vector3();
    if (hips) hips.getWorldPosition(hipsPos);
    else hipsPos.set(headPos.x, headPos.y - 0.55, headPos.z);

    const topY = headPos.y + 0.24; // ประมาณกระหม่อม เหนือกระดูกหัวขึ้นไปอีกนิด
    const bottomY = hipsPos.y; // ระดับเอว
    const centerY = (topY + bottomY) / 2;
    const extentY = Math.max(0.4, topY - bottomY);

    const fovRad = (camera.fov * Math.PI) / 180;
    const margin = 1.18; // เผื่อขอบเฟรม ไม่ให้หัว/เอวชิดขอบจอเกินไป
    const distance = (extentY * margin) / (2 * Math.tan(fovRad / 2));

    _frameTarget.set(headPos.x, centerY, headPos.z + distance);
    camera.position.lerp(_frameTarget, follow);
    camera.lookAt(camera.position.x, camera.position.y, headPos.z);
  }

  // แยกสเปกตรัมความถี่เป็น 3 ย่าน (ต่ำ/กลาง/สูง) แล้วเดารูปปากที่ใกล้เคียงที่สุด — วิธีนี้ไม่ใช่การ
  // ถอดหน่วยเสียงจริง (ต้องมี phoneme timing จาก TTS ซึ่ง Cartesia ไม่ได้ส่งมาให้) แต่เพียงพอให้ปาก
  // เปลี่ยนรูปสลับกันจริงตามเสียงสระเปิด/ปิด/แหลม/ทุ้ม แทนที่จะอ้า-หุบรูปเดียวซ้ำๆ
  function classifyViseme(freqData, sampleRate) {
    const nyquist = sampleRate / 2;
    const binHz = nyquist / freqData.length;
    const bandAvg = (fromHz, toHz) => {
      const from = Math.max(0, Math.round(fromHz / binHz));
      const to = Math.min(freqData.length, Math.round(toHz / binHz));
      if (to <= from) return 0;
      let sum = 0;
      for (let i = from; i < to; i++) sum += freqData[i];
      return sum / (to - from) / 255;
    };
    const low = bandAvg(100, 500); // สระเปิด (aa/oh) — พลังงานย่านต่ำเด่น
    const mid = bandAvg(500, 1500); // สระกลม (ou/oh)
    const high = bandAvg(1500, 4000); // สระแหลม/ปากยิ้ม (ee/ih)

    const scores = {
      aa: low * (1 - high * 0.5),
      oh: mid * low,
      ou: mid * (1 - low * 0.3),
      ih: high * (1 - low * 0.3) * 0.7,
      ee: high * high,
    };
    let best = "aa", bestScore = -1;
    for (const name of VISEMES) {
      if (scores[name] > bestScore) { bestScore = scores[name]; best = name; }
    }
    return best;
  }

  // VRM โหลดมาเป็นท่า T-pose (แขนกางออกด้านข้าง) เสมอ ไม่มีอนิเมชันมาด้วย — หุบแขนลงข้างลำตัว
  // ให้เป็นท่ายืนพักธรรมชาติครั้งเดียวตอนโหลดเสร็จ (ไม่ใช่ค่า pose ที่ขยับทุกเฟรม)
  function relaxArms(v) {
    const bone = (name) => v.humanoid && v.humanoid.getNormalizedBoneNode(name);
    const leftUpper = bone("leftUpperArm");
    const rightUpper = bone("rightUpperArm");
    const leftLower = bone("leftLowerArm");
    const rightLower = bone("rightLowerArm");
    if (leftUpper) leftUpper.rotation.z = -(Math.PI / 2 - 0.18);
    if (rightUpper) rightUpper.rotation.z = Math.PI / 2 - 0.18;
    if (leftLower) leftLower.rotation.z = -0.12;
    if (rightLower) rightLower.rotation.z = 0.12;
  }

  // โหลด Mixamo FBX ไฟล์เดียว แล้ว retarget เป็น AnimationClip ที่เล่นกับ VRM ได้ — คืน null เฉยๆ
  // ถ้าพัง (ไม่ throw) เพื่อให้ผู้เรียกตัดสินใจ fallback เองได้ ไม่ทำให้ทั้งโมดูลล้ม
  function loadMixamoClip(url) {
    return new Promise((resolve) => {
      new FBXLoader().load(
        url,
        (mixamoRoot) => {
          const clip = THREE.AnimationClip.findByName(mixamoRoot.animations, "mixamo.com") || mixamoRoot.animations[0];
          resolve(clip ? remapMixamoAnimationToVrm(vrm, mixamoRoot, clip) : null);
        },
        undefined,
        (err) => {
          console.warn(`[voice-avatar] โหลด animation clip (${url}) ไม่สำเร็จ:`, err);
          resolve(null);
        }
      );
    });
  }

  // เล่นท่าแก้เบื่อ 1 ท่าแบบสุ่ม (ไม่ซ้ำท่าก่อนหน้า) ครั้งเดียว แล้ว "finished" จะพากลับไปท่ายืนรอ
  function playFidget(name) {
    if (!fidgetActions.length || fidget) return;
    const pool = name ? fidgetActions.filter((f) => f.name === name)
      : fidgetActions.length > 1 ? fidgetActions.filter((f) => f.name !== lastFidget) : fidgetActions;
    if (!pool.length) return;
    fidget = pool[Math.floor(Math.random() * pool.length)];
    lastFidget = fidget.name;
    fidget.action.reset().setEffectiveWeight(1).fadeIn(0.6).play();
    talkAction.fadeOut(0.6);
  }

  // กลับไปท่ายืนรอ — ทั้งตอนท่าแก้เบื่อเล่นจบเอง และตอนลูกค้าเริ่มพูดกลางท่า (ตัดกลับเร็วกว่า)
  function endFidget(fade = 0.6) {
    if (!fidget) return;
    fidget.action.fadeOut(fade);
    talkAction.reset().setEffectiveWeight(1).fadeIn(fade).play();
    fidget = null;
    nextFidgetAt = performance.now() + FIDGET_GAP_MS;
  }

  // ท่ายืนหลักต้องมี ส่วนท่าแก้เบื่อเป็น optional ทีละท่า — ท่าไหนโหลดไม่สำเร็จก็แค่ไม่อยู่ในตัวเลือก
  async function setupAnimations() {
    const talkClip = await loadMixamoClip(ANIM_TALK_URL);
    if (!talkClip) { showStanding(); return; } // ไม่มีท่ายืนหลัก ใช้ระบบท่าทาง procedural แทนทั้งหมด
    mixer = new THREE.AnimationMixer(vrm.scene);
    talkAction = mixer.clipAction(talkClip);
    talkAction.setLoop(THREE.LoopRepeat);
    talkAction.play();
    // จัดกล้องใหม่ตามท่าแรกของ animation (ท่า Idle ขยับตัวออกจากจุดเดิมของ T-pose ทำให้ตัวละครเยื้องข้าง)
    mixer.update(0);
    frameOnHead();

    if (!entranceDone) {
      const walkClip = await loadMixamoClip(ANIM_ENTER_URL);
      if (walkClip && prepareEntrance(walkClip)) {
        entranceReady = true;
        if (enterRequested && !entering) startEntrance();
      } else {
        showStanding(); // โหลดท่าเดินไม่ได้ — ยืนรอที่เคาน์เตอร์เหมือนก่อนมีฟีเจอร์นี้
      }
    }

    for (const { name, url } of ANIM_FIDGET_URLS) {
      const clip = await loadMixamoClip(url);
      if (!clip) continue;
      const action = mixer.clipAction(clip);
      action.setLoop(THREE.LoopOnce, 1);
      action.clampWhenFinished = true;
      fidgetActions.push({ name, action, duration: clip.duration });
    }
    mixer.addEventListener("finished", (e) => {
      if (fidget && e.action === fidget.action) endFidget();
    });
  }

  // แยก "การเดินไปข้างหน้า" ออกจากท่า: ท่าเหลือเป็นเดินอยู่กับที่ ส่วนระยะทางเก็บไว้ให้โค้ดเลื่อนตัวละครเอง
  // (ถ้าปล่อยไว้ในท่า พอเปลี่ยนเป็นท่ายืนตัวจะวาร์ปกลับจุดเดิม และหมุนตัวหันหน้าไม่ได้)
  function prepareEntrance(clip) {
    const hips = vrm.humanoid && vrm.humanoid.getNormalizedBoneNode("hips");
    const track = hips && clip.tracks.find((t) => t.name === `${hips.name}.position`);
    if (!track) return false;
    const v = track.values;
    const n = track.times.length;
    const x0 = v[0], z0 = v[2];
    walkPath = { times: track.times, dist: new Float32Array(n) };
    for (let i = 0; i < n; i++) {
      walkPath.dist[i] = v[i * 3 + 2] - z0; // Mixamo เดินไปทาง +Z ของตัวเอง
      v[i * 3] = x0;
      v[i * 3 + 2] = z0;
    }
    walkTotal = walkPath.dist[n - 1];
    if (!(walkTotal > 0.2)) return false;   // ไม่ใช่ท่าเดินไปข้างหน้า (เช่น ดาวน์โหลดแบบ In Place มา)
    walkAction = mixer.clipAction(clip);
    walkAction.setLoop(THREE.LoopOnce, 1);
    walkAction.clampWhenFinished = true;
    return true;
  }

  function walkDistanceAt(t) {
    const { times, dist } = walkPath;
    if (t <= times[0]) return dist[0];
    for (let i = 1; i < times.length; i++) {
      if (t <= times[i]) {
        const k = (t - times[i - 1]) / (times[i] - times[i - 1]);
        return dist[i - 1] + (dist[i] - dist[i - 1]) * k;
      }
    }
    return walkTotal;
  }

  // เริ่มเดิน: หันขวา (เดินไปทาง +X) เริ่มนอกกรอบด้านซ้าย แล้วหยุดพอดีจุดยืนประจำ (x = 0)
  function startEntrance() {
    stageEl.classList.remove("is-waiting");
    vrm.scene.rotation.y = Math.PI / 2;
    vrm.scene.position.x = -walkTotal;
    vrm.scene.visible = true;
    canvas.style.visibility = "";
    talkAction.stop();
    walkAction.reset().setEffectiveWeight(1).play();
    entering = { phase: "walk", t: 0 };
  }

  function updateEntrance(dt) {
    if (entering.phase === "walk") {
      const dur = walkAction.getClip().duration;
      vrm.scene.position.x = -walkTotal + walkDistanceAt(Math.min(walkAction.time, dur));
      if (walkAction.time >= dur - 1e-3 || !walkAction.isRunning()) {
        vrm.scene.position.x = 0;
        walkAction.fadeOut(ENTER_TURN_SEC);
        talkAction.reset().setEffectiveWeight(1).fadeIn(ENTER_TURN_SEC).play();
        entering = { phase: "turn", t: 0 };
      }
    } else {
      entering.t += dt;
      const p = Math.min(1, entering.t / ENTER_TURN_SEC);
      vrm.scene.rotation.y = (Math.PI / 2) * (1 - p * p * (3 - 2 * p));
      if (p >= 1) finishEntrance();
    }
  }

  // ยืนประจำที่ทันที — ใช้ตอนแตะข้าม, โหลดท่าเดินไม่ได้, หรือรอไฟล์นานเกินไป
  function showStanding() {
    if (vrm) {
      vrm.scene.visible = true;
      vrm.scene.rotation.y = 0;
      vrm.scene.position.x = 0;
    }
    canvas.style.visibility = "";
    if (walkAction) walkAction.stop();
    if (talkAction && !talkAction.isRunning()) talkAction.reset().setEffectiveWeight(1).play();
    finishEntrance();
  }

  function finishEntrance() {
    stageEl.classList.remove("is-waiting");
    canvas.style.visibility = "";
    if (vrm) {
      vrm.scene.rotation.y = 0;
      vrm.scene.position.x = 0;
    }
    entering = null;
    entranceDone = true;
    lastEngagedAt = performance.now();
    entranceWaiters.splice(0).forEach((resolve) => resolve());
  }

  // แตะที่ตัวละคร/เวทีระหว่างเดิน = ข้ามไปยืนประจำที่ (เหมือนพูดแทรก)
  stageEl.addEventListener("pointerdown", () => {
    if (entering) {
      walkAction.stop();
      talkAction.reset().setEffectiveWeight(1).play();
      finishEntrance();
    }
  });

  // ความคืบหน้าของท่าแก้เบื่อ 0..1 (ใช้ทำสีหน้าให้เข้ากับท่า เช่น อ้าปากหาว ยิ้มเขิน)
  function fidgetProgress() {
    return fidget ? Math.min(1, fidget.action.time / fidget.duration) : 0;
  }

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  loader.load(
    VRM_URL,
    (gltf) => {
      const loaded = gltf.userData.vrm;
      if (!loaded) throw new Error("ไฟล์นี้ไม่มีข้อมูล VRM");
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      VRMUtils.combineMorphs(loaded);
      loaded.scene.traverse((obj) => { obj.frustumCulled = false; });
      if (loaded.meta && loaded.meta.metaVersion === "0") VRMUtils.rotateVRM0(loaded);
      scene.add(loaded.scene);
      vrm = loaded;
      expr = vrm.expressionManager;
      const bone = (name) => vrm.humanoid && vrm.humanoid.getNormalizedBoneNode(name);
      headBone = bone("head");
      neckBone = bone("neck");
      spineBone = bone("spine");
      chestBone = bone("chest");
      rightUpperArmBone = bone("rightUpperArm");
      rightLowerArmBone = bone("rightLowerArm");
      relaxArms(vrm);

      // ตาเล็ง/มองมาทางกล้อง (ผู้ใช้) — ให้ความรู้สึกเหมือนสบตาคุยด้วย ไม่ใช่จ้องนิ่งไปทางเดียว
      lookAtTarget = new THREE.Object3D();
      scene.add(lookAtTarget);
      if (vrm.lookAt) vrm.lookAt.target = lookAtTarget;

      resize();
      frameOnHead();
      if (!entranceDone) {
        vrm.scene.visible = false;           // เคาน์เตอร์ว่าง รอลูกค้ากดเริ่มคุย
        canvas.style.visibility = "hidden";  // ซ่อนทั้งชั้น 3D ด้วย — ชั้น WebGL ที่ว่างทั้งผืนบางเบราว์เซอร์วาดภาพค้างทับฉาก
        stageEl.classList.add("is-waiting");
      }
      fallbackCanvas.classList.add("hidden");
      canvas.classList.remove("hidden");
      if (running) startRenderLoop();

      setupAnimations();
    },
    undefined,
    (err) => {
      console.warn("[voice-avatar] โหลดโมเดล VRM ไม่สำเร็จ:", err);
      stageEl.classList.add("is-failed");
      finishEntrance(); // ไม่มีตัวละคร — ให้ voice.js ทักทายต่อได้ ไม่ค้างรอ
    }
  );

  function tick() {
    rafId = requestAnimationFrame(tick);
    const dt = Math.min(0.1, clock.getDelta());
    if (!vrm) return;

    // ปาก: ตอนพูดและมีสเปกตรัมเสียงจริงมาไม่เกิน 250ms ที่แล้ว ใช้รูปปากที่แยกได้จริง (classifyViseme)
    // — ถ้าไม่มี (เช่น fallback เป็นเสียง browser ที่ดึงคลื่นเสียงมาวิเคราะห์ไม่ได้) ก็ยังอ้าปากตาม
    // ความดังเบาด้วยรูป "aa" เหมือนเดิม ไม่ให้ปากค้างนิ่งไปเฉยๆ
    const hasFreshSpectrum = performance.now() - lastSpectrumAt < 250;
    const speakingNow = latestState === "speaking";
    const activeViseme = speakingNow ? (hasFreshSpectrum ? visemeTarget : "aa") : null;
    const mouthOpen = speakingNow ? Math.min(1, latestLevel * 1.3) : 0;
    for (const name of VISEMES) {
      const target = name === activeViseme ? mouthOpen : 0;
      visemeValue[name] += (target - visemeValue[name]) * Math.min(1, dt * 14);
      if (expr) expr.setValue(name, visemeValue[name]);
    }

    // กระพริบตาแบบสุ่มเป็นจังหวะ ไม่ให้หน้านิ่งเป็นหุ่น
    if (!blinkClosing) {
      blinkTimer -= dt;
      if (blinkTimer <= 0) blinkClosing = true;
    }
    if (blinkClosing) {
      blinkValue += dt * 9;
      if (blinkValue >= 1) {
        blinkValue = 1;
        blinkClosing = false;
        blinkTimer = 2.4 + Math.random() * 2.6;
      }
    } else if (blinkValue > 0) {
      blinkValue = Math.max(0, blinkValue - dt * 9);
    }
    if (expr) expr.setValue("blink", blinkValue);

    const now = performance.now();
    updateMood(dt);

    if (mixer) {
      // "ผู้ใช้เริ่มพูด" เดาจากสัญญาณ level เดิม (voice.js ตั้ง level พุ่งขึ้นจริงตอน onspeechstart/
      // มีเสียงพูดเข้าไมค์ ไม่ใช่แค่ silence floor ~0.16-0.2 ตอนฟังเฉยๆ) — ไม่ต้องเพิ่มสัญญาณใหม่
      const userSpeaking = latestState === "listening" && latestLevel > 0.35;
      const engaged = userSpeaking || latestState === "speaking" || latestState === "thinking";
      if (engaged) {
        lastEngagedAt = now;
        if (fidget) endFidget(0.3); // ลูกค้าเริ่มพูด/บอทเริ่มตอบกลางท่า — กลับมายืนพร้อมคุยทันที
      } else if (entranceDone && !fidget && fidgetActions.length && now - lastEngagedAt > FIDGET_AFTER_MS && now >= nextFidgetAt) {
        playFidget();
      }

      // มี animation clip จริงแล้ว — ให้มันคุมลำตัว/แขน/หัวแทน ระบบ procedural ด้านล่างข้ามไปเลย
      // (ทั้งสองระบบตั้งค่า rotation ทับกันตรงๆ ถ้าปล่อยให้ทำงานพร้อมกันจะแย่งกันสั่นตี)
      mixer.update(dt);
      if (entering) {
        // กำลังเดินเข้าฉาก: กล้องอยู่นิ่งที่จุดยืนประจำ (ไม่ตามตัว) · ตามองไปทางที่เดิน จนหันมาหาลูกค้า
        updateEntrance(dt);
        if (lookAtTarget && headBone) {
          headBone.getWorldPosition(lookAtTarget.position);
          if (entering && entering.phase === "walk") lookAtTarget.position.x += 2;
          else lookAtTarget.position.copy(camera.position);
        }
      } else {
        // ท่า Idle ถ่ายน้ำหนักซ้าย-ขวา และท่าแก้เบื่อขยับตัวมากกว่า — ให้กล้องเลื่อนตามช้า ๆ ตัวละครอยู่กลางเฟรมเสมอ
        frameOnHead(Math.min(1, dt * 2));
        // ตายังต้องคอยเล็งกล้องเองเสมอ เพราะ animation clip ไม่ได้ควบคุมกระดูกตา
        if (lookAtTarget) lookAtTarget.position.copy(camera.position);
        applyConversationPose(dt, now); // ปฏิกิริยาตามบทสนทนา บวกทับท่าที่ clip ตั้งไว้เฟรมนี้
      }
    } else {
      const damp = Math.min(1, dt * 3);

      // เหลียวหัวเป็นช่วงๆ แบบสุ่ม (หันซ้าย/ขวา/ก้ม-เงยนิดหน่อย) สลับกับคลื่นสั่นเบาๆ ต่อเนื่อง
      // ให้ดูเหมือนมองไปรอบๆ จริง ไม่ใช่แค่โยกอยู่กับที่ท่าเดิม
      gazeTimer -= dt;
      if (gazeTimer <= 0) {
        gazeYaw = (Math.random() - 0.5) * 0.5;
        gazePitch = (Math.random() - 0.5) * 0.16;
        gazeTimer = 2.5 + Math.random() * 3.5;
      }
      const microYaw = Math.sin(now * 0.00042) * 0.05 + Math.sin(now * 0.00071 + 2.1) * 0.03;
      const microPitch = Math.sin(now * 0.00061 + 1.0) * 0.025;

      if (headBone) {
        const stateX =
          latestState === "listening" ? -0.05 :
          latestState === "thinking" ? 0.08 : 0.02;
        // พยักหน้าตามจังหวะคำพูดตอนกำลังพูด (ยิ่งเสียงดังยิ่งพยักชัด)
        const speakNod = latestState === "speaking" ? Math.sin(now * 0.012) * latestLevel * 0.05 : 0;
        const targetX = stateX + microPitch * 0.6 + gazePitch * 0.5 + speakNod;
        const targetY = gazeYaw + microYaw;
        const targetZ = Math.sin(now * 0.00048 + 0.4) * 0.02;
        headBone.rotation.x += (targetX - headBone.rotation.x) * damp;
        headBone.rotation.y += (targetY - headBone.rotation.y) * damp;
        headBone.rotation.z += (targetZ - headBone.rotation.z) * damp;
      }

      // ลำตัว: โยกถ่ายน้ำหนักเบาๆ + หายใจ ให้ท่ายืนดูมีชีวิต ไม่ใช่หุ่นนิ่ง
      if (spineBone) {
        spineBone.rotation.z = Math.sin(now * 0.00055) * 0.022;
        spineBone.rotation.y += (gazeYaw * 0.25 - spineBone.rotation.y) * Math.min(1, dt * 1.5);
      }
      if (chestBone) chestBone.rotation.x = Math.sin(now * 0.0013) * 0.015;

      // ตา: มองมาทางกล้องเป็นหลัก บวกทิศเดียวกับที่หัวกำลังเหลียวไปเล็กน้อยให้ดูสอดคล้องกัน
      if (lookAtTarget) {
        lookAtTarget.position.set(
          camera.position.x + gazeYaw * 0.4,
          camera.position.y + gazePitch * 0.3,
          camera.position.z
        );
      }

      // ท่ามือเล็กๆ ตอนพูดเน้นคำ: ยกแขนขวาขึ้นนิดแล้ววางกลับ ไม่ยิงถี่เกินไป
      if (!gestureActive && latestState === "speaking" && latestLevel > 0.6 && Math.random() < dt * 0.4) {
        gestureActive = true;
        gestureT = 0;
      }
      if (gestureActive && rightUpperArmBone && rightLowerArmBone) {
        gestureT += dt;
        const p = Math.sin(Math.min(1, gestureT / GESTURE_DUR) * Math.PI);
        rightUpperArmBone.rotation.z = restRightUpperZ - p * 0.3;
        rightUpperArmBone.rotation.x = -p * 0.2;
        rightLowerArmBone.rotation.z = restRightLowerZ - p * 0.25;
        if (gestureT >= GESTURE_DUR) {
          gestureActive = false;
          rightUpperArmBone.rotation.z = restRightUpperZ;
          rightUpperArmBone.rotation.x = 0;
          rightLowerArmBone.rotation.z = restRightLowerZ;
        }
      }
    }

    vrm.update(dt);
    renderer.render(scene, camera);
  }

  // สีหน้าตามสถานะ: ฟัง = ยิ้มบาง ๆ ตั้งใจฟัง · คิด = หน้าปกติ · พูด = ตามอารมณ์ของคำตอบ
  function updateMood(dt) {
    if (!expr) return;
    const st = latestState;
    let name = st === "speaking" ? mood : "relaxed";
    let level = st === "speaking" ? MOOD_LEVEL[mood] : st === "thinking" ? 0.1 : 0.22;
    if (fidget && fidget.name === "bashful") {
      name = "happy";
      level = 0.6;
    } else if (fidget && fidget.name === "yawn") {
      // หาว: อ้าปากช่วงกลางท่า หรี่ตาตาม (ทับค่าที่ระบบปาก/กะพริบตาตั้งไว้เฟรมนี้)
      const open = Math.sin(Math.min(1, Math.max(0, (fidgetProgress() - 0.15) / 0.55)) * Math.PI);
      expr.setValue("aa", Math.max(visemeValue.aa, open * 0.85));
      expr.setValue("blink", Math.max(blinkValue, open * 0.7));
      name = "relaxed";
      level = 0;
    }
    const k = Math.min(1, dt * 4);
    for (const m of Object.keys(moodWeight)) {
      const target = m === name ? level : 0;
      moodWeight[m] += (target - moodWeight[m]) * k;
      expr.setValue(m, moodWeight[m]);
    }
  }

  // ท่าตามบทสนทนา (โหมดที่มี animation clip): ค่าทั้งหมดบวกทับหลัง mixer.update เพราะ clip ตั้งท่าใหม่ทุกเฟรม
  function applyConversationPose(dt, now) {
    if (!headBone) return;
    const st = latestState;
    // ลูกค้าเริ่มพูด (เสียงเข้าไมค์ดังขึ้นหลังเงียบ) → พยักหน้ารับ 1 ครั้ง ไม่ถี่เกิน 1.8 วินาที
    const loud = st === "listening" && latestLevel > 0.35;
    if (loud && !wasLoud && now - lastNodAt > 1800) {
      nodT = 0;
      lastNodAt = now;
    }
    wasLoud = loud;

    let tx = 0, ty = 0, tz = 0, ex = 0, ey = 0;
    if (fidget) {
      // ท่าแก้เบื่อคุมหัวเอง
    } else if (st === "listening") {
      tx = HEAD_DOWN * 0.05; // โน้มหน้าเข้าหาลูกค้านิดหนึ่ง
      tz = 0.1;              // เอียงหัวเหมือนตั้งใจฟัง
    } else if (st === "thinking") {
      tx = -HEAD_DOWN * 0.12; // เงยหน้าเหมือนกำลังนึก
      ty = 0.2;
      tz = -0.06;
      ex = -0.45;             // เหลือบตาขึ้นไปด้านข้าง
      ey = 0.35;
    } else if (st === "speaking") {
      tx = HEAD_DOWN * Math.sin(now * 0.012) * latestLevel * 0.05; // พยักเบา ๆ ตามจังหวะคำพูด
    }
    const k = Math.min(1, dt * 4);
    pose.hx += (tx - pose.hx) * k;
    pose.hy += (ty - pose.hy) * k;
    pose.hz += (tz - pose.hz) * k;
    pose.eyeX += (ex - pose.eyeX) * k;
    pose.eyeY += (ey - pose.eyeY) * k;

    let nod = 0;
    if (nodT >= 0) {
      nodT += dt;
      nod = HEAD_DOWN * 0.16 * Math.sin(Math.min(1, nodT / NOD_DUR) * Math.PI);
      if (nodT >= NOD_DUR) nodT = -1;
    }
    let bow = 0;
    if (bowT >= 0) {
      bowT += dt;
      bow = Math.sin(Math.min(1, bowT / BOW_DUR) * Math.PI);
      if (bowT >= BOW_DUR) bowT = -1;
    }

    headBone.rotation.x += pose.hx + nod + HEAD_DOWN * 0.12 * bow;
    headBone.rotation.y += pose.hy;
    headBone.rotation.z += pose.hz;
    if (neckBone) neckBone.rotation.z += pose.hz * 0.4;
    if (spineBone) spineBone.rotation.x += HEAD_DOWN * 0.2 * bow;
    if (chestBone) chestBone.rotation.x += HEAD_DOWN * 0.1 * bow;
    if (lookAtTarget) {
      lookAtTarget.position.x += pose.eyeX;
      lookAtTarget.position.y += pose.eyeY;
    }
  }

  function startRenderLoop() {
    if (rafId) return;
    clock.start();
    tick();
  }
  function stopRenderLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  window.voiceAvatar = {
    // เดินเข้าฉาก (ครั้งแรกเท่านั้น) — resolve เมื่อหันหน้ามาหาลูกค้าแล้ว voice.js จึงเริ่มทักทาย
    enter() {
      if (entranceDone) return Promise.resolve();
      return new Promise((resolve) => {
        entranceWaiters.push(resolve);
        if (enterRequested) return;
        enterRequested = true;
        if (entranceReady) startEntrance();
        else setTimeout(() => { if (!entering && !entranceDone) showStanding(); }, ENTER_WAIT_MS);
      });
    },
    onOpen() {
      running = true;
      resize();
      if (vrm) startRenderLoop();
    },
    onClose() {
      latestState = "off";
      if (alwaysOn) return; // ยังยืนรอลูกค้าต่อ แค่เลิกฟัง/พูด
      running = false;
      stopRenderLoop();
    },
    onResize() {
      resize();
      frameOnHead();
    },
    onFrame(level, state) {
      latestLevel = level;
      latestState = state;
    },
    // อารมณ์ของคำตอบ: "happy" | "relaxed" | "sad" | "surprised" (voice.js เดาจากเนื้อหาคำตอบ)
    setMood(name) {
      if (MOOD_LEVEL[name] !== undefined) mood = name;
    },
    // ท่าครั้งเดียว: "bow" = โค้งทักทาย/ขอบคุณ ตอนเริ่มและจบการคุย
    gesture(name) {
      if (name === "bow") bowT = 0;
      else playFidget(name); // "bashful" | "yawn" — สั่งเล่นทันที (ใช้ตอนสาธิต/ทดสอบ)
    },
    onAudioSpectrum(freqData, sampleRate) {
      visemeTarget = classifyViseme(freqData, sampleRate);
      lastSpectrumAt = performance.now();
    },
  };

  if (alwaysOn) {
    window.addEventListener("resize", () => {
      resize();
      frameOnHead();
    });
  }
}

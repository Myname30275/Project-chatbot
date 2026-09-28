// โมดูลตัวละคร VRM สำหรับโหมดสนทนาด้วยเสียง — แทนที่ภาพโครงข่ายเซลล์ประสาทบน <canvas>
//
// รับสัญญาณ level (0–1, ระดับเสียงจริง) กับ state (listening/thinking/speaking/...) จากลูป
// render() เดิมใน voice.js ผ่าน window.voiceAvatar.onFrame() — ไม่ต้องสร้าง audio pipeline ใหม่
//
// ถ้าโหลดไฟล์ .vrm ไม่สำเร็จ (เช่น ยังไม่ได้วางไฟล์ / ไฟล์เสีย) จะไม่ทำอะไรเลย ปล่อยให้
// #voice-canvas (โครงข่ายเซลล์ประสาทเดิม) ทำงานต่อตามปกติ — โหมดเสียงต้องใช้งานได้แม้ไม่มีโมเดล
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const VRM_URL = "/static/avatar/AvatarSample_B.vrm";
const ANIM_TALK_URL = "/static/avatar/anim/talking.fbx";
const ANIM_THINKING_URL = "/static/avatar/anim/thoughtful-head-nod.fbx";
// ท่า "roam" — สลับกันวนแบบสุ่มตอนไม่มีการสนทนา/รอคำตอบ ให้ดูมีชีวิต
const ANIM_ROAM_URLS = [
  { name: "idle", url: "/static/avatar/anim/Idle.fbx" },
  { name: "angry", url: "/static/avatar/anim/Angry.fbx" },
  { name: "dance", url: "/static/avatar/anim/hip-hop-dancing.fbx" },
  { name: "laugh", url: "/static/avatar/anim/laugh.fbx" },
  { name: "boxing", url: "/static/avatar/anim/boxing.fbx" },
  { name: "phone", url: "/static/avatar/anim/talking-on-phone.fbx" },
];

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
  const keyLight = new THREE.DirectionalLight(0xcfe0ff, 2.4);
  keyLight.position.set(0.6, 1.8, 1.3);
  scene.add(keyLight);
  scene.add(new THREE.AmbientLight(0x445577, 1.2));

  let vrm = null;
  let expr = null;
  let headBone = null;
  let spineBone = null;
  let chestBone = null;
  let rightUpperArmBone = null;
  let rightLowerArmBone = null;
  let lookAtTarget = null;
  let mixer = null; // ไม่เป็น null เมื่อโหลด animation clip จริงสำเร็จ — ตอนนั้นให้ mixer คุมท่าทาง
                     // ลำตัว/แขน/หัวแทนระบบ procedural ด้านล่าง (ปาก/ตา/กระพริบตายังใช้ระบบเดิม)
  // เครื่องสถานะท่าทาง 3 โหมด: "roam" (วนท่าสุ่มตอนไม่มีการสนทนา) / "thinking" (กำลังรอคำตอบ AI) /
  // "talk" (ผู้ใช้เริ่มพูดแล้ว หรือ AI กำลังตอบ) — ดู enterMode()/tick() สำหรับตรรกะเปลี่ยนสถานะ
  let talkAction = null;
  let thinkingAction = null;
  let roamActions = []; // [{ name, action }]
  let currentRoamIndex = -1;
  let mode = "roam";
  let pendingTarget = null; // "talk" | "thinking" | null — รอท่า roam ปัจจุบันเล่นจบก่อนค่อยสลับ
  let lastEngagedAt = 0;
  const ROAM_RESUME_DELAY_MS = 5000; // นิ่งไม่มีการโต้ตอบนานเท่านี้ค่อยกลับไปวนท่าสุ่ม
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
  let running = false;
  let rafId = 0;

  // "เหลียวมอง" เป็นช่วงๆ (หันหัว/ส่ายตา) — ไม่ใช่แค่สั่นค้างนิ่งๆ แบบเดิม
  let gazeYaw = 0, gazePitch = 0, gazeTimer = 1 + Math.random() * 2;

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
  function frameOnHead() {
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

    camera.position.set(headPos.x, centerY, headPos.z + distance);
    camera.lookAt(headPos.x, centerY, headPos.z);
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

  // เล่นท่า roam ตัวถัดไปแบบสุ่ม (ไม่ซ้ำตัวก่อนหน้าถ้ามีให้เลือกมากกว่า 1) — เรียกตอนเริ่ม, ตอนท่า
  // roam ตัวเดิมเล่นจบรอบ (ยังไม่ถึงคิวสลับโหมด), หรือตอนกลับจาก talk/thinking เข้าสู่ roam อีกครั้ง
  function playNextRoam() {
    if (!roamActions.length) return;
    let idx = Math.floor(Math.random() * roamActions.length);
    if (roamActions.length > 1 && idx === currentRoamIndex) idx = (idx + 1) % roamActions.length;
    currentRoamIndex = idx;
    mode = "roam";
    roamActions.forEach((r, i) => {
      if (i === idx) r.action.reset().fadeIn(0.4).play();
      else r.action.fadeOut(0.4);
    });
    if (talkAction) talkAction.fadeOut(0.4);
    if (thinkingAction) thinkingAction.fadeOut(0.4);
  }

  function actionForMode(m) {
    if (m === "talk") return talkAction;
    if (m === "thinking") return thinkingAction || talkAction; // ไม่มีท่าคิดก็ใช้ท่าคุยแทนไปก่อน
    return null;
  }

  // เปลี่ยน mode จริงๆ (fade action เก่าออก/ใหม่เข้า) — ใช้ภายในเท่านั้น ไม่เช็คว่ามาจาก roam หรือไม่
  // (ผู้เรียกต้องแน่ใจแล้วว่าถึงจังหวะสลับจริง — ดู enterMode() สำหรับตอนเรียกจากภายนอก)
  function applyMode(targetMode) {
    if (mode === targetMode) return;
    const from = actionForMode(mode);
    const to = actionForMode(targetMode);
    mode = targetMode;
    if (from && from !== to) from.fadeOut(0.4);
    if (to) { to.reset(); to.fadeIn(0.4).play(); }
    frameOnHead(); // กลับไปใช้เฟรมกล้องนิ่งแบบเดิม (ไม่ต้องตามหัวทุกเฟรมแบบตอน roam)
  }

  // สลับเข้าโหมด "thinking"/"talk" — ถ้ากำลัง roam อยู่ แค่ตั้งคิวรอ (pendingTarget) ให้ท่า roam
  // ปัจจุบันเล่นจบก่อนค่อยสลับ ไม่ตัดกลางคัน แต่ถ้าอยู่ในโหมด thinking/talk อยู่แล้วสลับกันเองได้ทันที
  // (ทั้งคู่ถือว่า "กำลังอยู่ในบทสนทนา" อยู่แล้ว ไม่ใช่จังหวะที่ต้องรอ)
  function enterMode(targetMode) {
    if (mode === "roam") pendingTarget = targetMode;
    else applyMode(targetMode);
  }

  // ท่ายืนคุยหลักเป็นค่าบังคับต้องมี ส่วนท่าอื่นๆ (thinking, roam ทุกแบบ) เป็น optional ทีละท่า —
  // ท่าไหนโหลดไม่สำเร็จก็แค่ไม่อยู่ในตัวเลือก ไม่ทำให้ฟีเจอร์อื่นพัง
  async function setupAnimations() {
    const talkClip = await loadMixamoClip(ANIM_TALK_URL);
    if (!talkClip) return; // ไม่มีท่ายืนหลัก ใช้ระบบท่าทาง procedural แทนทั้งหมด
    mixer = new THREE.AnimationMixer(vrm.scene);
    talkAction = mixer.clipAction(talkClip);
    talkAction.setLoop(THREE.LoopRepeat);

    const thinkingClip = await loadMixamoClip(ANIM_THINKING_URL);
    if (thinkingClip) {
      thinkingAction = mixer.clipAction(thinkingClip);
      thinkingAction.setLoop(THREE.LoopRepeat);
    }

    for (const { name, url } of ANIM_ROAM_URLS) {
      const clip = await loadMixamoClip(url);
      if (!clip) continue;
      const action = mixer.clipAction(clip);
      action.setLoop(THREE.LoopOnce, 1);
      action.clampWhenFinished = true;
      roamActions.push({ name, action });
    }

    mixer.addEventListener("finished", (e) => {
      if (!roamActions.some((r) => r.action === e.action)) return; // talk/thinking เป็น LoopRepeat ไม่มี finished
      if (pendingTarget) {
        const target = pendingTarget;
        pendingTarget = null;
        applyMode(target); // mode ยังเป็น "roam" อยู่ตอนนี้จริงๆ (ท่า roam เพิ่งเล่นจบ) เลข fade ตรงนี้ได้เลย
      } else {
        playNextRoam();
      }
    });

    if (roamActions.length) playNextRoam();
    else applyMode("talk"); // ไม่มีท่า roam เลย ก็ใช้ท่าคุยเป็นค่าเริ่มต้นไปเลยเหมือนก่อนมีฟีเจอร์นี้
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
      fallbackCanvas.classList.add("hidden");
      canvas.classList.remove("hidden");
      if (running) startRenderLoop();

      setupAnimations();
    },
    undefined,
    (err) => {
      console.warn("[voice-avatar] โหลดโมเดล VRM ไม่สำเร็จ ใช้ภาพโครงข่ายเซลล์ประสาทแทน:", err);
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

    if (mixer) {
      // "ผู้ใช้เริ่มพูด" เดาจากสัญญาณ level เดิม (voice.js ตั้ง level พุ่งขึ้นจริงตอน onspeechstart/
      // มีเสียงพูดเข้าไมค์ ไม่ใช่แค่ silence floor ~0.16-0.2 ตอนฟังเฉยๆ) — ไม่ต้องเพิ่มสัญญาณใหม่
      const userSpeaking = latestState === "listening" && latestLevel > 0.35;
      const targetMode =
        latestState === "speaking" || userSpeaking ? "talk" :
        latestState === "thinking" ? "thinking" : null;
      if (targetMode) lastEngagedAt = now;

      if (targetMode && mode !== targetMode) {
        enterMode(targetMode); // roam: ตั้งคิวรอท่าปัจจุบันเล่นจบ / thinking<->talk: สลับได้ทันที
      } else if (!targetMode && mode !== "roam" && now - lastEngagedAt > ROAM_RESUME_DELAY_MS) {
        playNextRoam(); // เงียบไปสักพักแล้ว ไม่มีการโต้ตอบ กลับไปวนท่าสุ่มต่อ
      }

      // มี animation clip จริงแล้ว — ให้มันคุมลำตัว/แขน/หัวแทน ระบบ procedural ด้านล่างข้ามไปเลย
      // (ทั้งสองระบบตั้งค่า rotation ทับกันตรงๆ ถ้าปล่อยให้ทำงานพร้อมกันจะแย่งกันสั่นตี)
      mixer.update(dt);
      // ท่า roam (โดยเฉพาะท่าเต้น) เคลื่อนตัว/ก้มเงยแรงกว่าท่ายืนคุยเยอะ — กล้องที่จัดไว้ครั้งเดียว
      // ตอนเข้าโหมด talk จะตามไม่ทัน (หัวโผล่จนจอเต็มตอนก้ม) เลยต้องรีเฟรมทุกเฟรมระหว่าง roam
      if (mode === "roam") frameOnHead();
      // ตายังต้องคอยเล็งกล้องเองเสมอ เพราะ animation clip ไม่ได้ควบคุมกระดูกตา
      if (lookAtTarget) lookAtTarget.position.copy(camera.position);
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
    onOpen() {
      running = true;
      resize();
      if (vrm) startRenderLoop();
    },
    onClose() {
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
    onAudioSpectrum(freqData, sampleRate) {
      visemeTarget = classifyViseme(freqData, sampleRate);
      lastSpectrumAt = performance.now();
    },
  };
}

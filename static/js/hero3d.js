/* อุปกรณ์อาบน้ำ-ตัดขน 3 มิติรอบภาพน้องหมาแมวบนหน้าแรก (อ่างฟองสบู่ หวี อุ้งเท้า กรรไกร ไดร์เป่าขน ประกาย)
 *
 * ภาพวาดเดิม (hero-pets.webp) มีอุปกรณ์วาดติดอยู่สองข้าง — ไฟล์นี้สลับเป็นภาพที่ตัดเหลือเฉพาะน้อง ๆ
 * (hero-pets-only.webp) แล้ววาดอุปกรณ์เป็นวัตถุ 3 มิติที่ขยับได้ในตำแหน่งเดิม
 * - ลงสีแบบการ์ตูน (เงา 3 ระดับ) + เส้นขอบสีกรมท่าแบบเดียวกับเส้นของภาพวาด
 * - แต่ละชิ้นขยับตามหน้าที่: ฟองลอยขึ้นจากอ่าง กรรไกรขยับตัด ไดร์ส่ายเป่าลม ประกายกะพริบ
 * - โหลด three.js หลังหน้าโหลดเสร็จ · โหลดไม่ได้/ไม่มี WebGL = ใช้ภาพวาดเดิมทั้งภาพต่อไป (ไม่มีอะไรหาย)
 * - หยุดวาดเมื่อเลื่อนพ้นจอหรือสลับแท็บ · ผู้ใช้ตั้งค่าลดการเคลื่อนไหว = วาดภาพนิ่งครั้งเดียว
 */
const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js";
const PETS_ONLY = "/static/img/hero-pets-only.webp";
const LINE = 0x0f2f47;      // เส้นขอบของภาพวาด
const HONEY = 0xf9b15f;     // สีส้มน้ำผึ้งของอุปกรณ์ในภาพวาด
const HONEY_DEEP = 0xf0982f;
const WHITE = 0xffffff;

const art = document.querySelector(".hero__art");
const canvas = art && art.querySelector(".hero__3d");
const img = art && art.querySelector("img");

// ตำแหน่งเป็นสัดส่วนของกรอบภาพ (x, y จากมุมซ้ายบน) · size = สัดส่วนของความสูงกรอบภาพต่อ 1 หน่วยของวัตถุ
// ภาพน้อง ๆ กินช่วงกลางประมาณ x 0.20–0.80 อุปกรณ์จึงอยู่สองข้าง ตำแหน่งใกล้เคียงภาพวาดเดิม
const LAYOUT = [
  { kind: "comb", x: 0.085, y: 0.2, size: 0.055 },
  { kind: "paw", x: 0.168, y: 0.4, size: 0.036 },
  { kind: "basin", x: 0.1, y: 0.72, size: 0.085 },
  { kind: "sparkle", x: 0.83, y: 0.3, size: 0.04 },
  { kind: "scissors", x: 0.855, y: 0.66, size: 0.075 },
  { kind: "dryer", x: 0.935, y: 0.36, size: 0.075 },
  { kind: "paw", x: 0.925, y: 0.86, size: 0.034 },
];

function whenIdle(fn) {
  const run = () => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 2500 }) : setTimeout(fn, 600));
  if (document.readyState === "complete") run();
  else window.addEventListener("load", run, { once: true });
}

async function start() {
  let THREE, renderer;
  try {
    const pets = new Image();
    pets.src = PETS_ONLY;
    [THREE] = await Promise.all([import(THREE_URL), pets.decode()]);
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  } catch (err) {
    console.warn("[hero3d] ใช้ภาพวาดเดิม (โหลด three.js / WebGL / ภาพไม่ได้):", err);
    return;
  }
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));

  const scene = new THREE.Scene();
  // กล้องไม่มีระยะลึก หน่วยเป็นพิกเซลของกรอบภาพ: วางของตามตำแหน่งบนภาพได้ตรง ๆ
  const camera = new THREE.OrthographicCamera(0, 1, 0, -1, -600, 600);
  scene.add(new THREE.AmbientLight(0xffffff, 1.55));
  const sun = new THREE.DirectionalLight(0xffffff, 2.1);
  sun.position.set(-0.6, 1, 1.2);
  scene.add(sun);

  // ไล่เฉดแบบขั้นบันได 3 ระดับ = เงาแบบการ์ตูน ไม่ไล่เนียน
  const steps = new THREE.DataTexture(new Uint8Array([165, 220, 255]), 3, 1, THREE.RedFormat);
  steps.minFilter = steps.magFilter = THREE.NearestFilter;
  steps.needsUpdate = true;
  const toon = (color) => new THREE.MeshToonMaterial({ color, gradientMap: steps });
  const lineMat = new THREE.MeshBasicMaterial({ color: LINE, side: THREE.BackSide });

  // ชิ้นส่วน 1 ชิ้น = ตัวสี + เส้นขอบ (ตัวเดียวกันขยายเล็กน้อย วาดเฉพาะด้านใน)
  function part(geometry, color, thick = 0.1) {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geometry, toon(color)));
    const line = new THREE.Mesh(geometry, lineMat);
    line.scale.setScalar(1 + thick);
    g.add(line);
    return g;
  }
  const at = (obj, x, y, z = 0) => { obj.position.set(x, y, z); return obj; };
  const ball = new THREE.SphereGeometry(1, 24, 18);

  function pawShape(color) {
    const g = new THREE.Group();
    const main = part(ball, color, 0.1);
    main.scale.set(0.95, 0.8, 0.4);
    g.add(at(main, 0, -0.35));
    [[-0.95, 0.45], [-0.33, 0.95], [0.33, 0.95], [0.95, 0.45]].forEach(([x, y]) => {
      const toe = part(ball, color, 0.18);
      toe.scale.set(0.33, 0.4, 0.28);
      g.add(at(toe, x, y));
    });
    return g;
  }

  // แต่ละตัวคืน { obj, tick(t) } — tick ขยับชิ้นส่วนภายในตามหน้าที่ของของชิ้นนั้น
  const BUILD = {
    comb() {
      const g = new THREE.Group();
      g.add(at(part(new THREE.BoxGeometry(2.6, 0.5, 0.34), HONEY, 0.12), 0, 0.45));
      const tooth = new THREE.BoxGeometry(0.13, 0.85, 0.2);
      for (let i = 0; i < 9; i++) g.add(at(part(tooth, HONEY, 0.3), -1.08 + i * 0.27, -0.2));
      const wrap = new THREE.Group();
      wrap.add(g);
      return { obj: wrap, tick: (t) => { g.rotation.z = 0.5 + Math.sin(t * 1.6) * 0.14; g.rotation.y = Math.sin(t * 0.8) * 0.5; } };
    },
    paw() {
      const g = pawShape(HONEY_DEEP);
      g.rotation.z = -0.3;
      const wrap = new THREE.Group();
      wrap.add(g);
      return { obj: wrap, tick: (t, i) => { g.scale.setScalar(1 + Math.sin(t * 2 + i) * 0.07); g.rotation.y = Math.sin(t * 0.9 + i) * 0.5; } };
    },
    basin() {
      const g = new THREE.Group();
      g.add(part(new THREE.CylinderGeometry(1.2, 0.86, 1.0, 28), HONEY, 0.07));
      g.add(at(part(new THREE.CylinderGeometry(1.3, 1.3, 0.2, 28), WHITE, 0.07), 0, 0.56));
      [[-0.6, 0.78, 0.36], [0.05, 0.9, 0.46], [0.62, 0.8, 0.34], [-0.2, 0.75, 0.3]].forEach(([x, y, r], k) => {
        const foam = at(part(ball, WHITE, 0.16), x, y, 0.2 - k * 0.05);
        foam.scale.setScalar(r);
        g.add(foam);
      });
      const mark = at(pawShape(WHITE), 0, -0.05, 1.02);
      mark.scale.setScalar(0.26);
      g.add(mark);
      g.rotation.x = 0.28;
      // ฟองลอยขึ้นจากอ่าง 3 ลูก วนไปเรื่อย ๆ
      const bubbles = [0, 1, 2].map((k) => {
        const b = part(ball, 0xdff3fb, 0.2);
        b.userData = { phase: k / 3, x: [-0.55, 0.15, 0.75][k], r: [0.2, 0.27, 0.17][k] };
        return b;
      });
      const wrap = new THREE.Group();
      wrap.add(g, ...bubbles);
      return {
        obj: wrap,
        tick: (t) => {
          g.rotation.z = Math.sin(t * 1.1) * 0.05;
          for (const b of bubbles) {
            const p = (t * 0.28 + b.userData.phase) % 1;
            b.position.set(b.userData.x + Math.sin(p * 6.3 + b.userData.phase * 9) * 0.22, 1.25 + p * 2.3, 0.3);
            b.scale.setScalar(b.userData.r * (0.5 + p * 0.7) * (p > 0.85 ? (1 - p) / 0.15 : 1));
          }
        },
      };
    },
    sparkle() {
      const s = new THREE.Shape();
      const pts = 8;
      for (let i = 0; i < pts; i++) {
        const r = i % 2 ? 0.28 : 1;
        const a = (i / pts) * Math.PI * 2 + Math.PI / 2;
        if (i) s.lineTo(Math.cos(a) * r, Math.sin(a) * r);
        else s.moveTo(Math.cos(a) * r, Math.sin(a) * r);
      }
      const geo = new THREE.ExtrudeGeometry(s, { depth: 0.25, bevelEnabled: false });
      geo.center();
      const g = part(geo, HONEY_DEEP, 0.16);
      const wrap = new THREE.Group();
      wrap.add(g);
      return { obj: wrap, tick: (t) => { g.rotation.z = Math.sin(t * 1.3) * 0.4; g.scale.setScalar(0.75 + Math.abs(Math.sin(t * 1.7)) * 0.45); } };
    },
    scissors() {
      // สองขา: ใบมีดชี้ขึ้น ห่วงจับอยู่ล่าง หมุนรอบหมุดตรงกลางให้ขยับตัด
      const half = (side) => {
        const h = new THREE.Group();
        h.add(at(part(new THREE.BoxGeometry(0.26, 1.7, 0.1), 0xe8eef3, 0.2), 0, 0.95));
        h.add(at(part(new THREE.TorusGeometry(0.34, 0.11, 10, 22), LINE, 0), side * 0.3, -0.75));
        h.add(at(part(new THREE.BoxGeometry(0.2, 0.55, 0.1), LINE, 0), side * 0.12, -0.25));
        return h;
      };
      const a = half(1), b = half(-1);
      b.position.z = 0.12;
      const pin = at(part(new THREE.CylinderGeometry(0.13, 0.13, 0.3, 14), HONEY_DEEP, 0.2), 0, 0.1, 0.1);
      pin.rotation.x = Math.PI / 2;
      const g = new THREE.Group();
      g.add(a, b, pin);
      g.rotation.z = 0.35;
      const wrap = new THREE.Group();
      wrap.add(g);
      return { obj: wrap, tick: (t) => { const open = 0.14 + (Math.sin(t * 3.2) * 0.5 + 0.5) * 0.3; a.rotation.z = open; b.rotation.z = -open; g.rotation.y = Math.sin(t * 0.7) * 0.35; } };
    },
    dryer() {
      const g = new THREE.Group();
      const body = part(new THREE.CylinderGeometry(0.62, 0.62, 1.3, 24), HONEY, 0.08);
      body.rotation.z = Math.PI / 2;
      g.add(body);
      const nozzle = at(part(new THREE.CylinderGeometry(0.5, 0.4, 0.55, 22), HONEY_DEEP, 0.1), -0.9, 0);
      nozzle.rotation.z = Math.PI / 2;
      g.add(nozzle);
      g.add(at(part(new THREE.SphereGeometry(0.62, 20, 16), HONEY, 0.08), 0.62, 0));
      const handle = at(part(new THREE.BoxGeometry(0.42, 1.25, 0.42), HONEY, 0.14), 0.3, -1.0);
      handle.rotation.z = -0.22;
      g.add(handle);
      const dial = at(part(new THREE.CylinderGeometry(0.2, 0.2, 0.12, 14), WHITE, 0.2), 0.2, 0, 0.62);
      dial.rotation.x = Math.PI / 2;
      g.add(dial);
      // ลมที่เป่าออกจากปากไดร์: ก้อนขาวเล็ก ๆ วิ่งออกไปแล้วหดหาย
      const puffs = [0, 1, 2].map((k) => {
        const p = part(ball, WHITE, 0.25);
        p.userData = { phase: k / 3, y: [0.22, -0.05, -0.3][k] };
        return p;
      });
      g.add(...puffs);
      const wrap = new THREE.Group();
      wrap.add(g);
      return {
        obj: wrap,
        tick: (t) => {
          g.rotation.z = -0.5 + Math.sin(t * 1.4) * 0.16;
          g.rotation.y = Math.sin(t * 0.8) * 0.3;
          for (const p of puffs) {
            const k = (t * 0.9 + p.userData.phase) % 1;
            p.position.set(-1.35 - k * 1.5, p.userData.y * (1 + k), 0);
            p.scale.setScalar(0.16 * (1 - k) + 0.02);
          }
        },
      };
    },
  };

  const items = LAYOUT.map((spec, i) => {
    const built = BUILD[spec.kind]();
    scene.add(built.obj);
    return { ...spec, ...built, phase: i * 1.7 };
  });

  let w = 0, h = 0;
  function resize() {
    w = art.clientWidth;
    h = art.clientHeight;
    renderer.setSize(w, h, false);
    camera.right = w;
    camera.bottom = -h;
    camera.updateProjectionMatrix();
    for (const it of items) it.obj.scale.setScalar(it.size * h);
  }

  const pointer = { x: 0, y: 0 };
  window.addEventListener("pointermove", (e) => {
    pointer.x = e.clientX / window.innerWidth - 0.5;
    pointer.y = e.clientY / window.innerHeight - 0.5;
  }, { passive: true });

  function draw(t) {
    items.forEach((it, i) => {
      const unit = it.size * h;
      const bob = Math.sin(t * 0.9 + it.phase) * unit * 0.18;
      // ขยับตามเมาส์นิดเดียว ให้รู้สึกว่าของลอยอยู่หน้าภาพ
      it.obj.position.set(it.x * w + pointer.x * unit * 0.5, -(it.y * h) + bob - pointer.y * unit * 0.4, 0);
      it.tick(t, i);
    });
    renderer.render(scene, camera);
  }

  // พร้อมแล้วจึงสลับเป็นภาพเฉพาะน้อง ๆ (กรอบภาพสัดส่วนเดิม หน้าไม่กระตุก)
  img.src = PETS_ONLY;
  art.classList.add("is-3d");
  resize();
  draw(0);

  const still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let visible = true;
  let raf = 0;
  const t0 = performance.now();
  function loop() {
    raf = 0;
    if (!visible || document.hidden) return;
    draw((performance.now() - t0) / 1000);
    raf = requestAnimationFrame(loop);
  }
  const wake = () => { if (!still && !raf) raf = requestAnimationFrame(loop); };
  window.addEventListener("resize", () => { resize(); draw((performance.now() - t0) / 1000); });
  if (!still) {
    new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; wake(); }).observe(art);
    document.addEventListener("visibilitychange", wake);
    wake();
  }
}

if (art && canvas && img) whenIdle(start);

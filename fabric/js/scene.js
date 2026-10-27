// Three.js scene: renderer, camera orbit, team palette, the two cloths (geometry + shaders) and the pitch lines.
import * as THREE from '../lib/three.module.js';
import { M, CAM, W, H, PORTRAIT, P, clamp, NX, NY, NL } from './config.js';

// ------------------------------------------------------------------ scene
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('gl'), antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio || 1); renderer.setSize(W, H); renderer.setClearColor(0x000000, 0);
const scene = new THREE.Scene();
// portrait: the camera looks along the pitch (from behind one goal, slightly off-axis) and from higher up, so the pitch
// runs up the tall screen; its field of view and framing are fitted below, after the camera is placed
const VIEW = PORTRAIT ? { ...CAM, az: 1.5 * Math.PI + 0.35, el: 0.85 } : CAM;
const camera = new THREE.PerspectiveCamera(VIEW.fov, W / H, 10, 5000);
// the map sits MAP_SHIFT_Y px lower on screen (a view offset: everything projected with this camera, cards and tags
// included, moves with it)
camera.setViewOffset(W, H, 0, -P.MAP_SHIFT_Y, W, H);
// camera on its orbit; `turn` (radians) swings it around the pitch centre (half-time: 0 -> pi, the teams then attack
// the other way on screen). The light turns with it so the shading of the cloths stays the same.
let camTurn = -1;
// the viewer's own view on top of the scripted orbit (main.js: drag to turn and tilt, wheel / pinch to zoom)
const userView = { az: 0, el: 0, zoom: 1 };
function placeCamera(turn, force = false) {
  if (turn === camTurn && !force) return false; camTurn = turn;
  const { az, el: el0, dist, tx, tz } = VIEW; const c = Math.cos(turn), s = Math.sin(turn);
  const cx = tx * c + tz * s, cz = -tx * s + tz * c, a = az + turn + userView.az, el = clamp(el0 + userView.el, 0.12, 1.5);
  camera.position.set(cx + dist * Math.cos(el) * Math.sin(a), dist * Math.sin(el), cz + dist * Math.cos(el) * Math.cos(a));
  camera.zoom = userView.zoom;
  camera.lookAt(cx, 0, cz); camera.updateProjectionMatrix(); camera.updateMatrixWorld();
  return true;
}
// the light turns with the view, so the cloths keep their shading whichever way the map is turned
function lightFor(turn) { return new THREE.Vector3(...P.LIGHT).normalize().applyAxisAngle(new THREE.Vector3(0, 1, 0), turn + userView.az); }
function setUserView(v) {
  Object.assign(userView, v); placeCamera(camTurn, true);
  const L = lightFor(camTurn); for (const cl of cloths) cl.uniforms.uLight.value.copy(L);
}
placeCamera(0);
// portrait: field of view so the pitch (with 20 m of relief) fills the band between the scoreboard (top) and the
// momentum bar (bottom), then a view offset centres it in that band
function fitPortrait(top, bottom, margin = 0.84) {
  camera.clearViewOffset();
  const pts = []; for (const x of [-52.5, 52.5]) for (const z of [-34, 34]) for (const y of [0, 20]) pts.push(new THREE.Vector3(x, y, z));
  const ext = () => { let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (const p of pts) { const v = p.clone().project(camera); x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x); y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y); }
    return { x0, x1, y0, y1 }; };
  for (let k = 0; k < 3; k++) {   // projected size scales with tan(fov / 2)
    const e = ext(), need = Math.max((e.x1 - e.x0) / 2 / margin, (e.y1 - e.y0) / 2 / ((bottom - top) / H));
    camera.fov = 2 * Math.atan(Math.tan(camera.fov * Math.PI / 360) * need) * 180 / Math.PI; camera.updateProjectionMatrix();
  }
  const e = ext(), xMid = (1 + (e.x0 + e.x1) / 2) / 2 * W, yMid = (1 - (e.y0 + e.y1) / 2) / 2 * H;
  camera.setViewOffset(W, H, xMid - W / 2, yMid - (top + bottom) / 2, W, H);
}
if (PORTRAIT) fitPortrait(270, P.PULSE_Y - 80);
// ---- two independent cloths. Each is a full grid stretched over its own territory (u in 0..1 along X).
function makeCloth(colorHex, side) {
  const nTop = NX * NY;
  const edge = [];
  for (let i = 0; i < NX; i++) edge.push([i, 0, 0, -1]);
  for (let j = 0; j < NY; j++) edge.push([NX - 1, j, 1, 0]);
  for (let i = NX - 1; i >= 0; i--) edge.push([i, NY - 1, 0, 1]);
  for (let j = NY - 1; j >= 0; j--) edge.push([0, j, -1, 0]);
  const nV = nTop + edge.length * 2;
  const pos = new Float32Array(nV * 3), nor = new Float32Array(nV * 3), pitch = new Float32Array(nV * 2), sideA = new Float32Array(nV);
  const idx = [];
  for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) { const k = j * NX + i; if (i < NX - 1 && j < NY - 1) idx.push(k, k + NX, k + 1, k + 1, k + NX, k + NX + 1); }
  edge.forEach(([i, j, nx, nz], e) => { const kt = nTop + e * 2, kb = kt + 1; for (const k of [kt, kb]) { sideA[k] = 1; nor[k * 3] = nx * side; nor[k * 3 + 2] = nz; }
    const e2 = (e + 1) % edge.length; const kt2 = nTop + e2 * 2, kb2 = kt2 + 1; idx.push(kt, kb, kt2, kt2, kb, kb2); });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  geo.setAttribute('pitch', new THREE.BufferAttribute(pitch, 2)); geo.setAttribute('side', new THREE.BufferAttribute(sideA, 1)); geo.setIndex(idx);
  const topGeo = new THREE.BufferGeometry(); topGeo.setAttribute('position', new THREE.BufferAttribute(pos.subarray(0, nTop * 3), 3)); topGeo.setIndex(idx.slice(0, (NX - 1) * (NY - 1) * 6));
  const uniforms = {
    uColor: { value: new THREE.Color(colorHex) }, uSeam: { value: new Float32Array(NL).fill(52.5) }, uSide: { value: side }, uTopSide: { value: 1 },
    uLight: { value: new THREE.Vector3(...P.LIGHT).normalize() }, uBlackout: { value: 0 }, uDim: { value: 0 }, uSpot: { value: new THREE.Vector4(11, 34, 12, 0) }, uBox: { value: new THREE.Vector4(0, 13.84, 16.5, 54.16) }, uReveal: { value: new THREE.Vector4(0, 34, 0, 0) }, uFlash: { value: new THREE.Vector4(0, 0, 0, 0) },
    uTints: { value: Array.from({ length: 8 }, () => new THREE.Vector4(0, 0, 0, 0)) }, uTintStr: { value: new Float32Array(8) }, uHome: { value: homeCol }, uAway: { value: awayCol },
  };
  const mat = new THREE.ShaderMaterial({ uniforms, side: THREE.DoubleSide, vertexShader: VS, fragmentShader: FS });
  const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false; scene.add(mesh);
  return { side, geo, topGeo, pos, nor, pitch, edge, nTop, uniforms, mesh, h: new Float32Array(nTop), hT: new Float32Array(nTop), L: new Float32Array(NY), lines: null };
}
const homeCol = new THREE.Color(M.home.color), awayCol = new THREE.Color(M.away.color);
// team palette: every team-coloured element (cloths, pulse chart, markers, scoreboard, cards, sky lean) uses the colours
// that build_data.py read from <match>_match_info.csv, so another match gets its own colours with no code change
const hexRgb = (h) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const TC = { home: hexRgb(M.home.color), away: hexRgb(M.away.color) };
const rgbaT = (side, a) => `rgba(${TC[side].join(',')},${a})`;
const inkOn = (c) => (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 > 0.55 ? '#1a1a20' : '#fff';   // readable text on a team colour
const VS = `
    attribute vec2 pitch; attribute float side;
    varying vec2 vPitch; varying vec3 vN; varying float vH; varying float vSide; varying float vNy;
    void main(){ vNy = normal.y; vPitch = pitch; vSide = side; vH = position.y; vN = normalize(normalMatrix * normal);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const FS = `
    precision highp float;
    uniform float uSeam[${NL}]; uniform vec3 uColor, uHome, uAway, uLight; uniform float uBlackout, uDim, uSide, uTopSide; uniform vec4 uSpot, uBox, uReveal, uFlash;
    uniform vec4 uTints[8]; uniform float uTintStr[8];
    varying vec2 vPitch; varying vec3 vN; varying float vH; varying float vSide; varying float vNy;
    float seamAt(float Y){ float f = clamp(Y / 2.0, 0.0, float(${NL - 1}) - 0.001); int i = int(floor(f)); float a = f - floor(f);
      float p0 = 0.0, p1 = 0.0, p2 = 0.0, p3 = 0.0; for (int k = 0; k < ${NL}; k++) { if (k == max(i - 1, 0)) p0 = uSeam[k]; if (k == i) p1 = uSeam[k]; if (k == i + 1) p2 = uSeam[k]; if (k == min(i + 2, ${NL - 1})) p3 = uSeam[k]; }
      return 0.5 * ((2.0 * p1) + (-p0 + p2) * a + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * a * a + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * a * a * a); }
    void main(){
      vec3 base = uColor;
      vec2 c = vPitch * 2.0; float aa = clamp(1.9 - 1.6 * max(fwidth(c.x), fwidth(c.y)), 0.3, 1.0) * smoothstep(0.3, 0.7, abs(vNy)); float row = floor(c.y); vec2 cell = vec2(fract(c.x + 0.5 * mod(row, 2.0)), fract(c.y));
      vec2 d = cell - 0.5; float dome = mix(0.55, max(0.0, 1.0 - dot(d, d) * 4.4), aa); float stitch = dome * dome;
      float knit = 0.80 + 0.26 * dome;
      vec3 n = normalize(vN); vec3 L = normalize((viewMatrix * vec4(uLight, 0.0)).xyz);
      vec3 nb = normalize(n + vec3(-d.x, -d.y, 0.0) * 1.8 * dome * aa);
      float diff = max(dot(nb, L), 0.0); float hemi = 0.5 + 0.5 * n.y; float light = 0.3 * hemi + 0.7 * diff;
      vec3 shade = mix(uSide > 0.0 ? vec3(0.50, 0.55, 0.74) : vec3(0.64, 0.65, 0.72), vec3(1.0), clamp(light, 0.0, 1.0)) * mix(0.88, 1.24, light);
      vec3 col = base * shade * knit + vec3(0.06) * stitch * light;
      // shadow cast by the top cloth onto the bottom cloth just beyond the front
      float sX = seamAt(vPitch.y); float beyond = (vPitch.x - sX) * uSide; // >0 : this cloth lies past the seam (its front strip)
      if (uTopSide != uSide) col *= 1.0 - 0.35 * exp(-max(0.0, -beyond - 0.0) * max(0.0, -beyond) / 6.0) * step(-0.5, beyond + 3.5);
      for (int k = 0; k < 8; k++) { vec4 t = uTints[k]; if (t.z <= 0.0) continue; float r = length(vPitch - t.xy); float a = clamp(exp(-r / t.z) * uTintStr[k], 0.0, 1.0);
        vec3 tc = t.w > 0.5 ? uHome : uAway; col = mix(col, tc * shade * knit, a); }
      float hf = clamp((vH - 6.0) / 34.0, 0.0, 1.0); if (uSide > 0.0) col = mix(col, vec3(0.82, 0.80, 0.97), hf * hf * 0.85);
      if (uSide < 0.0) col *= 1.14;
      if (vSide > 0.5) col = base * 0.70 * knit;
      vec3 dark = vec3(0.02, 0.02, 0.045) * (0.6 + 0.9 * stitch);
      vec2 bq = max(max(uBox.xy - vPitch, vPitch - uBox.zw), 0.0); float bd = length(bq); float spot = uSpot.w * 0.8 * exp(-bd * bd / 10.0);
      float bo = uBlackout; if (uReveal.w > 0.5) bo *= smoothstep(uReveal.z - 14.0, uReveal.z, length(vPitch - uReveal.xy));
      col = mix(col, dark + vec3(0.95) * spot, bo);
      if (uFlash.w > 0.0) { // foul: flash at the spot, a ring running out, and the foul line lit across the pitch
        float a = uFlash.z; float r = length(vPitch - uFlash.xy); float R = 3.0 + 40.0 * a;
        float ring = exp(-pow((r - R) / 2.4, 2.0)) * (1.0 - a);
        float core = exp(-r * r / 18.0) * exp(-a * 5.0);
        float ln = exp(-pow((vPitch.x - uFlash.x) / 0.7, 2.0)) * (1.0 - a) * (1.0 - a);
        col += vec3(1.0, 0.98, 0.94) * uFlash.w * (0.55 * ring + 0.9 * core + 0.45 * ln); }
      col *= 1.0 - 0.5 * uDim;
      gl_FragColor = vec4(col, 1.0);
    }`;
const cloths = [makeCloth(M.home.color, 1), makeCloth(M.away.color, -1)];
const [BLUE, WHITE] = cloths;

// pitch lines (one set per cloth, clipped to its territory)
function pitchLines() {
  const segs = []; const add = (a, b) => segs.push([a, b]);
  const poly = (pts) => { for (let i = 0; i < pts.length - 1; i++) add(pts[i], pts[i + 1]); };
  const arc = (cx, cy, r, a0, a1, n = 24) => { const p = []; for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; p.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); } return p; };
  const sub = (pts) => { const out = []; for (let i = 0; i < pts.length - 1; i++) { const [x0, y0] = pts[i], [x1, y1] = pts[i + 1]; const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 1.0)); for (let k = 0; k < n; k++) out.push([x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n]); } out.push(pts[pts.length - 1]); return out; };
  const L = 105, Wd = 68;
  poly(sub([[0, 0], [L, 0], [L, Wd], [0, Wd], [0, 0]])); poly(sub([[L / 2, 0], [L / 2, Wd]])); poly(arc(L / 2, Wd / 2, 9.15, 0, Math.PI * 2, 72));
  for (const s of [1, -1]) {
    const x0 = s > 0 ? 0 : L, d = (v) => x0 + s * v;
    poly(sub([[x0, 13.84], [d(16.5), 13.84], [d(16.5), 54.16], [x0, 54.16]])); poly(sub([[x0, 24.84], [d(5.5), 24.84], [d(5.5), 43.16], [x0, 43.16]]));
    const a0 = s > 0 ? -0.925 : Math.PI - 0.925, a1 = s > 0 ? 0.925 : Math.PI + 0.925;
    poly(arc(d(11), Wd / 2, 9.15, a0, a1, 24)); poly(arc(d(11), Wd / 2, 0.35, 0, Math.PI * 2, 12));
    poly(arc(x0, 0, 1, s > 0 ? 0 : Math.PI / 2, s > 0 ? Math.PI / 2 : Math.PI, 6)); poly(arc(x0, Wd, 1, s > 0 ? -Math.PI / 2 : Math.PI, s > 0 ? 0 : 1.5 * Math.PI, 6));
  }
  poly(arc(L / 2, Wd / 2, 0.35, 0, Math.PI * 2, 12));
  return segs;
}
const lineSegs = pitchLines();
for (const c of cloths) {
  const lpos = new Float32Array(lineSegs.length * 6); const lgeo = new THREE.BufferGeometry(); lgeo.setAttribute('position', new THREE.BufferAttribute(lpos, 3));
  const col = c.side > 0 ? 0xffffff : 0xeef0f6; const lmat = new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: c.side > 0 ? 0.95 : 0.8 });
  const lines = new THREE.LineSegments(lgeo, lmat); lines.frustumCulled = false; scene.add(lines); c.lines = { lpos, lgeo, lmat };
}
const boLines = (() => { // full, unclipped pitch markings shown on the flat black pitch during a penalty
  const a = new Float32Array(lineSegs.length * 6); lineSegs.forEach(([p, q], k) => { a.set([p[0] - 52.5, 0.2, p[1] - 34, q[0] - 52.5, 0.2, q[1] - 34], k * 6); });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(a, 3));
  const m = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthTest: false }); const l = new THREE.LineSegments(g, m); l.renderOrder = 5; l.frustumCulled = false; scene.add(l); return m; })();
{ // ground outline (rest position)
  const g = new THREE.BufferGeometry(); const y = -P.THICK - 0.1;
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-52.5, y, -34, 52.5, y, -34, 52.5, y, 34, -52.5, y, 34, -52.5, y, -34]), 3));
  scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xc8ccd8, transparent: true, opacity: 0.55 })));
}

export { renderer, scene, camera, placeCamera, userView, setUserView, lightFor, TC, rgbaT, inkOn, cloths, BLUE, WHITE, lineSegs, boLines };

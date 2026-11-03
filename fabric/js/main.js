// Entry point: frame loop, seeking (scrub), play / pause, test hooks used by tools/*.js, ready signal.
import { M, W, RENDER_MODE, P, clamp } from './config.js';
import { PERIODS, MAX_MIN, clockText, chartMinute, stops, knots, T_FULLTIME, T_VIDEO_END, matchTime, videoTimeAt } from './timeline.js';
import { renderer, scene, camera, cloths, BLUE, WHITE, setUserView } from './scene.js';
import { seam, seamVel, state, PERCEES, buildStart } from './engine.js';
import { hills, computeTargets } from './relief.js';
import { integrate, step, updateGeometry } from './sim.js';
import { drawSky } from './sky.js';
import { cssVar, FONT_TEXT, FONT_MONO } from './fonts.js';
import { CH, cx, drawPulse } from './pulse.js';
import { $, ui, updateUI } from './ui.js';
import { showHowto, isHowtoOpen } from './howto.js';
const EN = new URLSearchParams(location.search).get('lang') === 'en';  // ?lang=en : the English pages of data-workers.com/en/
if (EN) { document.documentElement.lang = 'en'; const hw = document.getElementById('howto'); if (hw) hw.textContent = 'How to read'; const gal = document.getElementById('gallery'); if (gal) gal.innerHTML = '‹&nbsp;&nbsp;GALLERY'; }

// ------------------------------------------------------------------ frame
function frame(dt) { step(dt); updateGeometry(); drawSky(dt); drawPulse(state.T, state.t); updateUI(state.T, state.t); renderer.render(scene, camera); }
function settle(n) { const dt = 1 / 60; for (let i = 0; i < n; i++) { state.dt = dt; computeTargets(matchTime(0), 0); integrate(dt); } }
settle(240);
let simT = 0;

// ------------------------------------------------------------------ seeking (scrub on the momentum bar)
// The simulation is stateful (springs, low-passes, front clock), so a seek replays it from the start: the cheap scalar
// part (front, clocks, envelopes) for the whole way, the expensive cloth relief only for the last SEEK_FULL seconds,
// which is all it depends on (it relaxes with H_TAU = 0.2 s).
const SEEK_FULL = 1.5;
const copyVal = (v) => ArrayBuffer.isView(v) ? v.slice() : v instanceof Map ? new Map(v) : v instanceof Set ? new Set(v)
  : Array.isArray(v) ? v.slice() : (v && typeof v === 'object' && v.constructor === Object) ? JSON.parse(JSON.stringify(v)) : v;
const INIT = { state: Object.fromEntries(Object.entries(state).map(([k, v]) => [k, copyVal(v)])), seam: seam.slice(), seamVel: seamVel.slice(), h: cloths.map(c => c.h.slice()) };
function restoreInit() {
  for (const k of Object.keys(state)) if (!(k in INIT.state)) delete state[k];
  for (const [k, v] of Object.entries(INIT.state)) state[k] = copyVal(v);
  seam.set(INIT.seam); seamVel.set(INIT.seamVel); cloths.forEach((c, i) => c.h.set(INIT.h[i])); simT = 0;
}
function seekTo(tt) {
  tt = clamp(tt, 0, T_VIDEO_END); restoreInit();
  const dt = 1 / 60, tFull = Math.max(0, tt - SEEK_FULL);
  while (state.t < tFull - 1e-9) { const d = Math.min(dt, tFull - state.t); step(d, true); drawSky(d, false); }
  while (state.t < tt - 1e-9) { const d = Math.min(dt, tt - state.t); step(d); drawSky(d, false); }
  simT = state.t; updateGeometry(); drawSky(dt); drawPulse(state.T, state.t); updateUI(state.T, state.t); renderer.render(scene, camera);
}
// x on the momentum bar -> match time (inverse of cx(chartMinute(T)))
function matchTimeAtX(x) { const cm = clamp((x - CH.x0) / CH.pxm, 0, MAX_MIN); const p = PERIODS.find(p => cm <= p.nom1) || PERIODS[PERIODS.length - 1]; return Math.min(p.end, p.start + (cm - p.nom0) * 60); }
let scrubX = null, scrubbing = false;
if (!RENDER_MODE) {
  const el = document.createElement('div'); el.id = 'scrub';
  Object.assign(el.style, { position: 'absolute', left: (CH.x0 - 8) + 'px', top: (CH.y - 56) + 'px', width: (cx(MAX_MIN) - CH.x0 + 16) + 'px', height: '112px', cursor: 'ew-resize', pointerEvents: 'auto' });
  document.getElementById('ui').appendChild(el);
  const xOf = (e) => e.clientX - document.getElementById('stage').getBoundingClientRect().left;
  el.addEventListener('pointerdown', (e) => { scrubbing = true; el.setPointerCapture(e.pointerId); scrubX = xOf(e); });
  el.addEventListener('pointermove', (e) => { if (scrubbing) scrubX = xOf(e); });
  const end = () => { scrubbing = false; }; el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
}
window.__prog = M.prog;
// test hook: advance the simulation (light, no cloth relief) to video time t and expose the drawn front
window.__seekLight = (t) => { if (t < state.t) restoreInit(); while (state.t < t - 1e-9) { const d = Math.min(1 / 60, t - state.t); step(d, true); } state.seamNow = Array.from(seam); };
window.__percees = PERCEES; window.__buildStart = buildStart; window.__seekTo = seekTo; window.__videoTimeAt = videoTimeAt;
window.__seek = (t) => { while (simT < t - 1e-6) { const dt = Math.min(1 / 60, t - simT); step(dt); simT += dt; if (simT < t - 1e-6) drawSky(dt, false); if (simT >= t - 1e-6) { updateGeometry(); drawSky(dt); drawPulse(state.T, state.t); updateUI(state.T, state.t); renderer.render(scene, camera); } }
  if (t === 0) frame(0.0001); return { done: t > T_VIDEO_END, T: state.T, clock: clockText(state.T) }; };
window.__timeline = { knots, stops, T_FULLTIME, T_VIDEO_END };
// seam-only trace for fitting: mean seam per lane at `hz`, without geometry work
window.__state = state; window.__P = P;
window.__dbg = () => { const mx = (a) => { let m = 0; for (let k = 0; k < a.length; k++) if (a[k] > m) m = a[k]; return +m.toFixed(1); };
  return { t: state.t, T: state.T, flat: +state.flat.toFixed(2), lean: +state.lean.toFixed(2), dom: +(state.dom || 0).toFixed(3), top: state.topSide, hB: mx(BLUE.h), hW: mx(WHITE.h), seam: Array.from(seam).map(v => +v.toFixed(1)), hills: state.activeHills.map(a => [a.h.player.short, +a.q.A.toFixed(1), +a.q.sig.toFixed(1)]) }; };
// play / pause: the round button or the space bar freezes the match clock
let paused = false;
const playBtn = document.getElementById('play');
const togglePause = () => { paused = !paused; playBtn.classList.toggle('paused', paused); };
playBtn.addEventListener('click', togglePause);
window.addEventListener('keydown', (e) => { if (e.code === 'Space' && !isHowtoOpen()) { e.preventDefault(); togglePause(); } });
// "Comment lire": pauses the match while the notes are open, plays again on close if it was playing
{ const link = document.getElementById('howto');
  // the guide shows a frozen example frame: the peak of the biggest missed chance (highest xG) while both teams hold a
  // visible share of the pitch; on close the match goes back to where it was
  const exampleFrame = () => {
    const shots = window.__howtoShotT !== undefined ? M.shots.filter(s => s.T === window.__howtoShotT)   // (forced by tools/make_howto.js)
      : M.shots.filter(s => !s.goal).sort((a, b) => b.xg - a.xg).slice(0, 8);
    for (const s of shots) { const t = videoTimeAt(s.T) + 0.25; seekTo(t);
      const mean = Array.from(seam).reduce((a, b) => a + b, 0) / seam.length;
      if (mean > 18 && mean < 87 && (state.activeHills || []).some(a => a.h === s || (a.h.T === s.T && a.h.X === s.X))) return { t, shot: s }; }
    const s = shots[0]; if (s) { const t = videoTimeAt(s.T) + 0.25; seekTo(t); return { t, shot: s }; } return null; };
  const open = () => { if (isHowtoOpen()) return; const wasPlaying = !paused; if (wasPlaying) togglePause();
    showHowto(() => { if (wasPlaying && paused) togglePause(); }); };   // the generic picture: instant, nothing moves underneath
  // tools/make_howto.js: build the notes live on the current frame (frozen example) to make that picture
  window.__howtoLive = (generic = true) => { const ex = exampleFrame(); showHowto(() => {}, ex && { ...ex.shot, generic }, true); return ex && ex.t; };
  if (link) link.addEventListener('click', open);
  if (/howto=1/.test(location.search)) setTimeout(open, 600); }
// turning the map by hand: drag (mouse or one finger) turns it round and tilts it, the wheel or two fingers zoom;
// a double click / double tap or the "Vue d'origine" button go back to the default view. The match keeps playing.
if (!RENDER_MODE) {
  const gl = document.getElementById('gl'), btn = document.createElement('div');
  btn.id = 'viewbtn'; btn.textContent = EN ? 'Drag to rotate' : 'Glisser pour tourner'; document.getElementById('ui').appendChild(btn);   // not in the video renders
  const v = { az: 0, el: 0, zoom: 1 }, pts = new Map(); let pinch = null;
  const moved = () => v.az !== 0 || v.el !== 0 || v.zoom !== 1;
  const apply = () => {
    setUserView(v);
    if (paused) { updateUI(state.T, state.t); renderer.render(scene, camera); }   // a paused match is redrawn at once
    btn.textContent = moved() ? (EN ? 'Reset view' : 'Vue d’origine') : (EN ? 'Drag to rotate' : 'Glisser pour tourner'); btn.classList.toggle('on', moved());
  };
  const perPx = () => W / gl.getBoundingClientRect().width;   // stage pixels per screen pixel (the page can be scaled)
  gl.addEventListener('pointerdown', (e) => { gl.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); gl.classList.add('drag'); });
  gl.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId)) return;
    const [px, py] = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 1) { const k = perPx(); v.az -= (e.clientX - px) * k * 0.006; v.el = clamp(v.el + (e.clientY - py) * k * 0.004, -0.45, 0.9); apply(); }
    else if (pts.size === 2) { const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) { v.zoom = clamp(v.zoom * d / pinch, 0.6, 3); apply(); } pinch = d; }
  });
  const up = (e) => { pts.delete(e.pointerId); pinch = null; if (!pts.size) gl.classList.remove('drag'); };
  gl.addEventListener('pointerup', up); gl.addEventListener('pointercancel', up);
  gl.addEventListener('wheel', (e) => { e.preventDefault(); v.zoom = clamp(v.zoom * Math.exp(-e.deltaY * 0.0015), 0.6, 3); apply(); }, { passive: false });
  const reset = () => { v.az = 0; v.el = 0; v.zoom = 1; apply(); };
  gl.addEventListener('dblclick', reset);
  btn.addEventListener('click', () => { if (moved()) reset(); });
}
if (!RENDER_MODE) { let last = performance.now(); const loop = (now) => { const dt = Math.min(0.05, (now - last) / 1000); last = now;
    if (scrubX !== null) { seekTo(videoTimeAt(matchTimeAtX(scrubX))); scrubX = null; } else if (!paused && !scrubbing) frame(dt);
    requestAnimationFrame(loop); }; requestAnimationFrame(loop); }
frame(0.0001);
// ready for the renderer once the fonts are loaded (or have fallen back), so no frame shows a fallback swap
Promise.all(['400 12px', '700 12px'].map(w => document.fonts.load(`${w} ${FONT_TEXT}`)).concat([document.fonts.load(`700 11px ${FONT_MONO}`), document.fonts.load(`900 40px ${cssVar('--font-num') || 'Helvetica'}`)]))
  .catch(() => {}).then(() => document.fonts.ready).then(() => { window.__ready = true; });
console.log('timeline: full time at', T_FULLTIME.toFixed(2), 's, video end', T_VIDEO_END.toFixed(2));

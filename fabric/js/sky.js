// Background sky: colour of the dominant team, goal / penalty / full-time moods.
import { W, H, P, LIGHT_THEME, clamp, sm } from './config.js';
import { TC } from './scene.js';
import { state } from './engine.js';
import { territory } from './relief.js';

// ------------------------------------------------------------------ sky
const skyCtx = document.getElementById('sky').getContext('2d');
const mix3 = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
const rgb = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
const CALM = { c0: [178, 180, 192], c1: [84, 88, 110], c2: [14, 16, 24], warm: 0, navy: 0 };
const PAPER = [235, 231, 222];
function skyTargetLight(t) {
  const s = { c0: [252, 250, 245], c1: [228, 223, 212], c2: PAPER, warm: 0, navy: 0 };
  { const tc = TC[(state.dom || 0) > 0 ? 'home' : 'away'], k = Math.sqrt(clamp(Math.abs(state.dom || 0) / P.SKY_DOM_FULL, 0, 1));
    s.c0 = mix3(s.c0, mix3(tc, [255, 255, 255], 0.8), k * 0.6); s.c1 = mix3(s.c1, mix3(tc, PAPER, 0.55), k * 0.7); }
  const intro = sm(t / 5); s.c0 = mix3(PAPER, s.c0, intro); s.c1 = mix3(PAPER, s.c1, intro);
  const st = state.stop, ph = state.stopPhase;
  if (st && ph >= st.sched.flood - 0.2 && ph < (st.pen ? 3.6 : st.sched.unflood + 0.3) && st.goal.team === 'away') s.c1 = mix3(s.c1, [196, 200, 220], st.pen ? 0.8 : 0.2);
  if (state.bo > 0.01) { s.c0 = mix3(s.c0, [214, 210, 202], state.bo); s.c1 = mix3(s.c1, [190, 186, 178], state.bo); }
  if (state.ft > 0.01) { s.c0 = mix3(s.c0, [240, 237, 230], state.ft); s.c1 = mix3(s.c1, [222, 218, 210], state.ft); }
  return s;
}
function skyTarget(t) {
  if (LIGHT_THEME) return skyTargetLight(t);
  let s = { ...CALM };
  const lean = clamp((state.dom || 0) * 2.5, -1, 1); // sky leans toward the dominant force: + home, - away
  // the wider the gap (territory + momentum), the more the whole background takes the dominant team's colour
  { const tc = TC[(state.dom || 0) > 0 ? 'home' : 'away'], k = Math.sqrt(clamp(Math.abs(state.dom || 0) / P.SKY_DOM_FULL, 0, 1));   // full colour at |dom| >= SKY_DOM_FULL
    s.c0 = mix3(s.c0, mix3(tc, [255, 255, 255], 0.3), k * 0.7); s.c1 = mix3(s.c1, tc.map(v => v * 0.75), k * 0.9); s.c2 = mix3(s.c2, tc.map(v => v * 0.22), k * 0.75); }
  const intro = sm(t / 5); s.c0 = mix3([150, 150, 160], s.c0, intro); s.c1 = mix3([22, 26, 58], s.c1, intro); s.c2 = mix3([0, 0, 0], s.c2, intro);
  const st = state.stop, ph = state.stopPhase;
  if (st && ph >= st.sched.flood - 0.2 && ph < (st.pen ? 3.6 : st.sched.unflood + 0.3)) {
    if (st.goal.team === 'away') { const k = st.pen ? 1 : 0.2; s.warm = k; s.navy = k; s.c2 = mix3(s.c2, [0, 0, 8], k); s.c1 = mix3(s.c1, [34, 40, 78], k * 0.8); }
  }
  if (state.bo > 0.01) { s.c0 = mix3(s.c0, [18, 19, 28], state.bo); s.c1 = mix3(s.c1, [8, 10, 46], state.bo); s.c2 = mix3(s.c2, [0, 0, 0], state.bo); s.warm = Math.max(s.warm, 0.5 * state.bo); }
  if (state.ft > 0.01) { s.c0 = mix3(s.c0, [132, 131, 136], state.ft); s.c1 = mix3(s.c1, [40, 43, 56], state.ft); s.c2 = mix3(s.c2, [8, 9, 18], state.ft); }
  return s;
}
let ditherCanvas = null;
function ditherSky(ctx) { // fixed (seeded, static) +-1 LSB dither so the wide gradients do not band
  if (!ditherCanvas) { ditherCanvas = document.createElement('canvas'); ditherCanvas.width = 256; ditherCanvas.height = 256; const dc = ditherCanvas.getContext('2d'); const im = dc.createImageData(256, 256);
    let seed = 1234567; const rnd = () => (seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296;
    for (let k = 0; k < 256 * 256; k++) { const v = rnd() < 0.5 ? 0 : 255; im.data[k * 4] = im.data[k * 4 + 1] = im.data[k * 4 + 2] = v; im.data[k * 4 + 3] = 5; } dc.putImageData(im, 0, 0); }
  ctx.fillStyle = ctx.createPattern(ditherCanvas, 'repeat'); ctx.fillRect(0, 0, W, H);
}
function drawSky(dt, paint = true) {
  const tg = skyTarget(state.t);
  if (!state.sky) state.sky = JSON.parse(JSON.stringify(tg));
  const S = state.sky, k = 1 - Math.exp(-dt / 0.35);
  for (const key of ['c0', 'c1', 'c2']) S[key] = mix3(S[key], tg[key], k);
  S.warm += (tg.warm - S.warm) * k; S.navy += (tg.navy - S.navy) * k;
  if (!paint) return;
  const ctx = skyCtx; ctx.clearRect(0, 0, W, H); ctx.fillStyle = rgb(S.c2); ctx.fillRect(0, 0, W, H);
  ctx.save(); ctx.translate(W * 0.5, H * 0.53); ctx.scale(1, 0.8);
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, W * 0.64); g.addColorStop(0, rgb(S.c0)); g.addColorStop(0.22, rgb(mix3(S.c0, S.c1, 0.3))); g.addColorStop(0.55, rgb(S.c1)); g.addColorStop(1, rgb(S.c2, 0));
  ctx.fillStyle = g; ctx.fillRect(-W, -H * 2, W * 2, H * 4); ctx.restore();
  if (S.warm > 0.01) { const g2 = ctx.createRadialGradient(W * 0.86, H * 0.98, 0, W * 0.86, H * 0.98, W * 0.6); g2.addColorStop(0, rgb([70, 42, 68], 0.4 * S.warm)); g2.addColorStop(1, rgb([120, 50, 80], 0)); ctx.fillStyle = g2; ctx.fillRect(0, 0, W, H); }
  ditherSky(ctx);
  if (S.navy > 0.01) { const g3 = ctx.createRadialGradient(W * 0.12, H * 0.15, 0, W * 0.12, H * 0.15, W * 0.55); g3.addColorStop(0, rgb([22, 48, 140], 0.75 * S.navy)); g3.addColorStop(1, rgb([30, 50, 170], 0)); ctx.fillStyle = g3; ctx.fillRect(0, 0, W, H); }
}

export { rgb, drawSky };

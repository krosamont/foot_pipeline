// Momentum bar: curve, goals, substitutions and cards, cursor.
import { M, W, H, PORTRAIT, clamp, P } from './config.js';
import { BREAKS, MAX_MIN, dispMinute, chartMinute, stops, CARDS } from './timeline.js';
import { TC, rgbaT, inkOn } from './scene.js';
import { state, momSeries, momentumAt } from './engine.js';
import { rgb } from './sky.js';
import { FONT_TEXT } from './fonts.js';

// ------------------------------------------------------------------ pulse chart
const pulseCtx = document.getElementById('pulse').getContext('2d');
// the chart keeps its width: 90 or 120 minutes (portrait: from the play button to the right edge)
const CH = PORTRAIT ? { x0: 96, pxm: (W - 96 - 40) / MAX_MIN, y: P.PULSE_Y, amp: 0.5 } : { x0: 251, pxm: 9.08 * 90 / MAX_MIN, y: P.PULSE_Y, amp: 0.5 };
const cx = (m) => CH.x0 + CH.pxm * Math.min(m, MAX_MIN);
function drawPulse(T, t) {
  const ctx = pulseCtx; ctx.clearRect(0, 0, W, H); const cm = chartMinute(T);
  for (const br of BREAKS) if (cm >= br.nom) { ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(cx(br.nom) + 0.5, CH.y - 52); ctx.lineTo(cx(br.nom) + 0.5, CH.y + 56); ctx.stroke(); }   // a line at each period start
  const pts = []; for (const [m, v] of momSeries) { if (m > cm) break; pts.push([cx(m), CH.y - v * CH.amp]); }
  pts.push([cx(cm), CH.y - momentumAt(cm) * CH.amp]);
  if (pts.length > 1) {
    const fill = (sign, color) => { ctx.save(); ctx.beginPath(); ctx.rect(0, sign > 0 ? 0 : CH.y, W, sign > 0 ? CH.y : H - CH.y); ctx.clip();
      ctx.beginPath(); ctx.moveTo(pts[0][0], CH.y); for (const p of pts) ctx.lineTo(p[0], p[1]); ctx.lineTo(pts[pts.length - 1][0], CH.y); ctx.closePath(); ctx.fillStyle = color; ctx.fill(); ctx.restore(); };
    fill(1, rgbaT('home', 0.9)); fill(-1, rgbaT('away', 0.62));
    ctx.beginPath(); for (const p of pts) ctx.lineTo(p[0], p[1]); ctx.strokeStyle = 'rgba(255,255,255,0.95)'; ctx.lineWidth = 1.6; ctx.lineJoin = 'round'; ctx.stroke();
  }
  ctx.beginPath(); ctx.moveTo(CH.x0, CH.y + 0.5); ctx.lineTo(cx(cm), CH.y + 0.5); ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.lineWidth = 1; ctx.stroke();
  // cursor line first, so markers and names are drawn over it
  { const xc = cx(cm); ctx.strokeStyle = 'rgba(255,255,255,0.55)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(xc + 0.5, CH.y - 55); ctx.lineTo(xc + 0.5, CH.y + 55); ctx.stroke(); }
  // markers
  const dotted = (x, y0, y1, color) => { ctx.save(); ctx.setLineDash([1.5, 3]); ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(x + 0.5, y0); ctx.lineTo(x + 0.5, y1); ctx.stroke(); ctx.restore(); };
  const ball = (x, y, color) => { ctx.save(); ctx.fillStyle = color; ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; ctx.lineTo(x + 2.2 * Math.cos(a), y + 2.2 * Math.sin(a)); } ctx.closePath(); ctx.fill();
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; ctx.beginPath(); ctx.moveTo(x + 2.2 * Math.cos(a), y + 2.2 * Math.sin(a)); ctx.lineTo(x + 4.6 * Math.cos(a), y + 4.6 * Math.sin(a)); ctx.stroke(); } ctx.restore(); };
  for (const s of stops) { if (t < s.t0 + s.sched.score) continue; const [m] = dispMinute(s.goal.T); const x = cx(m); const home = s.goal.team === 'home'; const col = home ? M.home.color : M.away.color;
    dotted(x, home ? CH.y - 8 : CH.y + 8, home ? CH.y - 34 : CH.y + 34, col); ball(x, home ? CH.y - 42 : CH.y + 42, col); }
  // substitutions and cards, stacked away from the baseline (home above, away below)
  const evs = [...M.subs.map(e => ({ ...e, kind: 'sub' })), ...CARDS.map(e => ({ ...e, kind: e.kind === 'red' ? 'red' : 'yellow' }))].sort((a, b) => a.T - b.T);
  const stack = {};
  for (const e of evs) { if (e.T > T) continue; const [m] = dispMinute(e.T); const home = e.team === 'home'; const key = e.team + m; const n = stack[key] = (stack[key] || 0) + 1;
    const x = cx(m), y = home ? CH.y - 12 - n * 15 : CH.y + 12 + n * 15; const fresh = clamp(1 - (T - e.T) / 360, 0, 1);
    ctx.save();
    if (n === 1) { ctx.setLineDash([1, 2.5]); ctx.strokeStyle = home ? rgbaT('home', 0.55) : rgbaT('away', 0.45); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x + 0.5, CH.y + (home ? -4 : 4)); ctx.lineTo(x + 0.5, y + (home ? 7 : -7)); ctx.stroke(); ctx.setLineDash([]); }
    if (e.kind === 'sub') {
      ctx.fillStyle = home ? M.home.color : M.away.color; ctx.beginPath(); ctx.arc(x, y, 6.5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = inkOn(TC[e.team]); ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(x - 3.2, y - 1.6); ctx.lineTo(x + 2.4, y - 1.6); ctx.moveTo(x + 3.2, y + 1.6); ctx.lineTo(x - 2.4, y + 1.6); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x + 3.4, y - 1.6); ctx.lineTo(x + 1.4, y - 3.3); ctx.lineTo(x + 1.4, y + 0.1); ctx.fill();
      ctx.beginPath(); ctx.moveTo(x - 3.4, y + 1.6); ctx.lineTo(x - 1.4, y - 0.1); ctx.lineTo(x - 1.4, y + 3.3); ctx.fill();
    } else {
      ctx.translate(x, y); ctx.rotate(0.12); ctx.fillStyle = e.kind === 'red' ? '#e5383b' : '#f2c230'; ctx.shadowColor = 'rgba(0,0,0,0.35)'; ctx.shadowBlur = 3;
      ctx.beginPath(); ctx.roundRect(-3.5, -5.5, 7, 11, 1.5); ctx.fill(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    }
    if (fresh > 0) { const name = (e.player && (e.player.short || e.player)) || ''; const short = String(name).split(' ').slice(-1)[0];
      ctx.globalAlpha = Math.min(1, fresh * 3) * 0.95; ctx.font = `500 10px ${FONT_TEXT}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      // substitution: "↑ in  ↓ out" (green arrow for the player coming on, red for the one going off)
      const offShort = e.kind === 'sub' && e.off ? String(e.off).split(' ').slice(-1)[0] : '';
      const parts = e.kind === 'sub' ? [['↑ ', '#5fd68a'], [short, '#e4e6ee'], ...(offShort ? [['  ↓ ', '#ff6b6b'], [offShort, '#9ea3b5']] : [])] : [[short, '#e4e6ee']];
      const tw = parts.reduce((a, [txt]) => a + ctx.measureText(txt).width, 0);
      ctx.fillStyle = 'rgba(14,16,24,0.72)'; ctx.beginPath(); ctx.roundRect(x + 8, y - 7, tw + 8, 14, 3); ctx.fill();   // backing: lines behind never cross the names
      let px = x + 12; for (const [txt, col] of parts) { ctx.fillStyle = col; ctx.fillText(txt, px, y); px += ctx.measureText(txt).width; } }
    ctx.restore(); }
  const x = cx(cm);
  // the cursor dot carries the colour of the side currently pushing on the 3D map (same signal that drives the front)
  const push = clamp((state.dom || 0) * 6, -1, 1); const dc = push >= 0 ? TC.home : TC.away; const k = Math.abs(push);
  ctx.save(); ctx.shadowColor = `rgba(${dc},${0.8 * k})`; ctx.shadowBlur = 10 * k; ctx.fillStyle = `rgb(${dc.map(v => Math.round(255 + (v - 255) * k))})`;
  ctx.beginPath(); ctx.arc(x, CH.y, 4.5 + 1.5 * k, 0, Math.PI * 2); ctx.fill(); ctx.lineWidth = 1.2; ctx.strokeStyle = '#fff'; ctx.stroke(); ctx.restore();
}

export { CH, cx, drawPulse };

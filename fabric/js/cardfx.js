// Full-screen card effects (red pulse, yellow rain).
import { W, H, P, sm } from './config.js';
import { CARDS, videoTimeAt } from './timeline.js';
import { rgb } from './sky.js';
import { FONT_TEXT, FONT_MONO } from './fonts.js';

// ------------------------------------------------------------------ card effects
// a card drops in front of the pitch, spinning down with a glow; a red card pulses the screen red, a yellow card brings
// a short rain shower. Pure function of the video time t, so seeking shows the right frame.
const fxCanvas = document.getElementById('fx'), fx = fxCanvas.getContext('2d');
const CARD_TV = CARDS.map(c => ({ c, tv: videoTimeAt(c.T) }));
const hash = (i) => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
function drawCardFx(t) {
  fx.clearRect(0, 0, W, H);
  for (const { c, tv } of CARD_TV) {
    const age = t - tv; if (age < 0 || age > P.CARD_FX) continue;
    const red = c.kind === 'red', col = red ? [229, 56, 59] : [242, 194, 48];
    const inA = sm(age / 0.25), outA = 1 - sm((age - (P.CARD_FX - 0.6)) / 0.6), A = inA * outA;
    if (red) { // screen pulse: two red heartbeats from the edges
      const beat = Math.max(Math.exp(-(((age - 0.25) / 0.18) ** 2)), 0.7 * Math.exp(-(((age - 0.75) / 0.2) ** 2)));
      const g = fx.createRadialGradient(W / 2, H / 2, H * 0.25, W / 2, H / 2, H * 0.95); g.addColorStop(0, 'rgba(229,56,59,0)'); g.addColorStop(1, `rgba(229,56,59,${(0.55 * beat + 0.12) * A})`);
      fx.fillStyle = g; fx.fillRect(0, 0, W, H);
    } else { // rain: slanted streaks falling across the screen, heavier at first, under a slight darkening
      fx.fillStyle = `rgba(8,10,18,${0.28 * A})`; fx.fillRect(0, 0, W, H);
      fx.strokeStyle = `rgba(200,210,230,${0.55 * A})`; fx.lineWidth = 1.1; fx.beginPath();
      const n = 220;
      for (let i = 0; i < n; i++) { const sp = 900 + 700 * hash(i + 1), len = 14 + 22 * hash(i + 7);
        const x0 = hash(i + 3) * (W + 200) - 100, y = ((hash(i + 5) * H + age * sp) % (H + 60)) - 30, x = x0 - (y + 30) * 0.18;
        fx.moveTo(x, y); fx.lineTo(x - len * 0.18, y + len); }
      fx.stroke();
      for (let i = 0; i < 26; i++) { const ra = ((age * 1.6 + hash(i + 11)) % 1); const x = hash(i + 13) * W, y = H * (0.55 + 0.4 * hash(i + 17));   // splashes on the pitch
        fx.strokeStyle = `rgba(210,220,240,${0.35 * (1 - ra) * A})`; fx.beginPath(); fx.ellipse(x, y, 2 + 10 * ra, 0.8 + 3 * ra, 0, 0, Math.PI * 2); fx.stroke(); }
    }
    // the card: drops from above, spins down to a slight tilt, settles, then fades
    const drop = 1 - Math.exp(-age / 0.16), wob = Math.exp(-age / 0.5) * Math.sin(age * 14);
    const cx0 = W * 0.5, cy0 = H * 0.36 - 120 * (1 - drop), rot = (-0.6 + 0.48 * drop) + 0.06 * wob, sc = 1 + 0.25 * (1 - drop);
    fx.save(); fx.globalAlpha = A; fx.translate(cx0, cy0); fx.rotate(rot); fx.scale(sc, sc);
    fx.shadowColor = `rgba(${col},0.9)`; fx.shadowBlur = 38; fx.fillStyle = `rgb(${col})`;
    fx.beginPath(); fx.roundRect(-34, -48, 68, 96, 7); fx.fill();
    fx.shadowBlur = 0; const gl = fx.createLinearGradient(-34, -48, 34, 48); gl.addColorStop(0, 'rgba(255,255,255,0.45)'); gl.addColorStop(0.45, 'rgba(255,255,255,0.05)'); gl.addColorStop(1, 'rgba(0,0,0,0.12)');
    fx.fillStyle = gl; fx.beginPath(); fx.roundRect(-34, -48, 68, 96, 7); fx.fill(); fx.restore();
    // caption
    fx.save(); fx.globalAlpha = A * sm((age - 0.3) / 0.3); fx.textAlign = 'center'; fx.fillStyle = '#f2f3f7';
    fx.font = `700 11px ${FONT_MONO}`; fx.fillText(`${red ? 'CARTON ROUGE' : 'CARTON JAUNE'}${c.demo ? ' · DÉMO' : ''}`, cx0, H * 0.36 + 88);
    fx.font = `600 15px ${FONT_TEXT}`; fx.fillText(`${(c.player && (c.player.short || c.player)) || ''}  ${c.label || ''}`, cx0, H * 0.36 + 110); fx.restore();
  }
}

export { drawCardFx };

// One simulation step and the geometry update of each frame (incl. the camera turn at each break).
import * as THREE from '../lib/three.module.js';
import { P, clamp, sm, NX, NY, DX, NL } from './config.js';
import { BREAKS, stops, matchTime, videoTimeAt } from './timeline.js';
import { placeCamera, lightFor, cloths, BLUE, WHITE, lineSegs, boLines } from './scene.js';
import { seam, seamVel, laneAt, FOULS, state, integrateSeam } from './engine.js';
import { territory, worldX, heightAtCloth, computeTargets } from './relief.js';


function integrate(dt, light = false) {
  // the front is a damped force balance: each lane accelerates toward the data target, with inertia
  integrateSeam(dt);
  // progression waves: metres each lane has gained lately, per side (forward moves in normal play only; resets to a foul
  // or to the centre line, floods and the goal stops are not gains), fading over GAIN_TAU s. Kept up to date in light
  // steps too, so a seek gives the same waves.
  { const f = Math.exp(-dt / P.GAIN_TAU), play = state.seamMode === 'normal';
    for (let l = 0; l < NL; l++) { const v = play ? seamVel[l] * dt : 0;
      state.gainHome[l] = state.gainHome[l] * f + Math.max(0, v); state.gainAway[l] = state.gainAway[l] * f + Math.max(0, -v); } }
  if (light) return;
  const b = 1 - Math.exp(-dt / P.H_TAU); for (const c of cloths) for (let k = 0; k < c.h.length; k++) c.h[k] += (c.hT[k] - c.h[k]) * b;
}
function step(dt, light = false) { state.dt = dt; const t = state.t + dt; const T = matchTime(t); const T0 = state.T; state.t = t; state.T = T;
  for (const f of FOULS) if (f.T > T0 && f.T <= T) state.flash = { ...f, t0: t };
  // kick-off after a goal: the centre spot flashes and the halfway line lights up when play restarts
  for (const st of stops) { const e = st.t0 + st.dur; if (e > t - dt && e <= t) state.flash = { T: st.goal.T + 0.01, X: 52.5, Y: 34, kickoff: true, t0: t }; }
  computeTargets(T, t, light); integrate(dt, light); }

// ------------------------------------------------------------------ geometry update
// half-time: during the break the whole pitch swings round (eased), the second half is seen from the other side
// the half-time turn starts once the line is flat on the centre line (HALF_FLAT s after the whistle)
// (one half turn per break: 0 -> pi at half-time, -> 2 pi before extra time, -> 3 pi at the extra-time break)
function halfTurn(t) { let turn = 0; for (const br of BREAKS) { const a = videoTimeAt(br.end) + P.HALF_FLAT, b = videoTimeAt(br.start); turn += Math.PI * sm((t - a) / Math.max(0.5, b - a - 0.2)); } return turn; }
function updateGeometry() {
  const turn = halfTurn(state.t);
  if (placeCamera(turn)) { const L = lightFor(turn); for (const cl of cloths) cl.uniforms.uLight.value.copy(L); }
  for (const c of cloths) {
    const { pos, nor, pitch, edge, nTop } = c;
    for (let j = 0; j < NY; j++) { const L = c.L[j]; for (let i = 0; i < NX; i++) { const k = j * NX + i; const X = worldX(c, i / (NX - 1), L);
      pos[k * 3] = X - 52.5; pos[k * 3 + 1] = c.h[k]; pos[k * 3 + 2] = j * DX - 34; pitch[k * 2] = X; pitch[k * 2 + 1] = j * DX; } }
    edge.forEach(([i, j], e) => { const kt = nTop + e * 2, kb = kt + 1, k = j * NX + i; const h = c.h[k];
      pos[kt * 3] = pos[kb * 3] = pos[k * 3]; pos[kt * 3 + 2] = pos[kb * 3 + 2] = pos[k * 3 + 2]; pos[kt * 3 + 1] = h; pos[kb * 3 + 1] = h - P.THICK; pitch[kt * 2] = pitch[kb * 2] = pitch[k * 2]; pitch[kt * 2 + 1] = pitch[kb * 2 + 1] = pitch[k * 2 + 1]; });
    c.topGeo.computeVertexNormals(); { const na = c.topGeo.attributes.normal.array; if (c.side < 0) { for (let k = 0; k < nTop * 3; k++) nor[k] = -na[k]; } else nor.set(na.subarray(0, nTop * 3), 0); }
    c.geo.attributes.position.needsUpdate = true; c.geo.attributes.normal.needsUpdate = true; c.geo.attributes.pitch.needsUpdate = true;
    // lines clipped to this cloth's territory
    const { lpos, lgeo } = c.lines;
    lineSegs.forEach(([a, b], s) => { [a, b].forEach(([X, Y], e) => { const o = (s * 2 + e) * 3; const L = c.L[clamp(Math.round(Y / DX), 0, NY - 1)];
      const inside = c.side > 0 ? X <= L : X >= 105 - L; const Xc = inside ? X : (c.side > 0 ? L : 105 - L); const h = heightAtCloth(c, Xc, Y);
      lpos[o] = Xc - 52.5; lpos[o + 1] = (h === null ? 0 : h) + 0.12; lpos[o + 2] = Y - 34; }); });
    lgeo.attributes.position.needsUpdate = true; c.lines.lmat.opacity = (c.side > 0 ? 0.95 : 0.8) * (1 - 0.4 * state.ft) * (1 - state.bo);
    const u = c.uniforms; for (let l = 0; l < NL; l++) u.uSeam.value[l] = seam[l];
    { const fl = state.flash, a = fl ? (state.t - fl.t0) / P.FLASH_DUR : 9; if (a >= 0 && a < 1) u.uFlash.value.set(fl.X, fl.Y, a, 1); else u.uFlash.value.w = 0; }
    u.uBlackout.value = state.bo; u.uDim.value = state.ft; u.uSpot.value.w = state.reveal ? 0 : state.bo;
    if (state.reveal) u.uReveal.value.set(state.reveal[0], state.reveal[1], state.reveal[2], 1); else u.uReveal.value.w = 0; u.uTopSide.value = state.topSide;
    let n = 0; const setT = (X, Y, sig, team, str) => { if (n >= 8) return; u.uTints.value[n].set(X, Y, sig, team === 'home' ? 1 : 0); u.uTintStr.value[n] = str; n++; };
    for (const s of stops) { const env = state.goalEnv.get(s) || 0; if (env > 0.01) setT(s.goal.X, s.goal.Y, P.GOAL_R * 0.9, s.goal.team, env * 1.3); }
    // a shot tints the cloth in the shooter's colour only briefly (TINT_LIFE video s) and only while the line is close
    // to the shot spot (fades past TINT_NEAR m), so no stray coloured spot stays where the battle no longer is
    for (const { h, q } of state.activeHills) { if (h.tv === undefined) h.tv = videoTimeAt(h.T);
      const life = 1 - sm((state.t - h.tv - P.TINT_LIFE) / 0.8), near = Math.exp(-Math.max(0, Math.abs(laneAt(seam, h.Y) - h.X) - P.TINT_NEAR) / 6);
      const str = Math.min(1, q.A / 6) * Math.min(1, q.A / (h.A * q.decay + 1e-6)) * life * near;
      if (str > 0.02) setT(h.X, h.Y, q.sig * 1.2, h.team, str); }
    for (; n < 8; n++) u.uTints.value[n].set(0, 0, 0, 0);
  }
  boLines.opacity = 0.95 * state.bo * (state.reveal ? 1 - sm(state.reveal[2] / 60) : 1);
  // draw order: the bottom cloth first
  BLUE.mesh.renderOrder = state.topSide > 0 ? 1 : 0; WHITE.mesh.renderOrder = state.topSide > 0 ? 0 : 1;
}

export { integrate, step, updateGeometry };

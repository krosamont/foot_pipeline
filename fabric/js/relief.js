// Relief of the cloths: battle body, shot hills, advances, set pieces, counter-attack waves, goal spires, penalty reveal.
import { M, H, P, lp, clamp, sm, NX, NY, DX } from './config.js';
import { goals, stops, BREAKS, T_FULLTIME, currentStop, videoTimeAt, currentPenMiss } from './timeline.js';
import { cloths } from './scene.js';
import { seam, laneAt, lastRestart, lastFoul, state, PERCEES, wipes, seamTargets } from './engine.js';

// territory of each cloth per row: blue covers X in [0, LB], white covers [105-LW, 105]
// the top cloth reaches OVERLAP m past the line to cover the other cloth's lip; with the relief laid flat (kick-offs,
// breaks) there is no lip, the overlap goes to 0 and the visible border sits exactly on the line (52.5 m at a kick-off)
function territory(c, Y) { const s = laneAt(seam, Y); const top = (state.topSide === c.side); const o = top ? P.OVERLAP * clamp((state.calm ?? 1) * state.flat, 0, 1) : 0; return c.side > 0 ? clamp(s + o, 1, 105) : clamp(105 - s + o, 1, 105); }
function worldX(c, u, L) { return c.side > 0 ? u * L : 105 - u * L; }
function heightAtCloth(c, X, Y) { const L = c.L[clamp(Math.round(Y / DX), 0, NY - 1)]; const u = c.side > 0 ? X / L : (105 - X) / L; if (u < 0 || u > 1) return null;
  const fx = clamp(u * (NX - 1), 0, NX - 1.001), fy = clamp(Y / DX, 0, NY - 1.001); const i = Math.floor(fx), j = Math.floor(fy), a = fx - i, b = fy - j; const k = j * NX + i;
  return (c.h[k] * (1 - a) + c.h[k + 1] * a) * (1 - b) + (c.h[k + NX] * (1 - a) + c.h[k + NX + 1] * a) * b; }
function heightAt(X, Y) { const top = cloths.find(c => c.side === state.topSide), bot = cloths.find(c => c.side !== state.topSide); const h = heightAtCloth(top, X, Y); if (h !== null) return h; const h2 = heightAtCloth(bot, X, Y); return h2 === null ? 0 : h2; }
// a missed chance is a low hill (XG_BASE m, never tall: only goals are) whose WIDTH grows with its xG
const hills = M.shots.filter(s => !s.goal).map(s => ({ ...s, A: P.XG_BASE + P.XG_SCALE * s.xg, S1: P.HILL_W0 + P.HILL_WXG * s.xg }));
function hillParams(h, T) { const age = T - h.T; if (age < 0) return null; const decay = Math.exp(-age / P.HILL_TAU_A); if (decay < 0.02) return null; const g = 1 - Math.exp(-age / P.HILL_TAU_S);
  const s1 = h.S1 || P.HILL_S1; return { A: h.A * decay, sig: 0.5 * s1 + 0.5 * s1 * g, p: 1 + g, decay }; }
// add a radial bump (gaussian-like or cone) to a cloth's target field, in world coordinates
function addBumpTo(c, X0, Y0, R, fn, win) {
  const j0 = Math.max(0, Math.floor((Y0 - R) / DX)), j1 = Math.min(NY - 1, Math.ceil((Y0 + R) / DX));
  for (let j = j0; j <= j1; j++) { const Y = j * DX; const L = c.L[j]; const du = (NX - 1) / L;
    const uc = c.side > 0 ? X0 / L : (105 - X0) / L; const i0 = Math.max(0, Math.floor((uc - R / L) * (NX - 1))), i1 = Math.min(NX - 1, Math.ceil((uc + R / L) * (NX - 1)));
    for (let i = i0; i <= i1; i++) { const X = worldX(c, i / (NX - 1), L); const r = Math.hypot(X - X0, Y - Y0); if (r >= R) continue; let v = fn(r);
      if (win) v *= sm(X / 3) * sm((105 - X) / 3) * sm(Y / 3) * sm((68 - Y) / 3); c.hT[j * NX + i] += v; } }
}
// ---- relief of the advances: every on-ball action that moves a side up the pitch (pass received, carry, ...) lifts
// the cloth where it lands, higher with its xT (scaled by ADV_XT_REF) and the closer it is to the opponent goal;
// it rises in 0.15 s and settles back over ADV_TAU video seconds. Percée tips rise too (PERC_H, more with xG).
const goalProx = (side, X) => sm(((side > 0 ? X : 105 - X) - 40) / 60);   // 0 up to 40 m from own goal, 1 at the opponent goal
const ADV = (M.prog || []).map(([T, side, X, Y, xt = 0]) => { const k = Math.sqrt(clamp(xt / P.ADV_XT_REF, 0, 1));
  return { T, side, X, Y, A: P.ADV_H * (0.4 + 0.6 * goalProx(side, X)), R: P.ADV_R + P.ADV_RX * k, k }; })   // height: closeness to goal; WIDTH: xT
  .filter(a => a.A > 1 && (a.k > 0.1 || goalProx(a.side, a.X) > 0.3)).map(a => ({ ...a, tv: videoTimeAt(a.T) }));
// set pieces and shots lift a broad area: a corner / free kick raises a wide dome where the ball is sent (a free kick
// more the closer it is to goal), a shot a wide base under its spike; each rises in 0.2 s and settles over SET_TAU s
const SETP = (M.setpieces || []).map(c => { const side = c.team === 'home' ? 1 : -1;
  const A = c.kind === 'corner' ? P.SET_H_CORNER : P.SET_H_FK * goalProx(side, c.X2); return { ...c, side, A, tv: videoTimeAt(c.T) }; }).filter(c => c.A > 1);
const SHOTB = M.shots.filter(s => !s.goal).map(s => ({ X: s.X, Y: s.Y, side: s.team === 'home' ? 1 : -1, A: P.SHOT_BASE * (0.5 + goalProx(s.team === 'home' ? 1 : -1, s.X)), tv: videoTimeAt(s.T) }));
// tackles won lift the cloth where the ball was won (TACKLE_H m, TACKLE_R m wide), wherever on the pitch
const TACK = (M.tackles || []).map(([T, side, X, Y]) => ({ T, side, X, Y, A: P.TACKLE_H, R: P.TACKLE_R, tv: videoTimeAt(T) }));
function addAdvanceRelief(t) {
  for (const list of [SETP, SHOTB]) for (const a of list) { const age = t - a.tv; if (age < -0.2 || age > 4 * P.SET_TAU) continue;
    if (wipes.some(x => x >= a.tv - 0.01 && t >= x)) continue;
    const A = a.A * state.flat * (age < 0 ? sm((age + 0.2) / 0.2) : Math.exp(-age / P.SET_TAU)); if (A < 0.05) continue;
    const X = a.X2 ?? a.X, Y = a.Y2 ?? a.Y, R = list === SETP ? P.SET_R : P.SHOT_BASE_R, w = R / 2.2;
    for (const c of cloths) addBumpTo(c, X, Y, R, r => A * Math.exp(-((r / w) ** 2)), true); }
  const R = P.ADV_R, w = R / 2.5;
  for (const a of [...ADV, ...TACK]) { const age = t - a.tv; if (age < -0.15 || age > 4 * P.ADV_TAU) continue;
    if (wipes.some(x => x >= a.tv - 0.01 && t >= x)) continue;
    const A = a.A * state.flat * (age < 0 ? sm((age + 0.15) / 0.15) : Math.exp(-age / P.ADV_TAU)); if (A < 0.05) continue;
    const Ra = a.R, wa = Ra / 2.5; for (const c of cloths) addBumpTo(c, a.X, a.Y, Ra, r => A * Math.exp(-((r / wa) ** 2)), true); }
  for (const e of PERCEES) { if (!(e.env > 0)) continue; const A = state.flat * P.PERC_H * e.env * (0.4 + goalProx(e.side, e.X)) + P.PERC_XG * e.env * (e.xg || 0);
    const Rp = R * 1.2 + P.PERC_WXG * (e.xg || 0), wp = Rp / 2.5;   // wider for bigger chances, never taller
    for (const c of cloths) addBumpTo(c, e.X, e.Y, Rp, r => A * Math.exp(-((r / wp) ** 2)), true); }
}
// light = true skips the per-vertex cloth relief (the expensive part) but keeps every scalar state up to date;
// used to fast-forward when seeking, the relief only depends on its last ~1 s (H_TAU low-pass)
function computeTargets(T, t, light = false) {
  const stop = currentStop(t); const phase = stop ? t - stop.t0 : -1; state.stop = stop; state.stopPhase = phase;
  seamTargets(T, t);
  const uAf = stop && (stop.pen ? stop.sched.unflood : P.UNFLOOD_AT);
  const inStop = stop && ((stop.pen && phase >= stop.sched.boOn + 0.1 && phase < stop.sched.flatUntil) || (phase >= uAf && phase < stop.dur));
  const flatTar = inStop ? 0 : 1; state.flat = lp(state.flat, flatTar, flatTar < state.flat ? 0.3 : 1.2, state.dt);
  // relief: the dominant force (more territory) swells into a broad body and rides over the front;
  // the pushed cloth stays low and folds up into a lip where it is being pressed
  const strength = P.STR_FLOOR + (1 - P.STR_FLOOR) * Math.min(1, Math.abs(state.dom) * P.STR_GAIN);
  if (!light) for (const c of cloths) {
    c.hT.fill(0); const top = state.topSide === c.side;
    for (let j = 0; j < NY; j++) {
      const Y = j * DX; const L = territory(c, Y); c.L[j] = L;
      const wy = P.EDGE_Y + (1 - P.EDGE_Y) * sm(Y / P.PIN_Y) * sm((68 - Y) / P.PIN_Y);
      const H = P.TOP_H * strength * (0.55 + 0.45 * sm(L / 55));
      for (let i = 0; i < NX; i++) {
        const u = i / (NX - 1); const a = u * L, df = (1 - u) * L; let h;
        if (top) {
          const ridge = Math.exp(-(((df - P.PEAK_D) / P.PEAK_S) ** 2)); const back = P.EDGE_X + (1 - P.EDGE_X) * sm(a / P.RISE_A);
          const body = (P.FRONT_F + (1 - P.FRONT_F) * sm(df / P.FRONT_W)) * Math.max(back * P.BACK_LV, ridge) ;
          h = P.BASE + H * body * wy;
        } else {
          const lip = P.LIP_H * strength * Math.exp(-((df - P.LIP_D) ** 2) / (2 * P.LIP_W * P.LIP_W));
          const ramp = P.RAMP_H * strength * sm(1 - df / P.RAMP_W);
          h = P.BASE + (lip + ramp) * (0.4 + 0.6 * wy) + P.LOW_H * sm(a / 20) * sm(df / 20) * wy;
        }
        c.hT[j * NX + i] = h;
      }
    }
  }
  // calm (after restarts and fouls) lays the battle relief flat; shot spikes and advances stay (only a goal stop flattens them)
  if (!light) { const k0 = state.flat * (state.calm ?? 1); for (const c of cloths) for (let k = 0; k < c.hT.length; k++) c.hT[k] *= k0; }
  state.activeHills = [];
  // a shot's hill (and its name tag) only stands while the shot spot is still on the shooting side's ground: once the
  // line has gone back past it by more than HILL_OUT m it melts away (HILL_FADE m), so no hill stands in the other's land
  for (const h of hills) { const q = hillParams(h, T); if (!q) continue;
    const out = (h.team === 'home' ? 1 : -1) * (h.X - laneAt(seam, h.Y)); q.near = Math.exp(-Math.max(0, out - P.HILL_OUT) / P.HILL_FADE); q.A *= q.near * state.flat;
    for (const st of stops) if (st.goal.T >= h.T && t >= st.t0 + P.FLOOD_AT) q.A *= Math.exp(-(t - st.t0 - P.FLOOD_AT) / 0.35);
    if (q.A < 0.05) continue; state.activeHills.push({ h, q });
    const R = q.sig * (q.p < 1.5 ? 6 : 4); if (!light) for (const c of cloths) addBumpTo(c, h.X, h.Y, R, r => q.A * Math.exp(-(q.p === 1 ? r / q.sig : Math.pow(r / q.sig, q.p))), true); }
  // calm: the relief is laid flat after every restart and builds back slowly. Goals / kick-offs keep it flat for
  // RESTART_HOLD s then regrow it over RESTART_RAMP s of match time; fouls for FOUL_HOLD then FOUL_FLAT s.
  // The envelope itself moves in video time (CALM_DOWN / CALM_UP), so nothing collapses or pops up at once.
  const lr = lastRestart(T), lf = lastFoul(T);
  const rflat = T >= lr ? sm((T - lr - P.RESTART_HOLD) / P.RESTART_RAMP) : 1;   // (>=: flat right at the kick-off too, clock frozen on it)
  const fflat = lf ? sm((T - lf.T - P.FOUL_HOLD) / P.FOUL_FLAT) : 1;
  const brk = BREAKS.some(b => T >= b.end && T < b.start) ? 0 : 1;   // from the whistle of a period to the next kick-off: flat
  const calmTar = Math.min(rflat, fflat, brk); state.calm = lp(state.calm ?? 1, calmTar, calmTar < (state.calm ?? 1) ? P.CALM_DOWN : P.CALM_UP, state.dt);
  state.foulFlat = fflat;
  if (!light) addAdvanceRelief(t);
  // chances, set pieces and advances pile up when they follow each other at the same spot: their sum is softly capped at
  // RELIEF_CAP m (h -> CAP * (1 - e^(-h/CAP))), so only a goal's spire (added after) ever stands taller
  if (!light) { const C = P.RELIEF_CAP; for (const c of cloths) for (let k = 0; k < c.hT.length; k++) { const h = c.hT[k]; if (h > 0) c.hT[k] = C * (1 - Math.exp(-h / C)); } }
  // shot peak: at the moment of a shot (not a goal) its hill shoots up SHOT_PEAK m higher (added after the cap, so it
  // stands out; still well below a goal's spire), rising in 0.15 s and falling back over SHOT_PEAK_TAU video s
  if (!light) for (const { h, q } of state.activeHills) { if (h.tv === undefined) h.tv = videoTimeAt(h.T); const age = t - h.tv;
    if (age < -0.15 || age > 5 * P.SHOT_PEAK_TAU) continue;
    const A = P.SHOT_PEAK * q.near * state.flat * (age < 0 ? sm((age + 0.15) / 0.15) : Math.exp(-age / P.SHOT_PEAK_TAU)); if (A < 0.05) continue;
    const s = Math.max(3, q.sig * 0.7); for (const c of cloths) addBumpTo(c, h.X, h.Y, s * 4, r => A * Math.exp(-((r / s) ** 2)), true); }
  // breaking waves (added after the cap: the exceptions besides goals): the attacking cloth rises into a wave along the
  // front of its run, CW_W m wide - COUNTER_WAVE m high for a counter-attack (WhoScored FastBreak, or >= 25 m upfield in
  // <= 15 s), SHOT_WAVE m for any other shot that is not a goal (saved, off target, post, blocked)
  // Progression waves: wherever a side is gaining ground, its front rises into the same wave, the higher the more it has
  // gained lately (GAIN_WAVE m at most, half of it after GAIN_REF m x ln 2). Waves of one cloth are pooled by a max
  // per row (a shot wave over a progressing front does not stack).
  if (!light) for (const c of cloths) {
    const amp = new Float64Array(NY), gain = c.side > 0 ? state.gainHome : state.gainAway;
    for (let j = 0; j < NY; j++) { const g = laneAt(gain, j * DX); amp[j] = P.GAIN_WAVE * (1 - Math.exp(-g / P.GAIN_REF)) * state.flat; }
    for (const e of PERCEES) { const H0 = e.counter ? P.COUNTER_WAVE : e.shot ? P.SHOT_WAVE : 0; if (!H0 || !(e.env > 0) || e.side !== c.side) continue;
      const A = H0 * e.env * state.flat; for (let j = 0; j < NY; j++) amp[j] = Math.max(amp[j], A * Math.exp(-(((j * DX - e.Y) / P.CW_W) ** 2) / 2)); }
    for (let j = 0; j < NY; j++) { const A = amp[j]; if (A < 0.05) continue; const Y = j * DX, L = c.L[j], wy = sm(Y / 3) * sm((68 - Y) / 3);
      // crest CW_D m behind the front, 0 at the front edge (it stays down on the other cloth: no gap under the wave)
      for (let i = 0; i < NX; i++) { const df = (1 - i / (NX - 1)) * L; c.hT[j * NX + i] += A * wy * Math.exp(-(((df - P.CW_D) / P.CW_S) ** 2)) * sm(df / P.CW_EDGE); } } }
  if (!light) for (const c of cloths) { const lift = state.topSide === c.side ? P.TOP_LIFT : 0;   // the top cloth never sits exactly on the other one
    for (let k = 0; k < c.hT.length; k++) c.hT[k] += lift; }
  if (!light && state.reveal && state.stop) { // penalty: the scorer's cloth rolls out of the box as a travelling wave
    const [sx, sy, R] = state.reveal; const c = cloths.find(c => c.side === (state.stop.goal.team === 'home' ? 1 : -1)); const amp = P.PEN_WAVE * (1 - sm((R - 70) / 70));
    if (amp > 0.01) for (let j = 0; j < NY; j++) { const Y = j * DX, L = c.L[j]; for (let i = 0; i < NX; i++) { const X = worldX(c, i / (NX - 1), L); const r = Math.hypot(X - sx, Y - sy);
      c.hT[j * NX + i] += amp * Math.exp(-(((r - R + 9) / 8) ** 2)) * sm(X / 4) * sm((105 - X) / 4) * sm(Y / 4) * sm((68 - Y) / 4); } }
  }
  for (const s of stops) {
    const ph = t - s.t0; if (ph < -0.5) continue;
    let env = state.goalEnv.get(s) || 0; const target = (ph >= s.sched.spire && ph < s.sched.spireDecay) ? 1 : 0;
    env = lp(env, target, target > env ? 0.1 : 0.7, state.dt); state.goalEnv.set(s, env);
    if (!light && env > 0.003) for (const c of cloths.filter(c => c.side === (s.goal.team === 'home' ? 1 : -1))) addBumpTo(c, s.goal.X, s.goal.Y, P.GOAL_R, r => { const q = r / P.GOAL_R; return P.GOAL_H * env * Math.exp(-((q / 0.36) ** 2)) * sm(1 - q) / 1.0; }, false);
  }
  // missed / saved penalty: the same black-out with the spotlight on the box, without the reveal
  const pm = currentPenMiss(t), pmPh = pm ? t - pm.t0 : -1; state.penMiss = pm; state.penMissPhase = pmPh;
  if (pm) { const home = pm.shot.team === 'home'; for (const c of cloths) c.uniforms.uBox.value.set(home ? 88.5 : 0, 13.84, home ? 105 : 16.5, 54.16); }
  const boTar = ((stop && stop.pen && phase >= stop.sched.boOn && phase < stop.sched.blackout) || (pm && pmPh >= pm.sched.boOn && pmPh < pm.sched.blackout)) ? 1 : 0; state.bo = lp(state.bo, boTar, boTar ? 0.3 : 0.15, state.dt);
  state.reveal = null;
  if (stop && stop.pen) { const g = stop.goal; const home = g.team === 'home'; const sx = home ? 94 : 11;
    for (const c of cloths) { c.uniforms.uBox.value.set(home ? 88.5 : 0, 13.84, home ? 105 : 16.5, 54.16); }
    if (phase >= stop.sched.reveal0) { const rp = phase - stop.sched.reveal0; state.reveal = [sx, 34, 90 * (1 - Math.exp(-rp / 0.9)) + 60 * sm((rp - 1.05) / 1.0)]; } }
  const ftTar = t >= T_FULLTIME ? 1 : 0; state.ft = lp(state.ft, ftTar, 0.6, state.dt);
}

export { territory, worldX, heightAtCloth, heightAt, hills, computeTargets };

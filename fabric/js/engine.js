// Territory engine: the front line (CSV keyframes, front clock), restarts and resets, percées, goal build-up floor, one-way movement.
import { M, P, lp, clamp, sm, NL } from './config.js';
import { END, BREAKS, chartMinute, goals, stops, SLOW, slowExtra, buildKnots, currentStop, videoTimeAt, kickPauses } from './timeline.js';

const seam = new Float32Array(NL).fill(52.5), seamTar = new Float32Array(NL).fill(52.5), seamVel = new Float32Array(NL);
// ------------------------------------------------------------------ fields
function laneAt(arr, Y) { const f = clamp(Y / 2, 0, NL - 1.001); const i = Math.floor(f), a = f - i; return arr[i] * (1 - a) + arr[i + 1] * a; }
// restarts from the centre spot: kick-off, second half, and every goal
const RESTARTS = [0, ...BREAKS.map(b => b.start), ...goals.map(g => g.T)].sort((a, b) => a - b);
function lastRestart(T) { let r = 0; for (const x of RESTARTS) if (x <= T) r = x; return r; }   // (<=: the kick-off itself counts, clock frozen on it)
// fouls: play restarts flat from the line of the foul
const FOULS = (M.fouls || []).filter(f => !goals.some(g => Math.abs(g.T - f.T) < 30)).sort((a, b) => a.T - b.T);
// travel-paced clock: where the CSV moves the front a lot in little match time, the clock slows so the front can follow
// at about FRONT_V m per video second (at most FRONT_SLOW_MAX s added per stretch); the timeline is then rebuilt
{ const F0 = buildFront(); const k = F0.keys;
  for (let i = 1; i < k.length; i++) { const a = k[i - 1], b = k[i]; if (b.T <= a.T) continue;
    let d = 0; for (let l = 0; l < NL; l++) d = Math.max(d, Math.abs(b.F[l] - a.F[l]));
    const extra = Math.min(P.FRONT_SLOW_MAX, d / P.FRONT_V - (b.T - a.T) / 60 * P.BASE_DWELL - slowExtra(a.T, b.T));
    if (extra > 0.02) SLOW.push({ T0: a.T, T1: b.T, extra }); }
  buildKnots(); }
// resets seen on screen: the front glides calmly, from wherever it is drawn, to a flat straight line, in HALF_RESET /
// FOUL_RESET video seconds, or longer when it has far to go (RESET_V m per second on average), and stays there holdV s:
//  - end of every period (half-time, end of normal time, extra-time break): back to the centre line in exactly
//    HALF_RESET s, held there through the turn (the map turns only once the line is flat, HALF_FLAT s after the
//    whistle) and the next kick-off;
//  - every foul: once its percée has shown the foul point (PERC_HOLD_FOUL s after it), to a straight line through the
//    foul, from which play restarts flat.
const RESETS = [...BREAKS.map(b => ({ T: b.end, tStart: videoTimeAt(b.end), anchor: 52.5, dur: P.HALF_RESET, fixed: true, holdV: Math.max(0, videoTimeAt(b.start) - videoTimeAt(b.end) - P.HALF_RESET), Tafter: b.start })),
  ...FOULS.map(f => ({ T: f.T, tStart: videoTimeAt(f.T) + P.PERC_HOLD_FOUL, anchor: clamp(f.X, 4, 101), dur: P.FOUL_RESET, holdV: P.FOUL_LINE_HOLD, Tafter: f.T + P.FOUL_SNAP }))
    // the half-time reset wins: no foul restart begins between the first-half whistle and the second-half kick-off
    .filter(r => !BREAKS.some(b => r.tStart >= videoTimeAt(b.end) && r.T < b.start + 1))];
function lastFoul(T) { let r = null; for (const f of FOULS) if (f.T < T) r = f; return r; }
// ---- territory engine: every minute has ONE winner (the side the momentum line favours, or the side that got
// furthest when momentum is level). Only that side gains, so nobody gains and loses at the same time.
// The gain is built step by step from the winner's own actions in that minute, in order: each completed pass moves
// the front a little toward where the team-mate received it (endX/endY), each carry toward where it ended (the pass
// origin). Every step is a fraction of the remaining distance (STEP_FRAC, at most STEP_MAX m), the minute at most G_MAX m.
// Restarts: kick-off, second half and goals reset the front to the centre line and hold it there (GOAL_HOLD);
// fouls to a straight line through the foul (FOUL_HOLD_FRONT).
const reachOf = (e) => e.side > 0 ? e.X : 105 - e.X;
let FRONT = null, FRONT_SIG = '';
function buildFront() {
  const byMin = new Map();
  for (const [T, side, X, Y] of (M.prog || [])) { const k = Math.floor(T / 60); if (!byMin.has(k)) byMin.set(k, []); byMin.get(k).push({ T, side, X, Y }); }
  // ease = match seconds to reach the anchor line, hold = how long it stays there. Kick-offs (second half, goals) are on
  // the centre line already when the clock restarts (ease < 0: reached before; for goals that happens during the stop)
  // (the match kick-off is held on the centre line like every other kick-off)
  const restarts = [{ T: 0, anchor: 52.5, ease: -0.5, hold: 20 }, ...BREAKS.map(b => ({ T: b.start, anchor: 52.5, ease: -0.5, hold: 20 })), ...goals.map(g => ({ T: g.T - (g.penalty ? 1 : 0), anchor: 52.5, ease: -0.5, hold: P.GOAL_HOLD })),
    ...FOULS.map(f => ({ T: f.T, anchor: clamp(f.X, 4, 101), ease: P.FOUL_SNAP, hold: P.FOUL_HOLD_FRONT }))   // play restarts flat from the foul line
  ].sort((a, b) => a.T - b.T);
  const keys = [{ T: 0, F: new Float64Array(NL).fill(52.5) }]; let F = keys[0].F.slice(); const wins = []; let diffT = 0;
  const push = (T, F) => { const last = keys[keys.length - 1]; if (T <= last.T + 0.01) { last.F = F.slice(); return; } keys.push({ T, F: F.slice() }); };
  const lastT = Math.ceil(END / 60);
  for (let k = 0; k <= lastT; k++) {
    const t0 = k * 60, t1 = t0 + 60; let lastR = -1;
    for (const r of restarts) if (r.T >= t0 && r.T < t1) { const a0 = Math.min(r.T - 0.1, r.T + r.ease), a1 = Math.max(r.T, r.T + r.ease);
      push(a0, F); F = new Float64Array(NL).fill(r.anchor); push(a1, F); push(a1 + r.hold, F); lastR = a1 + r.hold; }
    // every on-ball action of the CSV, in match order: its side's line must reach just past where it happened
    // (B_MARGIN m); if it is not there yet, that part of the line is pushed out to it (bulge of B_SIG m). Ground is
    // kept until the other side's actions take it back.
    const s2 = 2 * P.B_SIG * P.B_SIG;
    for (const e of (byMin.get(k) || []).filter(e => e.T > lastR)) {
      // between actions the line relaxes sideways (one diffusion pass per B_DIFF_DT match s): isolated spikes left by
      // a single action melt into the line instead of staying as a thin tongue in the other side's ground
      const nd = Math.min(30, Math.floor((e.T - diffT) / P.B_DIFF_DT));
      if (nd > 0) { for (let it = 0; it < nd; it++) { const G = F.slice(); for (let l = 0; l < NL; l++) { const a = G[Math.max(0, l - 1)], b = G[Math.min(NL - 1, l + 1)]; F[l] = G[l] + P.B_DIFF * (a + b - 2 * G[l]); } }
        diffT += nd * P.B_DIFF_DT; push(Math.max(e.T - 0.05, keys[keys.length - 1].T + 0.05), F); }
      const need = e.side * (e.X - laneAt(F, e.Y)) + P.B_MARGIN; if (need <= P.B_MIN) continue;
      const nF = F.slice();
      for (let l = 0; l < NL; l++) { const dy = l * 2 - e.Y; nF[l] = clamp(F[l] + e.side * need * (P.G_BASE + (1 - P.G_BASE) * Math.exp(-dy * dy / s2)), 3, 102); }
      F = nF; push(Math.max(e.T, keys[keys.length - 1].T + 0.05), F); wins.push({ k, side: e.side, T: e.T, X: e.X, Y: e.Y, G: need });
    }
  }
  // monotone cubic (Fritsch-Carlson) tangents per lane: smooth, never overshoots, monotone between keyframes
  const n = keys.length; const m = keys.map(() => new Float64Array(NL));
  for (let l = 0; l < NL; l++) {
    const d = []; for (let i = 0; i < n - 1; i++) d.push((keys[i + 1].F[l] - keys[i].F[l]) / (keys[i + 1].T - keys[i].T));
    for (let i = 0; i < n; i++) { if (i === 0) m[i][l] = 0; else if (i === n - 1) m[i][l] = 0; else m[i][l] = (d[i - 1] * d[i] <= 0) ? 0 : (d[i - 1] + d[i]) / 2; }
    for (let i = 0; i < n - 1; i++) { if (d[i] === 0) { m[i][l] = 0; m[i + 1][l] = 0; continue; } const a = m[i][l] / d[i], b = m[i + 1][l] / d[i], h = a * a + b * b; if (h > 9) { const tt = 3 / Math.sqrt(h); m[i][l] = tt * a * d[i]; m[i + 1][l] = tt * b * d[i]; } }
  }
  return { keys, m };
}
function computeFront(T, out) {
  const sig = [P.G_BASE, P.FOUL_SNAP, P.GOAL_HOLD, P.FOUL_HOLD_FRONT, P.B_MARGIN, P.B_SIG, P.B_MIN, P.B_DIFF, P.B_DIFF_DT].join();
  if (!FRONT || sig !== FRONT_SIG) { FRONT = buildFront(); FRONT_SIG = sig; }
  const { keys, m } = FRONT; let lo = 0, hi = keys.length - 1;
  if (T <= keys[0].T) { out.set(keys[0].F); return; } if (T >= keys[hi].T) { out.set(keys[hi].F); return; }
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (keys[mid].T <= T) lo = mid; else hi = mid; }
  const a = keys[lo], b = keys[hi], h = b.T - a.T, u = (T - a.T) / h, u2 = u * u, u3 = u2 * u;
  const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
  for (let l = 0; l < NL; l++) out[l] = h00 * a.F[l] + h10 * h * m[lo][l] + h01 * b.F[l] + h11 * h * m[hi][l];
}
const state = { t: 0, T: 0, flat: 1, bo: 0, dim: 0, ft: 0, lean: 0, topSide: 1, goalEnv: new Map(), score: [0, 0], shown: new Set(), sky: null, stopPhase: 0, seamMode: 'normal', calm: 0,   // the match starts with the relief laid flat
 
  gainHome: new Float64Array(NL), gainAway: new Float64Array(NL) };   // metres each lane gained lately (progression waves)
// front clock: the front replays the keyframed curve at its own pace. It follows match time but never moves any lane
// faster than V_MAX metres per video second (a little more when it lags), so every gain is seen happening. All lanes read the same curve at the
// same instant, so they always move together. While a goal floods the pitch the clock jumps to match time (hidden).
const frontA = new Float64Array(NL), frontB = new Float64Array(NL);
function advanceFrontClock(T, dt, jump) {
  if (state.Tf === undefined || jump || T < state.Tf) { state.Tf = T; return; }
  computeFront(state.Tf, frontA); let dT = T - state.Tf;
  const vmax = P.V_MAX * Math.min(2, 1 + dT / P.LAG_REF);   // a front that falls far behind speeds up gently, so it never drifts away
  for (let it = 0; it < 12 && dT > 1e-6; it++) {
    computeFront(state.Tf + dT, frontB); let mx = 0; for (let l = 0; l < NL; l++) mx = Math.max(mx, Math.abs(frontB[l] - frontA[l]));
    const lim = vmax * dt; if (mx <= lim) break; dT *= 0.9 * lim / mx;
  }
  state.Tf += dT;
}
// ---- percées: a shot, a goal or a foul can only happen where the attacking side's line has got to (for a foul: the
// side that had the ball, i.e. the committer when WhoScored marks the foul 'Offensive', else the fouled side). Around the action's
// Y, part of the front (not the whole line) runs out to the action point and PERC_MARGIN m beyond it, then falls back.
// Counter-attacks (WhoScored FastBreak shots; fouls after >= 25 m gained in <= 15 s) make a narrow tongue (PERC_SIG_C),
// other actions a broader bulge (PERC_SIG). Timed in video seconds so they are always seen: the run starts with the
// attacking chain (chainT) and lasts PERC_RISE_MIN..PERC_RISE_MAX s (longer trips take longer, ~PERC_V m/s), holds,
// then decays over PERC_DECAY s. A goal stop or the half-time reset wipes the percées that came before it.
const PERCEES = [
  ...M.shots.map(s => ({ T: s.goal && s.penalty ? s.T - 1 : s.T, side: s.team === 'home' ? 1 : -1, X: s.X, Y: s.Y, xg: s.xg, chainT: s.chainT ?? s.T, counter: !!s.counter, shot: !s.goal, hold: P.PERC_HOLD })),
  ...(M.setpieces || []).filter(c => c.kind === 'corner').map(c => ({ T: c.T, side: c.team === 'home' ? 1 : -1, X: c.X2, Y: c.Y2, chainT: c.T, counter: false, hold: P.PERC_HOLD })),
  ...FOULS.map(f => ({ T: f.T, foulT: f.T, side: (f.attack || f.fouled) === 'home' ? 1 : -1, X: f.X, Y: f.Y, chainT: f.chainT ?? f.T, counter: !!f.counter, hold: P.PERC_HOLD_FOUL }))
].map(e => ({ ...e, tv: videoTimeAt(e.T), tc: videoTimeAt(e.chainT), sig: e.counter ? P.PERC_SIG_C : P.PERC_SIG }));
const wipes = [...stops.map(s => s.t0 + (s.pen ? s.sched.flood : P.FLOOD_AT)), ...BREAKS.flatMap(b => [videoTimeAt(b.end), videoTimeAt(b.start)])];
// a run may not start before the end of a goal stop or of the half-time reset that precedes it (the pitch stays flat)
// (and none during a kick-off pause: start of the match and of every period)
const calmEnds = [...stops.map(s => s.t0 + s.dur + P.GOAL_CALM), ...kickPauses.flatMap(k => [k.t0 + k.dur, k.t0 + k.dur + P.GOAL_CALM])];
PERCEES.sort((a, b) => a.tv - b.tv);
PERCEES.forEach((e, i) => {
  e.minStart = Math.max(-1, ...calmEnds.filter(c => c <= e.tv));
  for (let j = i - 1; j >= 0; j--) if (PERCEES[j].side !== e.side) { e.minStart = Math.max(e.minStart, PERCEES[j].tv); break; }
  // the next action that takes the line over: the other side's next action, or any foul (its run sets the line at the spot)
  for (let j = i + 1; j < PERCEES.length; j++) if (PERCEES[j].side !== e.side || PERCEES[j].foulT !== undefined) { e.nextOpp = PERCEES[j]; break; }
});
const percBase = new Float64Array(NL), percUp = new Float64Array(NL), percDn = new Float64Array(NL), percMask = new Float64Array(NL), foulDir = new Int8Array(NL), runDir = new Int8Array(NL);   // foulDir: way a foul run pulls each lane   // percMask: lanes a run is moving now
// Runs of the same side are pooled with a max (no double counting), the two sides add up. When the other side's next
// action comes, an older run fades out over the last FADE s before that action (its own run starts no earlier than
// the older action), so at the moment of every action its own run sets the line there. All envelopes are smooth.
function applyPercees(t, out) {
  percBase.set(out); percUp.fill(0); percDn.fill(0); foulDir.fill(0); runDir.fill(0); for (const e of PERCEES) e.env = 0;
  for (const e of PERCEES) {
    if (t < e.tv - P.PERC_RISE_MAX || t > e.tv + e.hold + P.PERC_DECAY) continue;
    if (wipes.some(w => w >= e.tv - 0.01 && t >= w)) continue;
    if (e.foulT !== undefined && t >= e.tv + e.hold) continue;   // a foul's run ends where its flat restart line takes over
    // shots: the attacking line must have got past the point. Fouls are duels: the line comes to the foul point from
    // whichever side it is (if the attacking side already holds far beyond it, the other side pushes back to it)
    let need = e.side * (e.X - laneAt(percBase, e.Y)) + (e.foulT !== undefined ? P.FOUL_MARGIN : P.PERC_MARGIN);   // fouls: right at the spot
    if (need <= 0 && (e.foulT === undefined || need > -0.5)) continue;   // shot: already beyond the action point
    const r0 = Math.max(e.tv - clamp(Math.max(e.tv - e.tc, need / P.PERC_V), P.PERC_RISE_MIN, P.PERC_RISE_MAX), e.minStart);
    const tvL = e.tv - P.PERC_LEAD;   // fully out a little before the action, so speed limits never make it late
    const rise = Math.max(P.PERC_MIN_MOVE, tvL - r0);   // starts at r0 (never before the other side's previous action), never faster than PERC_MIN_MOVE s
    const up0 = Math.max(tvL - rise, e.minStart), up1 = up0 + rise;   // never starts before minStart (kick-off pause / calm), even if then a little late
    let env = t < up1 ? sm((t - up0) / rise) : t < Math.max(e.tv, up1) + e.hold ? 1 : 1 - sm((t - Math.max(e.tv, up1) - e.hold) / P.PERC_DECAY);
    // the fade toward the other side's next action never starts before this run's own action (packed actions: shorter fade)
    const o = e.nextOpp; if (o) { const F = clamp(o.tv - e.tv, P.PERC_MIN_MOVE, P.PERC_RISE_MIN), f0 = Math.max(e.tv, o.tv - F); env *= 1 - sm((t - f0) / Math.max(0.05, o.tv - f0)); }
    if (env <= 0) continue; e.env = env;
    const dirSide = need > 0 ? e.side : -e.side; need = Math.abs(need);
    const A = need * env, s2 = 2 * e.sig * e.sig, acc = dirSide > 0 ? percUp : percDn;
    for (let l = 0; l < NL; l++) { const dy = l * 2 - e.Y, a = A * Math.exp(-dy * dy / s2); acc[l] = Math.max(acc[l], a); if (e.foulT !== undefined && a > 0.5) foulDir[l] = dirSide; if (a > 0.5 && env > 0.9) runDir[l] = dirSide; }
  }
  for (let l = 0; l < NL; l++) { out[l] = clamp(percBase[l] + percUp[l] - percDn[l], 1, 104); percMask[l] = Math.min(1, (percUp[l] + percDn[l]) / 3); }
}
function buildStart(st) {
  // from the start of the scorer's possession (CSV: after the opponent's last on-ball action), at least GOAL_BUILD s
  if (st.buildStart === undefined) { const side = st.goal.team === 'home' ? 1 : -1;
    let b = Math.min(st.t0 - P.GOAL_BUILD, st.goal.poss !== undefined ? videoTimeAt(st.goal.poss) : Infinity);
    // (after the other side's last action, and after any foul: a foul restarts play from its own line)
    for (const e of PERCEES) if ((e.side !== side || e.foulT !== undefined) && e.tv < st.t0) b = Math.max(b, Math.min(st.t0 - 0.3, e.tv + e.hold));
    for (const o of stops) if (o !== st && o.t0 < st.t0) b = Math.max(b, o.t0 + o.dur + 0.1);   // not before the previous kick-off
    st.buildStart = b; }
  return st.buildStart;
}
function seamTargets(T, t) {
  const stop = currentStop(t); const phase = stop ? t - stop.t0 : -1;
  const fA0 = stop && (stop.pen ? stop.sched.flood : P.FLOOD_AT);
  advanceFrontClock(T, state.dt, !!stop && phase >= fA0 && phase < stop.dur); computeFront(state.Tf, seamTar); applyPercees(t, seamTar);
  state.seamMode = 'normal';
  const fA = stop && !stop.pen ? P.FLOOD_AT : stop && stop.sched.flood, uA = stop && !stop.pen ? P.UNFLOOD_AT : stop && stop.sched.unflood;
  if (stop && phase >= fA && phase < uA) { state.seamMode = 'flood'; const v = stop.goal.team === 'home' ? 112 : -7; for (let l = 0; l < NL; l++) seamTar[l] = v; }
  else if (stop && phase >= uA && phase < stop.dur) { state.seamMode = 'center'; for (let l = 0; l < NL; l++) seamTar[l] = 52.5; }
  // goal build-up: while the scorer's team has the ball before a goal (and at least the last GOAL_BUILD video s), the
  //   scorer's whole line never steps back - the move that ends in the goal goes forward in one go
  //   (it starts after the other side's last shot / foul / corner before the goal, which must still be shown) and the
  //   floor holds until the flood starts: between the goal instant and the flood the line must not drift back either
  { const st = stops.find(s => t >= buildStart(s) && t < s.t0 + (s.pen ? s.sched.flood : P.FLOOD_AT));
    state.floorSide = st ? (st.goal.team === 'home' ? 1 : -1) : 0;   // also stops any on-screen step back (integrateSeam)
    if (st && state.seamMode === 'normal') { const g = st.goal, side = g.team === 'home' ? 1 : -1;
      // (re)start the floor from the line on screen: at the start of the possession and after a foul restart glide
      if (!state.goalFloor || state.goalFloor.st !== st || state.prevMode !== 'normal') state.goalFloor = { st, F: Float64Array.from(seam) };
      const F = state.goalFloor.F;
      for (let l = 0; l < NL; l++) { const w = 1;   // the whole line: no lane of the scorer steps back before the goal
        const floor = F[l] * w + seamTar[l] * (1 - w); seamTar[l] = side > 0 ? Math.max(seamTar[l], floor) : Math.min(seamTar[l], floor); F[l] = side > 0 ? Math.max(F[l], seamTar[l]) : Math.min(F[l], seamTar[l]); } }
    else state.goalFloor = null; }
  if (state.prevT !== undefined) for (const r of RESETS) if (r.tStart !== undefined ? (r.tStart > state.prevt && r.tStart <= t) : (r.T > state.prevT && r.T <= T)) { // longer glides for longer trips (RESET_V m/s on average)
    let d = 0; for (let l = 0; l < NL; l++) d = Math.max(d, Math.abs(seam[l] - r.anchor));
    const d0 = new Float64Array(NL).fill(r.anchor); applyPercees(t, d0); for (let l = 0; l < NL; l++) d0[l] -= r.anchor;   // runs already on screen
    // two phases so the line never moves both ways at once: first the lanes going the dominant way, then the others
    const from = Float64Array.from(seam), dir = new Int8Array(NL); let sp = 0, sn = 0, dp = 0, dn = 0;
    for (let l = 0; l < NL; l++) { const g = r.anchor - (from[l] - d0[l]); dir[l] = g >= 0 ? 1 : -1; if (g >= 0) { sp += g; dp = Math.max(dp, g); } else { sn -= g; dn = Math.max(dn, -g); } }
    const first = sp >= sn ? 1 : -1, d1 = first > 0 ? dp : dn, d2 = first > 0 ? dn : dp;
    const dur1 = r.fixed ? (d2 > 0.3 ? r.dur * 0.5 : r.dur) : Math.max(r.dur * 0.5, d1 / P.RESET_V), dur2 = d2 > 0.3 ? (r.fixed ? r.dur * 0.5 : Math.max(r.dur * 0.5, d2 / P.RESET_V)) : 0;
    state.reset = { r, t0: t, from, d0, dir, first, dur1, dur2, dur: dur1 + dur2 }; }
  state.prevT = T; state.prevt = t;
  if (state.reset) {
    const r = state.reset.r;
    // no hold at the restart point while the scorer keeps the ball before a goal
    if (t - state.reset.t0 >= state.reset.dur + (state.floorSide ? 0 : r.holdV)) { state.Tf = Math.max(state.Tf, r.Tafter); state.reset = null; computeFront(state.Tf, seamTar); applyPercees(t, seamTar); }
    else { // the line glides (runs present at the start are taken out of it); other actions' runs ride on top of it
      state.seamMode = 'reset'; const R = state.reset;
      const u1 = sm((t - R.t0) / R.dur1), u2 = R.dur2 > 0 ? sm((t - R.t0 - R.dur1) / R.dur2) : 1;
      for (let l = 0; l < NL; l++) { const u = R.dir[l] === R.first ? u1 : u2; seamTar[l] = (R.from[l] - R.d0[l]) * (1 - u) + r.anchor * u; }
      applyPercees(t, seamTar); }
  }
  // which cloth is on top: the pushing force (momentum sign, with hysteresis; a flood puts the scorer on top)
  state.lean = lp(state.lean, momentumAt(chartMinute(T)) / 100, 1.0, state.dt);
  let share = 0; for (let l = 0; l < NL; l++) share += clamp(seam[l], 0, 105) / 105; share /= NL;
  const ramp = 1 - Math.exp(-(T - lastRestart(T)) / P.RESTART_TAU);
  // dominance = territory held, blended with the momentum line
  state.dom = lp(state.dom || 0, (1 - P.MOM_DOM) * (share - 0.5) + P.MOM_DOM * 0.5 * state.lean * ramp, P.DOM_TAU, state.dt);
  if (stop && phase >= fA && phase < uA) state.topSide = stop.goal.team === 'home' ? 1 : -1;
  else if (Math.abs(state.dom) > P.DOM_HYST) state.topSide = state.dom > 0 ? 1 : -1;
}
const dirD = new Float64Array(NL);
// one direction at a time: in each frame only the lanes moving the dominant way move (at most V_LANE m/s); lanes that
// would move the other way wait and catch up when their direction dominates, so the line never gains and loses at once.
// The chosen direction is held DIR_HOLD s before it may switch (no flicker between two frames).
function moveOneWay(dt) {
  // lanes carried by a run toward a foul / shot / corner weigh 6x, so the line goes to the action first
  let sp = 0, sn = 0; for (let l = 0; l < NL; l++) { const d = dirD[l] * (1 + 5 * percMask[l]); if (d > 0) sp += d; else sn -= d; }
  let keep = state.dir || (sp >= sn ? 1 : -1); const cur = keep > 0 ? sp : sn, other = keep > 0 ? sn : sp;
  // lanes kept waiting get their turn after DIR_MAX_WAIT s, so no pocket of the other colour is left behind
  if (other > 0.5) { if (state.waitT === undefined) state.waitT = state.t; } else state.waitT = undefined;
  const starved = state.waitT !== undefined && state.t - state.waitT >= P.DIR_MAX_WAIT;
  // a foul run pulling the other way switches at once (the line must reach the foul point in time)
  let foulOther = 0; for (let l = 0; l < NL; l++) if (foulDir[l] === -keep && Math.sign(dirD[l]) === -keep) foulOther += Math.abs(dirD[l]);
  // likewise a run that is fully out (shot, corner, foul) and whose lanes still lag the other way takes the line at once
  // (at most one such switch every 0.2 s, so two runs never make it flicker)
  let runOther = 0; for (let l = 0; l < NL; l++) if (runDir[l] === -keep && Math.sign(dirD[l]) === -keep) runOther += Math.abs(dirD[l]);
  const runTurn = runOther > 0.5 && state.t - (state.dirT || 0) >= 0.2;
  if ((cur < 1e-6 && other > 1e-6) || (foulOther > 0.5 && foulOther * 6 > cur) || runTurn || ((other > cur || starved) && state.t - (state.dirT || 0) >= P.DIR_HOLD)) { keep = -keep; state.dirT = state.t; state.waitT = undefined; }
  state.dir = keep; const cap = P.V_LANE * dt;
  for (let l = 0; l < NL; l++) { let d = dirD[l]; if (Math.sign(d) !== keep) d = 0; d = clamp(d, -cap, cap); seamVel[l] = d / dt; seam[l] += d; }
}
function integrateSeam(dt) {
  if (state.seamMode === 'normal') { // follow the keyframed front + percées, one way at a time
    // follow the keyframed (C1, monotone) curve exactly; a residual offset left by a stop fades out uniformly
    if (state.prevMode !== 'normal') { state.catchOff = Float64Array.from(seam, (v, l) => v - seamTar[l]); }
    state.prevMode = 'normal'; const f = Math.exp(-dt / P.FOLLOW_TAU); const off = state.catchOff;
    for (let l = 0; l < NL; l++) { if (off) off[l] *= f; dirD[l] = seamTar[l] + (off ? off[l] : 0) - seam[l]; }
    if (state.floorSide) for (let l = 0; l < NL; l++) dirD[l] = state.floorSide > 0 ? Math.max(0, dirD[l]) : Math.min(0, dirD[l]);   // scorer in possession: forward only
    moveOneWay(dt); return; }
  if (state.seamMode === 'reset') { // calm glide to the restart line (computed in seamTargets), one way at a time
    state.prevMode = 'reset'; for (let l = 0; l < NL; l++) dirD[l] = seamTar[l] - seam[l]; moveOneWay(dt); return; }
  if (state.seamMode === 'center') { // glide from wherever the unflood left it to the exact centre line, eased, done 0.3 s before play
    if (state.prevMode !== 'center') { state.centerFrom = Float64Array.from(seam); state.centerT0 = state.stopPhase; }
    state.prevMode = 'center'; const st = state.stop; const uA = st.pen ? st.sched.unflood : P.UNFLOOD_AT;
    const u = sm((state.stopPhase - state.centerT0) / Math.max(0.2, st.dur - 0.3 - Math.max(uA, state.centerT0)));
    for (let l = 0; l < NL; l++) { const v = state.centerFrom[l] + (52.5 - state.centerFrom[l]) * u; seamVel[l] = (v - seam[l]) / dt; seam[l] = v; } return; }
  state.prevMode = state.seamMode;
  const K = state.seamMode === 'flood' ? P.FLOOD_K : state.seamMode === 'center' ? P.CENTER_K : P.SEAM_K; const D = 2 * Math.sqrt(K) * P.SEAM_DAMP;
  for (let l = 0; l < NL; l++) { const a = K * (seamTar[l] - seam[l]) - D * seamVel[l]; seamVel[l] += a * dt; seam[l] += seamVel[l] * dt; }
}
const momSeries = M.momentum.csv || M.momentum.fotmob;   // CSV xT momentum (recomputed by the export script), else FotMob
function momentumAt(cm) { const s = momSeries; if (cm <= s[0][0]) return s[0][1];
  for (let i = 1; i < s.length; i++) if (s[i][0] >= cm) { const [m0, v0] = s[i - 1], [m1, v1] = s[i]; return m1 > m0 ? v0 + (v1 - v0) * (cm - m0) / (m1 - m0) : v1; } return s[s.length - 1][1]; }

export { seam, seamVel, laneAt, lastRestart, FOULS, lastFoul, state, PERCEES, wipes, buildStart, seamTargets, integrateSeam, momSeries, momentumAt };

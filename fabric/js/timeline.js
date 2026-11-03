// Periods and match clock, goal stops, cards, slow windows and the dramatic timeline (match time <-> video time).
import { M, P, clamp } from './config.js';

// ------------------------------------------------------------------ clock helpers
const SH = M.periods.secondHalfStart, FH_END = M.periods.firstHalfEnd, END = M.periods.matchEnd;
// periods drawn (two halves, plus the two periods of extra time when played; no penalty shoot-out), from build_data.py:
// start / end in match time, nom0 / nom1 the nominal minutes (0-45, 45-90, 90-105, 105-120). BREAKS: the pauses
// between them (each one: line back flat on the centre line, then the map turns 180 degrees, then kick-off).
const PERIODS = M.periods.list || [{ start: 0, end: FH_END, nom0: 0, nom1: 45 }, { start: SH, end: END, nom0: 45, nom1: 90 }];
const BREAKS = PERIODS.slice(1).map((p, i) => ({ end: PERIODS[i].end, start: p.start, nom: p.nom0 }));
const MAX_MIN = PERIODS[PERIODS.length - 1].nom1;   // 90, or 120 with extra time
const EN = new URLSearchParams(location.search).get('lang') === 'en';  // ?lang=en : the English pages of data-workers.com/en/
const PERIOD_LABELS = EN ? ['1ST HALF', '2ND HALF', 'EXTRA TIME 1', 'EXTRA TIME 2'] : ['1RE MI-TEMPS', '2E MI-TEMPS', 'PROLONGATION 1', 'PROLONGATION 2'];
function periodIndex(T) { let k = 0; PERIODS.forEach((p, i) => { if (T >= p.start) k = i; }); return k; }
// displayed minute: each period restarts at its nominal minute at its own kick-off (1.., 46.., 91.., 106..; cap+n in stoppage time)
function dispMinute(T) { const p = PERIODS[periodIndex(T)]; return [p.nom0 + 1 + Math.floor((T - p.start) / 60), p.nom1]; }
// the clock shows the time played: 0' at the kick-off, 45' at the second-half kick-off, ... (cap during stoppage time);
// event labels keep the football minute (a goal at 19:45 is 20')
function clockText(T) { const p = PERIODS[periodIndex(T)]; return String(Math.min(p.nom0 + Math.floor(Math.max(0, T - p.start) / 60), p.nom1)); }
function chartMinute(T) { const p = PERIODS[periodIndex(T)]; return Math.min(p.nom0 + Math.max(0, T - p.start) / 60, p.nom1); }

// ------------------------------------------------------------------ dramatic timeline
const goals = M.shots.filter(s => s.goal).sort((a, b) => a.T - b.T);
const stops = goals.map(g => ({ T: g.T - (g.penalty ? 1 : 0), dur: g.penalty ? P.PEN_PAUSE : P.GOAL_PAUSE, goal: g, pen: !!g.penalty }));
stops.forEach(s => { // phase schedule (seconds since the clock froze)
  s.sched = s.pen ? { boOn: 0.75, blackout: 4.0, reveal0: 1.95, reveal1: 4.0, flatUntil: 4.8, spire: 99, flood: 1.8, score: 3.0, cardIn: 2.0, spireDecay: 99, unflood: 5.7, cardOut: 3.6 }
                  : { blackout: 0, spire: 1.1, flood: 1.0, score: 1.2, cardIn: 1.2, spireDecay: 2.0, unflood: 2.4, cardOut: 3.0 };
});
// cards: from the CSV (WhoScored 'Card' events). ?demoCards=1 adds two made-up cards (labelled DÉMO) to preview the effects
const CARDS = [...(M.cards || []), ...(/demoCards=1/.test(location.search) ? [
  { T: 25 * 60 + 10, team: 'away', kind: 'yellow', player: { short: 'DÉMO' }, label: "26'", demo: true },
  { T: 3000 + 22 * 60, team: 'home', kind: 'red', player: { short: 'DÉMO' }, label: "68'", demo: true }] : [])].sort((a, b) => a.T - b.T);
// slow windows: right after every kick-off (match start, each period, each goal) and after every foul the match clock runs slower,
// so the flat restart from the centre line, or the calm return to the foul line, can be seen. `extra` = video seconds added.
const SLOW = [...CARDS.map(c => ({ T0: c.T, T1: c.T + 20, extra: P.CARD_SLOW })), { T0: 0, T1: P.GOAL_HOLD, extra: P.GOAL_SLOW }, ...BREAKS.flatMap(b => [{ T0: b.end, T1: b.start, extra: P.HALF_SLOW }, { T0: b.start, T1: b.start + P.GOAL_HOLD, extra: P.GOAL_SLOW }]), ...goals.map(g => ({ T0: g.T, T1: g.T + 0.5 + P.GOAL_HOLD, extra: P.GOAL_SLOW })),
  ...(M.fouls || []).filter(f => !goals.some(g => Math.abs(g.T - f.T) < 30)).map(f => ({ T0: f.T, T1: f.T + P.FOUL_SNAP + P.FOUL_HOLD_FRONT, extra: P.FOUL_SLOW })),
  // every shot that is not a goal: a short slow-down (SHOT_SLOW video s over SHOT_SLOW_T match s) to see its wave and hill
  ...M.shots.filter(s => !s.goal).map(s => ({ T0: s.T, T1: s.T + P.SHOT_SLOW_T, extra: P.SHOT_SLOW }))];
// swings: when one side's shot / foul follows the other side's far away, the line must cross the pitch between them;
// the clock slows so that crossing runs at about SWING_V m per video second (at most SWING_MAX s added per swing)
{ const gT = goals.map(g => g.T);
  const acts = [...M.shots.map(s => ({ T: s.T, side: s.team === 'home' ? 1 : -1, X: s.X })),
    ...(M.fouls || []).filter(f => !gT.some(g => Math.abs(g - f.T) < 30)).map(f => ({ T: f.T, side: (f.attack || f.fouled) === 'home' ? 1 : -1, X: f.X }))].sort((a, b) => a.T - b.T);
  for (let i = 1; i < acts.length; i++) { const a = acts[i - 1], b = acts[i]; if (a.side === b.side || b.T <= a.T) continue;
    const extra = Math.min(P.SWING_MAX, Math.abs(b.X - a.X) / P.SWING_V - (b.T - a.T) / 60 * P.BASE_DWELL);
    if (extra > 0.05) SLOW.push({ T0: a.T, T1: b.T, extra }); } }
// missed / saved penalties (situation 'Penalty', not a goal): the clock also stops (PENMISS_PAUSE s) for the black-out
// with the spotlight on the box, then play goes on (no flood, no score change)
const penMisses = M.shots.filter(s => !s.goal && s.situation === 'Penalty').sort((a, b) => a.T - b.T)
  .map(s => ({ T: s.T - 1, dur: P.PENMISS_PAUSE, shot: s, miss: true, sched: { boOn: 0.5, blackout: 3.0 } }));
// kick-off of the match and of every later period: the clock waits KICK_PAUSE s with the line flat on the centre line
const kickPauses = [0, ...BREAKS.map(b => b.start)].map(T => ({ T, dur: P.KICK_PAUSE, kick: true }));
function currentPenMiss(t) { for (const s of penMisses) if (t >= s.t0 && t < s.t0 + s.dur + 1) return s; return null; }
function slowExtra(a, b) { let e = 0; for (const w of SLOW) { const o = Math.min(b, w.T1) - Math.max(a, w.T0); if (o > 0) e += w.extra * o / (w.T1 - w.T0); } return e; }
const knots = [];
function buildKnots() {
  knots.length = 0; let t = 0, si = 0; knots.push({ t: 0, T: 0 });
  const pauses = [...stops, ...penMisses, ...kickPauses].sort((a, b) => a.T - b.T);   // goal stops, missed-penalty and kick-off pauses
  const Tend = END + 1;
  for (let m = 0; m * 60 < Tend; m++) {
    const T0 = m * 60, T1 = Math.min((m + 1) * 60, Tend);
    let dwell = P.BASE_DWELL;
    for (const s of M.shots) if (!s.goal && s.T >= T0 && s.T < T1) dwell += P.SHOT_DWELL + P.SHOT_DWELL_XG * s.xg;
    // breakpoints inside the minute: slow-window edges (so each window's extra time stays inside it) and goal stops
    const edges = [...new Set(SLOW.flatMap(w => [w.T0, w.T1]).filter(x => x > T0 && x < T1))].sort((x, y) => x - y);
    let cur = T0;
    const advance = (x) => { if (x > cur) { t += (x - cur) / 60 * dwell + slowExtra(cur, x); knots.push({ t, T: x }); cur = x; } };
    for (const x of edges) {
      while (si < pauses.length && pauses[si].T < T1 && pauses[si].T <= x) {
        const st = pauses[si]; advance(st.T);
        t += st.dur; knots.push({ t, T: st.T, stop: st }); st.t0 = t - st.dur; si++;
      }
      advance(x);
    }
    while (si < pauses.length && pauses[si].T < T1) {
      const st = pauses[si]; advance(st.T);
      t += st.dur; knots.push({ t, T: st.T, stop: st }); st.t0 = t - st.dur; si++;
    }
    advance(T1);
  }
  T_FULLTIME = knots[knots.length - 1].t; T_VIDEO_END = T_FULLTIME + P.END_HOLD;
}
let T_FULLTIME = 0, T_VIDEO_END = 0; // video time when the match ends / when the video ends
buildKnots();
function matchTime(t) {
  let lo = 0, hi = knots.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (knots[mid].t <= t) lo = mid; else hi = mid; }
  const a = knots[lo], b = knots[hi];
  if (b.t <= a.t) return a.T;
  return a.T + (b.T - a.T) * clamp((t - a.t) / (b.t - a.t), 0, 1);
}
function currentStop(t) { for (const s of stops) if (t >= s.t0 && t < s.t0 + s.dur + 2.5) return s; return null; }
// video time at which the match clock reaches T (before a goal stop when T is a goal)
function videoTimeAt(T) { for (let i = 1; i < knots.length; i++) { const a = knots[i - 1], b = knots[i]; if (b.T > a.T && T <= b.T) return a.t + (b.t - a.t) * clamp((T - a.T) / (b.T - a.T), 0, 1); } return T_FULLTIME; }

export { kickPauses, penMisses, currentPenMiss, END, PERIODS, BREAKS, MAX_MIN, PERIOD_LABELS, periodIndex, dispMinute, clockText, chartMinute, goals, stops, CARDS, SLOW, slowExtra, knots, buildKnots, T_FULLTIME, T_VIDEO_END, matchTime, currentStop, videoTimeAt };

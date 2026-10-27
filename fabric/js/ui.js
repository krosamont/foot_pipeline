// Overlay UI: scoreboard, clock, player cards, shot tags, foul / kick-off tags, end statistics.
import * as THREE from '../lib/three.module.js';
import { M, W, H, P, clamp, sm } from './config.js';
import { PERIOD_LABELS, periodIndex, dispMinute, clockText, stops, CARDS, T_FULLTIME } from './timeline.js';
import { camera, TC, inkOn } from './scene.js';
import { state } from './engine.js';
import { heightAt, hills } from './relief.js';
import { drawCardFx } from './cardfx.js';

// ------------------------------------------------------------------ overlay UI
const $ = (q) => document.querySelector(q);
// scoreboard, title and CSS colours from the data: FotMob team logo (a square in the team colour if it does not load)
document.title = `${M.home.display || M.home.name} – ${M.away.display || M.away.name} · match fabric`;
for (const side of ['home', 'away']) { const c = TC[side]; document.documentElement.style.setProperty(`--${side}`, M[side].color); document.documentElement.style.setProperty(`--${side}-ink`, inkOn(c)); }
for (const [sel, t] of [['#home .name', M.home], ['#away .name', M.away]]) { const el = document.querySelector(sel); if (!el) continue;
  el.innerHTML = `<span class="flag" style="background:${t.color}"></span><span class="tn${(t.display || t.name).length > 8 ? ' long' : ''}">${t.display || t.name}</span>`; el.title = t.display || t.name;
  if (t.logo) { const img = new Image(); img.className = 'logo'; img.alt = ''; img.onload = () => el.querySelector('.flag').replaceWith(img); img.src = t.logo; } }
const ui = { hs: $('#home .score'), as: $('#away .score'), hg: $('#home .goals'), ag: $('#away .goals'), min: $('#clock .min'), half: $('#clock .half'), cards: $('#cards'), tips: $('#tips'), stats: $('#stats') };
const cardEls = new Map(), tipEls = new Map();
const flashEl = document.getElementById('flash'), foulEl = document.createElement('div'); foulEl.className = 'tip foul'; ui.tips.appendChild(foulEl);
// body part of a shot (WhoScored qualifiers, see build_data.py)
const BODY = { head: 'de la tête', right: 'pied droit', left: 'pied gauche', other: 'autre partie du corps' };
const GOAL_BODY = { head: 'But de la tête', right: 'But pied droit', left: 'But pied gauche', other: 'But' };
// kind of goal, from WhoScored's situation
const SITUATION = { RegularPlay: 'jeu placé', FastBreak: 'contre-attaque', FromCorner: 'corner', SetPiece: 'coup de pied arrêté', DirectFreekick: 'coup franc direct', Penalty: 'penalty', ThrowinSetPiece: 'touche' };
for (const s of stops) {
  const g = s.goal, p = g.player; const el = document.createElement('div'); el.className = 'card ' + g.team;
  // a goal card: photo, name, age ("21 ans"), then "But pied droit (0.05 xG)", then the context ("jeu placé"): body part · xG · kind of goal (WhoScored situation)
  // "But pied droit (0.05 xG)" then the context ("jeu placé"); "But contre son camp"
  const ctx = SITUATION[g.penalty ? 'Penalty' : g.situation];
  const how = g.own ? 'But contre son camp' : `${GOAL_BODY[g.body] || 'But'} (${(g.xg || 0).toFixed(2)} xG)${ctx ? `<br><span class="xg">${ctx}</span>` : ''}`;
  el.innerHTML = `<div class="photo" style="${p.photo ? `background-image:url(${p.photo})` : ''}"></div><div class="row"><span class="nm">${p.name || p.short}</span></div>${p.age ? `<div class="age">${p.age} ans</div>` : ''}<div class="sub">${how}</div>`;
  ui.cards.appendChild(el); cardEls.set(s, el);
}
// every tall shot spike carries a tag: who shot, what happened, and the xG that sets its height (10 m + 90 m x xG)
// a missed chance carries a small tag (no photo): name, what happened, body part (xG), context
const SHOT_OUTCOME = { SavedShot: 'tir arrêté', MissedShots: 'tir non cadré', ShotOnPost: 'tir sur le poteau' };
const SHOT_BODY = { head: 'tête', right: 'pied droit', left: 'pied gauche', other: 'autre partie du corps' };
for (const h of hills) if (h.xg >= P.TIP_XG) { const el = document.createElement('div'); el.className = 'tip shot';
  el.innerHTML = `<b>${h.player.name}</b><br>${SHOT_OUTCOME[h.type] || 'tir'}<br>${SHOT_BODY[h.body] || 'tir'} (${h.xg.toFixed(2)} xG)${SITUATION[h.situation] ? `<br><span class="ctx">${SITUATION[h.situation]}</span>` : ''}`;
  ui.tips.appendChild(el); tipEls.set(h, el); }
const v3 = new THREE.Vector3();
function project(X, h, Y) { v3.set(X - 52.5, h, Y - 34).project(camera); return [(v3.x + 1) / 2 * W, (1 - v3.y) / 2 * H]; }
// goal line of the scoreboard: minute then the scorer's last name (the full name on hover)
function fmtGoal(g) { const p = g.player || {}; return `${g.label}<span class="sc" title="${p.name || ''}">${p.short || ''}</span>`; }
// missed / saved penalty: a tag over the black-out (PENALTY SAVED / MISSED / POST · shooter)
const penEl = document.createElement('div'); penEl.className = 'tip foul'; ui.tips.appendChild(penEl);
const PEN_OUTCOME = { SavedShot: 'PENALTY ARRÊTÉ', MissedShots: 'PENALTY MANQUÉ', ShotOnPost: 'PENALTY · POTEAU' };
function updateUI(T, t) {
  const score = [0, 0]; const lists = { home: [], away: [] };
  for (const s of stops) { const vis = t >= s.t0 + s.sched.score; if (vis) { score[s.goal.team === 'home' ? 0 : 1]++; lists[s.goal.team].push(s.goal); } }
  ui.hs.textContent = score[0]; ui.as.textContent = score[1];
  ui.hg.innerHTML = lists.home.map(g => `<div><i></i>${fmtGoal(g)}</div>`).join(''); ui.ag.innerHTML = lists.away.map(g => `<div><i></i>${fmtGoal(g)}</div>`).join('');
  drawCardFx(t);
  ui.min.innerHTML = clockText(T) + '<sup>\'</sup>';
  const [dm] = dispMinute(T); ui.half.textContent = t >= T_FULLTIME ? 'FIN DU MATCH' : PERIOD_LABELS[periodIndex(T)];
  for (const s of stops) { const el = cardEls.get(s); const ph = t - s.t0; const a = ph < s.sched.cardIn ? 0 : ph < s.sched.cardOut ? sm((ph - s.sched.cardIn) / 0.3) : 1 - sm((ph - s.sched.cardOut) / 0.3);
    el.style.opacity = a.toFixed(3); if (a > 0) { const [x, y] = project(s.goal.X, 0, s.goal.Y); el.style.left = x + 'px'; el.style.top = y + 'px'; } }
  for (const [h, el] of tipEls) { const act = state.activeHills.find(a => a.h === h); const killed = stops.some(s => s.goal.T > h.T && t >= s.t0) || (T - h.T) > P.TIP_LIFE; const a = (act && !killed) ? Math.min(1, act.q.decay * 2.2 - 0.6) * state.flat * act.q.near * clamp((act.q.A - 4) / 6, 0, 1) * (1 - sm((T - h.T - P.TIP_LIFE + 10) / 10)) : 0;   // only over a spike that is really up (> 4 m); fades out over the last 10 s of TIP_LIFE
    el.style.opacity = Math.max(0, a).toFixed(3); if (a > 0) { const [x, y] = project(h.X, heightAt(h.X, h.Y) + 2.5, h.Y); el.style.left = clamp(x, 160, W - 160) + 'px'; el.style.top = Math.max(y - 10, 56) + 'px'; } }
  { const fl = state.flash, a = fl ? (t - fl.t0) / P.FLASH_DUR : 9; const on = a >= 0 && a < 1;
    flashEl.style.opacity = on ? (0.16 * Math.exp(-a * 7)).toFixed(3) : 0;
    foulEl.style.opacity = on ? (Math.min(1, a * 8) * (1 - sm((a - 0.6) / 0.4))).toFixed(3) : 0;
    if (on) { if (foulEl.dataset.k !== String(fl.T)) { foulEl.dataset.k = fl.T; foulEl.innerHTML = fl.kickoff ? '<b>COUP D\'ENVOI</b>' : `<b>FAUTE</b> · ${fl.player} <span>${fl.label}</span>`; }
      const [x, y] = project(fl.X, 2, fl.Y); foulEl.style.left = x + 'px'; foulEl.style.top = (y - 14) + 'px'; } }
  { const pm = state.penMiss, ph = state.penMissPhase; const a = pm ? sm((ph - pm.sched.boOn - 0.4) / 0.3) * (1 - sm((ph - pm.sched.blackout - 0.2) / 0.4)) : 0;
    penEl.style.opacity = a.toFixed(3);
    if (a > 0) { penEl.innerHTML = `<b>${PEN_OUTCOME[pm.shot.type] || 'PENALTY'}</b> · ${pm.shot.player.name} <span>${pm.shot.label}</span>`; penEl.style.left = (W / 2) + 'px'; penEl.style.top = (H * 0.3) + 'px'; } }
  const sa = sm((t - T_FULLTIME - 1.0) / 0.6); ui.stats.style.opacity = sa; ui.stats.style.transform = `translateY(${(1 - sa) * 20}px)`;
  if (sa > 0 && !ui.stats.dataset.built) { ui.stats.dataset.built = 1; const S = M.stats; const rows = [['xG', S.xg], ['TIRS', S.shots], ['CORNERS', S.corners], ['CARTONS', S.cards]];
    ui.stats.innerHTML = rows.map(([lab, [a, b]]) => { const sh = (a + b) > 0 ? a / (a + b) : 0.5; return `<div class="row"><span class="v l">${a}</span><span class="lab">${lab}</span><span class="v r">${b}</span><div class="track"><div class="fill" style="width:${(sh * 100).toFixed(1)}%"></div></div></div>`; }).join(''); }
}

export { $, ui, updateUI, project };

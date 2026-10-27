// "Comment lire" overlay (French): a frozen example frame (chosen in main.js), lightly dimmed, with notes and leader lines
// pointing at the two cloths, the border, the shot hill, the scoreboard, the clock and the momentum bar; the data
// sources at the bottom.
import { M, W, H } from './config.js';
import { seam, laneAt, state } from './engine.js';
import { heightAt } from './relief.js';
import { project } from './ui.js';
import { CH, cx } from './pulse.js';
import { chartMinute } from './timeline.js';

const layer = document.createElement('div'); layer.id = 'howtoLayer';
document.getElementById('stage').appendChild(layer);
const homeName = M.home.display || M.home.name, awayName = M.away.display || M.away.name;
// team names written in their team's colour
const homeTag = `<b style="color:${M.home.color}">${homeName}</b>`, awayTag = `<b style="color:${M.away.color}">${awayName}</b>`;

// a text block on the overlay; returns its box in stage coordinates
function block(html, x, y, side, cls = 'hw-note') {
  const el = document.createElement('div'); el.className = cls; el.innerHTML = html;
  el.style.top = y + 'px'; if (side === 'left') el.style.left = x + 'px'; else el.style.right = (W - x) + 'px';
  layer.appendChild(el);
  const s = layer.getBoundingClientRect(), r = el.getBoundingClientRect();
  return { L: r.left - s.left, R: r.right - s.left, T: r.top - s.top, B: r.bottom - s.top };
}
// a straight leader from the block's side to a point of the scene (a dot at the point), never through the text
function leader(svg, b, p, from = 'left') {
  if (!p) return;
  // from the side: a short horizontal stub out of the text column first, then straight to the point
  // always from the first line of the text: out of its left end, or of its right end when the point is on that side
  const y = b.T + 11, right = from === 'auto' ? p[0] > b.R : from === 'right';
  const pts = right ? [[b.R + 8, y], [b.R + 34, y], p] : [[b.L - 8, y], [b.L - 34, y], p];
  svg.insertAdjacentHTML('beforeend', `<polyline points="${pts.map(q => q.join(',')).join(' ')}" /><circle cx="${p[0]}" cy="${p[1]}" r="4" />`);
}

function buildRead() {
  layer.innerHTML = ''; layer.dataset.view = 'read';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('width', W); svg.setAttribute('height', H); layer.appendChild(svg);
  // points of the frozen scene
  const at = (X, Y, lift = 0.5) => project(X, heightAt(X, Y) + lift, Y);
  // each team is pointed at where its cloth is widest (middle of its ground on that lane), the border mid-width
  let lh = 0, la = 0; for (let l = 2; l < seam.length - 2; l++) { if (seam[l] > seam[lh]) lh = l; if (seam[l] < seam[la]) la = l; }
  const homeP = at(Math.max(6, seam[lh] * 0.5), lh * 2), awayP = at(Math.min(99, seam[la] + (105 - seam[la]) * 0.5), la * 2);
  const s34 = laneAt(seam, 34), seamP = at(s34, 34, 0.3);   // the border in the middle of the width
  const hill = (state.activeHills || []).slice().sort((a, b) => b.q.A - a.q.A)[0];
  const hillP = hill ? at(hill.h.X, hill.h.Y, 1) : null;
  const momP = [cx(chartMinute(state.T)), CH.y];

  // 1. the shot peak: top centre, leader down to the peak
  leader(svg, block(`<b>Les pics sont les tirs.</b> La montagne jaillit au moment du tir, plus <b>large</b> quand l'occasion est grosse (xG). Un but : la grande flèche.`, 440, 96, 'left'), hillP, 'auto');
  // 2-4. right column, in the order of their targets (top to bottom) so the leaders never cross
  const notes = [
    { y: seamP[1], html: `<b>La frontière, c'est le territoire.</b> Elle avance quand une équipe progresse avec le ballon et se lève en vague quand elle pousse.`, pts: [seamP] },
    { y: Math.min(homeP[1], awayP[1]), html: `<b>Les deux couleurs sont les deux équipes</b> : ${homeTag} part de son but, ${awayTag} du sien.`, pts: [homeP, awayP] },
    { y: momP[1], minY: CH.y - 130, html: `<b>Momentum</b> (menace créée) : au-dessus ${homeTag}, en dessous ${awayTag}. Cliquer sur la courbe pour se déplacer.<div class="hw-keys"><span>⚽ but</span><span><i class="k-y"></i> carton jaune</span><span><i class="k-r"></i> carton rouge</span><span>⇄ remplacement</span></div>`, pts: [momP] },
  ].sort((a, b) => a.y - b.y);
  let y = 214;
  for (const n of notes) { const b = block(n.html, 1235, Math.max(y, n.minY || 0), 'right'); n.pts.forEach(p => leader(svg, b, p)); y = b.B + 26; }   // (momentum: low, near its bar)
  // the rest, without leaders, small at the bottom
  const foot = [`<b>Sources</b> : WhoScored · FotMob`];
  block(foot.join('<br><br>'), 1235, y - 8, 'right', 'hw-sources');   // under the notes, clear of the momentum bar
  addBar();
}

function addBar() {
  const bar = document.createElement('div'); bar.className = 'hw-bar';
  bar.innerHTML = `<span class="hw-title">Comment lire</span><span class="hw-close" title="Fermer (Échap)">✕</span>`;
  bar.querySelector('.hw-close').addEventListener('click', (e) => { e.stopPropagation(); hideHowto(); });
  layer.appendChild(bar);
}

let onClose = null;
let example = null;   // the shot of the frozen example frame (caption)
const link = () => document.getElementById('howto');
const tips = () => document.getElementById('tips');   // the scene's shot / foul tags are hidden under the guide
// The guide shown to readers is one generic picture (assets/howto/comment-lire.jpg, made by tools/make_howto.js from the
// live build below on a neutral "Équipe A - Équipe B" frame): it opens at once, the same for every match. If the
// picture is missing, the notes are built live on the scene as it is.
const HOWTO_IMG = '../assets/howto/comment-lire.jpg';
function showImage() {
  layer.innerHTML = ''; layer.dataset.view = 'image';
  const img = new Image(); img.className = 'hw-img'; img.alt = 'Comment lire la carte';
  img.onerror = () => { if (layer.dataset.view === 'image') buildRead(); };
  img.src = HOWTO_IMG; layer.appendChild(img); addBar();
}
function showHowto(close, shot, live = false) { onClose = close; example = shot || null; layer.classList.add('on'); if (link()) link().style.visibility = 'hidden'; if (tips()) tips().style.visibility = 'hidden';
  if (live) buildRead(); else showImage(); }
function hideHowto() { if (!layer.classList.contains('on')) return; layer.classList.remove('on'); if (link()) link().style.visibility = ''; if (tips()) tips().style.visibility = ''; layer.innerHTML = ''; const f = onClose; onClose = null; if (f) f(); }
const isHowtoOpen = () => layer.classList.contains('on');
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideHowto(); });

export { showHowto, hideHowto, isHowtoOpen };

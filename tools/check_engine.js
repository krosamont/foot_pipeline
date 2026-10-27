// Engine rules check for the 3D match portrait — works for any match built with build_data.py.
// usage: node tools/check_engine.js [--match <name>]        (serves the project itself, runs headless Chrome, exits 1 on a FAIL)
//
// Rules checked (the user's rules, measured on the simulation):
//   1. every shot / goal / corner: the attacking side's line is past the action point when it happens
//   2. every foul: the line is at the foul point (<= 6 m) when it happens
//   3. CSV actions (passes received, carries...): >= 85 % happen on their side of the line (or within 5 m)
//   4. after every goal: play restarts flat on the halfway line (52.5 m, straight) and stays there >= 1.5 s
//   5. goal build-up: the scorer's line does not step back (<= 2 m) while the scorer's team has the ball before a goal
//      (CSV possession, at least the last 5 s) and until the flood starts, from the other side's last shot / foul / corner on (that one is shown), foul restarts excepted
//   6. no shot hill stands (> 1 m) in the other side's ground (> 10 m beyond the line)
//   7. smooth: the line never moves faster than 150 m/s in normal play, and gains + losses at once in < 3 % of frames
//   9. every break (half-time, before / during extra time): the line is flat on the centre line (52.5 m) before the map turns and during the whole turn
//   8. team identity: home / away as in FotMob; names, logos and colours come from <match>_match_info.csv, are the ones shown on screen, and the
//      two cloth colours are far enough apart (CIE76 delta E >= 25)
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('./browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const MATCH = (process.argv.indexOf('--match') > 0) ? process.argv[process.argv.indexOf('--match') + 1] : null;   // fabric/data/<match>.js (default: data.js)
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res);
});

(async () => {
  await new Promise(r => server.listen(0, r));
  const b = await puppeteer.launch(launchOptions([]));
  const p = await b.newPage(); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1${MATCH ? '&match=' + encodeURIComponent(MATCH) : ''}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  const R = await p.evaluate(() => {
    const S = window.__state, tl = window.__timeline, NL = 35;
    const lane = (s, Y) => { const f = Math.min(Y / 2, NL - 1.001), i = Math.floor(f); return s[i] * (1 - (f - i)) + s[i + 1] * (f - i); };
    const out = {};
    // 1-2. key actions
    const E = window.__percees.slice().sort((a, b) => a.tv - b.tv); let okA = 0, okF = 0, nA = 0, nF = 0; const missA = [], missF = [];
    for (const e of E) { window.__seekLight(e.tv); const s = lane(S.seamNow, e.Y);
      if (e.foulT !== undefined) { nF++; if (Math.abs(s - e.X) <= 6) okF++; else missF.push([e.T, +(s - e.X).toFixed(1)]); }
      else { nA++; if (e.side * (s - e.X) >= 0) okA++; else missA.push([e.T, +(e.side * (s - e.X)).toFixed(1)]); } }
    out.actions = { ok: okA, n: nA, miss: missA }; out.fouls = { ok: okF, n: nF, miss: missF };
    // 3. CSV actions placement
    const P2 = window.__prog.map(([T, side, X, Y]) => ({ side, X, Y, tv: window.__videoTimeAt(T) })).sort((a, b) => a.tv - b.tv); let inside = 0;
    for (const e of P2) { window.__seekLight(e.tv); if (e.side * (lane(S.seamNow, e.Y) - e.X) >= -5) inside++; }
    out.placement = { ok: inside, n: P2.length };
    // 4-5. goals
    out.kickoff = []; out.buildup = [];
    // kick-off of the match and after every break: flat on the halfway line for 1.5 s
    const L = window.MATCH.periods.list || [];
    for (const [lab, t0] of [['start', 0], ...L.slice(1).map((q, k) => ['period ' + (k + 2), window.__videoTimeAt(q.start)])]) { let flat = true;
      for (const d of [0, 0.5, 1, 1.5]) { window.__seekLight(t0 + d + 0.01); const s = S.seamNow; if (Math.max(...s) - Math.min(...s) > 0.5 || Math.abs(s[17] - 52.5) > 0.5 || (S.calm ?? 1) > 0.05) flat = false; }   // line on the centre line AND relief laid flat
      out.kickoff.push([lab, flat]); }
    for (const st of tl.stops) {
      const end = st.t0 + st.dur; let flat = true;
      for (const d of [0, 0.5, 1, 1.5]) { window.__seekLight(end + d); const s = S.seamNow; if (Math.max(...s) - Math.min(...s) > 0.5 || Math.abs(s[17] - 52.5) > 0.5) flat = false; }
      out.kickoff.push([st.goal.label, flat]);
      const side = st.goal.team === 'home' ? 1 : -1; let peak = null, worst = 0;
      for (let t = window.__buildStart(st); t < st.t0 + (st.pen ? st.sched.flood : window.__P.FLOOD_AT); t += 0.05) { window.__seekLight(t); if (S.seamMode !== 'normal') { peak = null; continue; }
        const s = S.seamNow.map(v => side * v); if (!peak) peak = s.slice(); for (let l = 0; l < NL; l++) { peak[l] = Math.max(peak[l], s[l]); worst = Math.max(worst, peak[l] - s[l]); } }
      out.buildup.push([st.goal.label, +worst.toFixed(1)]);
    }
    // 6-7. hills, speed and one-way movement over the whole video
    let tall = 0, vmax = 0, moving = 0, mixed = 0, prev = null, prevMode = null;
    for (let t = 0; t < tl.T_VIDEO_END; t += 1 / 30) { window.__seekLight(t); const s = S.seamNow;
      for (const { h, q } of S.activeHills) { const o = (h.team === 'home' ? 1 : -1) * (h.X - lane(s, h.Y)); if (o > 10 && q.A > 1) tall++; }
      if (prev && S.seamMode === 'normal' && prevMode === 'normal') { const v = s.map((x, l) => (x - prev[l]) * 30); const m = v.filter(x => Math.abs(x) > 0.3);
        vmax = Math.max(vmax, ...v.map(Math.abs)); if (m.length >= 3) { moving++; if (m.some(x => x > 0) && m.some(x => x < 0)) mixed++; } }
      prev = s.slice(); prevMode = S.seamMode; }
    // 9. half-time: flat on the centre line from the start of the turn to the second-half kick-off
    { const Pp = window.__P, L = window.MATCH.periods.list || [{ end: window.MATCH.periods.firstHalfEnd }, { start: window.MATCH.periods.secondHalfStart }];
      let worst = 0; for (let k = 1; k < L.length; k++) { const a = window.__videoTimeAt(L[k - 1].end) + Pp.HALF_FLAT, b = window.__videoTimeAt(L[k].start);
        for (let t = a; t <= b; t += 0.1) { window.__seekLight(t); const s = S.seamNow; worst = Math.max(worst, Math.max(...s) - 52.5, 52.5 - Math.min(...s)); out.breakCalm = Math.max(out.breakCalm || 0, S.calm ?? 1); } }
      out.half = +worst.toFixed(2); out.breaks = L.length - 1; }
    // 8. team identity
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    out.identity = ['home', 'away'].map(side => { const t = window.MATCH[side], el = document.querySelector(`#${side} .name`);
      return { side, fotmobSide: t.fotmob_side, source: t.source, color: t.color, css: css(`--${side}`), code: el.textContent.trim(), want: t.display || t.name, logo: !!t.logo, logoShown: !!el.querySelector('img.logo') }; });
    out.contrast = window.MATCH.home.contrast;
    out.hills = tall; out.speed = +vmax.toFixed(0); out.mixed = { mixed, moving };
    return out;
  });
  let fail = 0; const line = (ok, name, detail) => { if (!ok) fail++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  ${detail}`); };
  line(R.actions.ok === R.actions.n, 'shots / goals / corners reached by the attacking line', `${R.actions.ok}/${R.actions.n} ${R.actions.miss.length ? JSON.stringify(R.actions.miss) : ''}`);
  line(R.fouls.ok === R.fouls.n, 'line at every foul point (<= 6 m)', `${R.fouls.ok}/${R.fouls.n} ${R.fouls.miss.length ? JSON.stringify(R.fouls.miss) : ''}`);
  line(R.placement.ok / R.placement.n >= 0.85, 'CSV actions on their side of the line (>= 85 %)', `${(100 * R.placement.ok / R.placement.n).toFixed(1)} %`);
  line(R.kickoff.every(k => k[1]), 'kick-off on the halfway line, relief flat: start, every break, every goal (1.5 s)', JSON.stringify(R.kickoff.filter(k => !k[1])));
  line(R.buildup.every(k => k[1] <= 2), 'no step back of the scorer before a goal (<= 2 m)', JSON.stringify(R.buildup.filter(k => k[1] > 2)));
  line(R.hills === 0, 'no shot hill standing in the other side ground', `${R.hills} samples`);
  line(R.speed <= 150, 'line speed in normal play <= 150 m/s', `${R.speed} m/s`);
  line(R.mixed.mixed / Math.max(1, R.mixed.moving) < 0.03, 'gain and loss at once in < 3 % of moving frames', `${R.mixed.mixed}/${R.mixed.moving}`);
  line(R.half <= 0.5 && (R.breakCalm || 0) <= 0.05, 'every break (half-time, extra time): line flat on the centre line during the whole map turn', `${R.breaks} break(s), max gap ${R.half} m, relief ${((R.breakCalm || 0) * 100).toFixed(0)} %`);
  const idOk = R.identity.every(i => i.source !== 'default' && (!i.fotmobSide || i.fotmobSide === i.side) && i.css === i.color && i.code === i.want && (!i.logo || i.logoShown));
  line(idOk && R.contrast >= 25, 'team names / logos / colours from match_info.csv, shown on screen, cloths distinct (dE >= 25)', `${JSON.stringify(R.identity.map(i => [i.code, i.color, i.source, i.logoShown ? 'logo' : 'no logo']))} dE ${R.contrast}`);
  console.log(fail ? `\n${fail} rule(s) failed` : '\nall rules pass');
  await b.close(); server.close(); process.exit(fail ? 1 : 0);
})();

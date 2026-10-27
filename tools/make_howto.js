// Makes the generic "Comment lire" picture shown by the 3D page for every match: assets/howto/comment-lire.jpg.
// A real frame is anonymised (Équipe A in blue, Équipe B in red, no names, no logos) at a moment where the score is
// 1-0 and a shot peak stands, then the notes are built on it (fabric/js/howto.js) and the stage is captured.
// usage: node tools/make_howto.js [source match, default 2026-10-14_roma_vs_real-madrid]
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('./browser');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const SRC = process.argv[2] || '2026-10-14_roma_vs_real-madrid', GEN = '_howto_generic';
const OUT = path.join(ROOT, 'assets', 'howto', 'comment-lire.jpg');

// 1. anonymised copy of the match data
const js = fs.readFileSync(path.join(ROOT, 'fabric', 'data', SRC + '.js'), 'utf8');
const M = JSON.parse(js.slice(js.indexOf('{'), js.lastIndexOf('}') + 1));
Object.assign(M.home, { name: 'Équipe A', display: 'Équipe A', color: '#2f6fd6', logo: null });
Object.assign(M.away, { name: 'Équipe B', display: 'Équipe B', color: '#d1242f', logo: null });
const anon = (p) => p && typeof p === 'object' ? Object.assign(p, { name: 'Joueur', short: 'Joueur', photo: null, club: null, age: null }) : p;
for (const s of M.shots) anon(s.player);
for (const c of M.cards || []) anon(c.player);
for (const s of M.subs || []) { s.player = ''; s.off = ''; }
for (const f of M.fouls || []) f.player = '';
fs.writeFileSync(path.join(ROOT, 'fabric', 'data', GEN + '.js'), 'window.MATCH = ' + JSON.stringify(M) + ';\n');
// the frame: a home shot (not a goal) after the first home goal and before any away goal -> score 1-0
const goals = M.shots.filter(s => s.goal).sort((a, b) => a.T - b.T);
const g1 = goals.find(g => g.team === 'home'), gAway = goals.find(g => g.team === 'away' && g1 && g.T > g1.T);
const shot = M.shots.filter(s => !s.goal && s.team === 'home' && g1 && s.T > g1.T && (!gAway || s.T < gAway.T) && !goals.some(g => g.team === 'away' && g.T < s.T)).sort((a, b) => b.xg - a.xg)[0];
if (!shot) { console.error('no home shot at 1-0 in', SRC); process.exit(1); }

// 2. capture
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png', '.jpg': 'image/jpeg' };
const server = http.createServer((q, r) => { const p = path.join(ROOT, decodeURIComponent(q.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(r); });
(async () => {
  await new Promise(r => server.listen(0, r));
  const b = await puppeteer.launch(launchOptions([])); const p = await b.newPage();
  await p.setViewport({ width: 1257, height: 835, deviceScaleFactor: 2 }); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1&match=${GEN}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  await p.evaluate((T) => { window.__howtoShotT = T; window.__howtoLive(true); document.querySelector('#howtoLayer .hw-bar')?.remove(); }, shot.T);
  await new Promise(r => setTimeout(r, 500));
  const score = await p.evaluate(() => [document.querySelector('#home .score').textContent, document.querySelector('#away .score').textContent].join('-'));
  const el = await p.$('#stage'); await el.screenshot({ path: OUT, type: 'jpeg', quality: 88 });
  console.log(`written ${path.relative(ROOT, OUT)} (${(fs.statSync(OUT).size / 1024).toFixed(0)} KB) - frame of the ${shot.label} home shot, score ${score}`);
  await b.close(); server.close();
})();

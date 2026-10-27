// Screenshots of the 3D at given video times, for checking a change by eye.
// usage: node tools/debug/snap.js <match> <prefix> <t1,t2,...|expr> [out/debug]
//   times: numbers (video seconds), or 'penmiss' (each missed-penalty pause), 'goals' (each goal stop), 'breaks'
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json' };
const [match, prefix = 'snap', spec = '5', outDir = 'out/debug'] = process.argv.slice(2);
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res);
});
(async () => {
  await new Promise(r => server.listen(0, r)); fs.mkdirSync(path.join(ROOT, outDir), { recursive: true });
  const b = await puppeteer.launch(launchOptions([]));
  const p = await b.newPage(); await p.setViewport({ width: 1257, height: 835 }); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1&match=${encodeURIComponent(match)}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  const times = await p.evaluate((spec) => {
    const tl = window.__timeline, M = window.MATCH, va = window.__videoTimeAt;
    if (spec === 'penmiss') return tl.knots.filter(k => k.stop && k.stop.miss).flatMap(k => [0.3, 1.5, 2.6, 4.3].map(d => k.stop.t0 + d));
    if (spec === 'goals') return tl.stops.flatMap(s => [s.t0 - 0.3, s.t0 + s.dur + 0.3]);
    if (spec === 'breaks') return (M.periods.list || []).slice(1).flatMap((q, i) => [va(M.periods.list[i].end) + 1, va(q.start) - 0.5, va(q.start) + 1]);
    if (spec.startsWith('shot:')) { const s = M.shots.find(s => s.player && (s.player.name || '').includes(spec.slice(5))); return s ? [-0.3, 0.1, 0.5, 1.0].map(d => va(s.T) + d) : []; }
    return spec.split(',').map(Number);
  }, spec);
  times.sort((a, b) => a - b);
  for (const t of times) { await p.evaluate(t => window.__seek(t), t);
    const f = path.join(ROOT, outDir, `${prefix}_${match}_${t.toFixed(1)}.png`); await p.screenshot({ path: f }); console.log(f); }
  await b.close(); server.close();
})();

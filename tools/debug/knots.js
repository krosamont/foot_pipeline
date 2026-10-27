// Dramatic timeline knots (video time t <-> match time T) between two match times, with the stop / pause kinds.
// usage: node tools/debug/knots.js <match> <T0> <T1>
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };
const [match, A, Z] = process.argv.slice(2);
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res); });
(async () => { await new Promise(r => server.listen(0, r));
  const b = await puppeteer.launch(launchOptions([]));
  const p = await b.newPage(); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1&match=${encodeURIComponent(match)}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  const out = await p.evaluate((A, Z) => window.__timeline.knots.filter(k => k.T >= A && k.T <= Z).map(k => `t=${k.t.toFixed(2)} T=${k.T.toFixed(1)} ${k.stop ? (k.stop.kick ? 'KICK' : k.stop.miss ? 'PENMISS' : 'GOAL') : ''}`), +A, +Z);
  console.log(out.join('\n')); await b.close(); server.close(); })();

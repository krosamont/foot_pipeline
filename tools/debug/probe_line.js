// Front line between two video times: min / mean / max of the lanes and the mode.
// usage: node tools/debug/probe_line.js <match> <t0> <t1> [step]   (t0 = 'goal<k>' starts at the kick-off after goal k, t1 = seconds after)
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };
const [match, a, z, st = '0.1'] = process.argv.slice(2);
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res); });
(async () => { await new Promise(r => server.listen(0, r));
  const b = await puppeteer.launch(launchOptions([]));
  const p = await b.newPage(); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1&match=${encodeURIComponent(match)}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  const out = await p.evaluate((a, z, st) => { const S = window.__state, o = [];
    if (/^goal\d+$/.test(a)) { const g = window.__timeline.stops[+a.slice(4)]; a = g.t0 + g.dur - 0.2; z = a + +z; } else { a = +a; z = +z; }
    for (let t = a; t <= z + 1e-9; t += st) { window.__seekLight(t); const s = S.seamNow;
      const act = window.__percees.filter(q => q.env > 0).map(q => `${q.T}${q.foulT !== undefined ? 'F' : ''}:${q.env.toFixed(2)}`).join(' ');
      o.push(`${t.toFixed(2)} T=${S.T.toFixed(1)} ${S.seamMode} min=${Math.min(...s).toFixed(1)} mean=${(s.reduce((x, y) => x + y) / s.length).toFixed(1)} max=${Math.max(...s).toFixed(1)} runs[${act}]`); }
    return o; }, a, z, +st);
  console.log(out.join('\n')); await b.close(); server.close(); })();

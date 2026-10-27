// Front line around one action: lane at the action's Y, mode, active runs (env) and the CSV base line.
// usage: node tools/debug/probe_action.js <match> <T of the action (match s)> [seconds before] [seconds after]
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };
const [match, T0, before = '2', after = '0.6'] = process.argv.slice(2);
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res); });
(async () => { await new Promise(r => server.listen(0, r));
  const b = await puppeteer.launch(launchOptions([]));
  const p = await b.newPage(); p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1&match=${encodeURIComponent(match)}`); await p.waitForFunction('window.__ready', { timeout: 60000 });
  const out = await p.evaluate((T0, before, after) => { const S = window.__state, NL = 35, o = [];
    const lane = (s, Y) => { const f = Math.min(Y / 2, NL - 1.001), i = Math.floor(f); return s[i] * (1 - (f - i)) + s[i + 1] * (f - i); };
    const e = window.__percees.find(e => e.T === T0); if (!e) return ['no run at T=' + T0];
    o.push(`action T=${e.T} side=${e.side} X=${e.X} Y=${e.Y} tv=${e.tv.toFixed(2)} foul=${e.foulT !== undefined} counter=${e.counter} minStart=${e.minStart.toFixed(2)}`);
    for (let t = e.tv - before; t <= e.tv + after; t += 0.1) { window.__seekLight(t);
      const act = window.__percees.filter(q => q.env > 0).map(q => `${q.T}${q.foulT !== undefined ? 'F' : ''}:${q.env.toFixed(2)}`).join(' ');
      o.push(`${t.toFixed(2)} T=${S.T.toFixed(0)} ${S.seamMode} lane=${lane(S.seamNow, e.Y).toFixed(1)} dir=${S.dir} runs[${act}]`); }
    return o; }, +T0, +before, +after);
  console.log(out.join('\n')); await b.close(); server.close(); })();

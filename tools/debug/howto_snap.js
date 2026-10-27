// Screenshots of the "Comment lire" overlay: node tools/debug/howto_snap.js <match> <video time> [prefix]
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.js': 'text/javascript', '.html': 'text/html', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png' };
const [match, t = '27.4', prefix = 'howto'] = process.argv.slice(2);
const srv = http.createServer((q, r) => { const p = path.join(ROOT, decodeURIComponent(q.url.split('?')[0])); if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); return r.end(); } r.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(r); });
(async () => { await new Promise(r => srv.listen(0, r)); const b = await puppeteer.launch(launchOptions([])); const p = await b.newPage(); await p.setViewport({ width: 1257, height: 835 });
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(`http://127.0.0.1:${srv.address().port}/fabric/index.html?render=1&match=${match}`); await p.waitForFunction('window.__ready');
  await p.evaluate(t => window.__seek(t), +t); await p.click('#howto'); await new Promise(r => setTimeout(r, 400));
  await p.screenshot({ path: path.join(ROOT, `out/debug/${prefix}_read.png`) });
  console.log('errors:', errs.length ? errs : 'none'); await b.close(); srv.close(); })();

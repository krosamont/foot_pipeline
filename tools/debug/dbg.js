const puppeteer = require('puppeteer-core');
const { launchOptions } = require('../browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => { const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0])); if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); } res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res); });
(async () => {
  await new Promise(r => server.listen(0, r));
  const browser = await puppeteer.launch(launchOptions([]));
  const page = await browser.newPage(); page.on('pageerror', e => console.error('PAGE ERROR', e.message));
  await page.setViewport({ width: 1257, height: 835 });
  await page.goto(`http://127.0.0.1:${server.address().port}/fabric/index.html?render=1`, { waitUntil: 'networkidle0' });
  await page.waitForFunction(() => window.__ready === true);
  for (const t of process.argv.slice(2).map(Number)) { await page.evaluate(t => window.__seek(t), t); console.log(JSON.stringify(await page.evaluate(() => window.__dbg()))); }
  await browser.close(); server.close();
})();

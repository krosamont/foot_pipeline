// Render fabric/index.html to PNG frames with headless Chrome, then encode with ffmpeg.
// usage: node tools/render.js [--match <name>] [--fps 30] [--from 0] [--to <end, default: until the video ends>] [--out out/frames] [--times 1.0,2.5] [--scale 2]
const puppeteer = require('puppeteer-core');
const { launchOptions } = require('./browser');   // Chrome + WebGL settings for Mac or server
const http = require('http'), fs = require('fs'), path = require('path');
const args = Object.fromEntries(process.argv.slice(2).join(' ').split('--').filter(Boolean).map(s => { const [k, ...v] = s.trim().split(' '); return [k, v.join(' ') || true]; }));
const ROOT = path.resolve(__dirname, '..');
const FPS = +(args.fps || 30), FROM = +(args.from || 0), TO = +(args.to || 100000), SCALE = +(args.scale || 2);
const OUT = path.resolve(ROOT, args.out || 'out/frames');
const TIMES = args.times ? String(args.times).split(',').map(Number) : null;
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res);
});
(async () => {
  await new Promise(r => server.listen(0, r));
  const port = server.address().port;
  fs.mkdirSync(OUT, { recursive: true });
  // the page may crash on long renders (GPU / memory): relaunch, jump straight to the frame (window.__seekTo replays the
  // simulation exactly) and carry on; frames already on disk are kept
  let times = TIMES || null;   // built once the page tells us how long the video is
  const t0 = Date.now(); let i = 0, browser = null, page = null, tries = 0, done = false;
  while (!done) {
    try {
      browser = await puppeteer.launch(launchOptions(['--hide-scrollbars', '--font-render-hinting=none']));
      page = await browser.newPage();
      page.on('pageerror', e => console.error('PAGE ERROR', e.message));
      page.on('requestfailed', r => console.error('request failed', r.url()));
      page.on('response', r => { if (r.status() >= 400) console.error('HTTP', r.status(), r.url()); });
      page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.error('console', m.text()); });
      await page.setViewport({ width: 1257, height: 835, deviceScaleFactor: SCALE });
      await page.goto(`http://127.0.0.1:${port}/fabric/index.html?render=1${args.match ? '&match=' + encodeURIComponent(args.match) : ''}`, { waitUntil: 'networkidle0' });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => window.__ready === true, { timeout: 30000 });
      // every player photo and team logo must be loaded before the first frame (retried, then reported)
      const img = await page.evaluate(async () => {
        const urls = [...new Set([window.MATCH.home.logo, window.MATCH.away.logo, ...window.MATCH.shots.map(s => s.player && s.player.photo), ...(window.MATCH.cards || []).map(c => c.player && c.player.photo)].filter(Boolean))];
        const load = (u) => new Promise(res => { const im = new Image(); im.onload = () => res(true); im.onerror = () => res(false); im.src = u; });
        const bad = []; for (const u of urls) { let ok = false; for (let k = 0; k < 3 && !ok; k++) ok = await load(u + (k ? (u.includes('?') ? '&' : '?') + 'r=' + k : '')); if (!ok) bad.push(u); }
        return { n: urls.length, bad }; });
      if (i === 0) console.log(`images: ${img.n - img.bad.length}/${img.n} loaded` + (img.bad.length ? ' - MISSING: ' + img.bad.join(' ') : ''));
      if (!times) { const end = Math.min(TO, await page.evaluate(() => window.__timeline.T_VIDEO_END) + 1 / FPS);
        times = Array.from({ length: Math.round((end - FROM) * FPS) + 1 }, (_, k) => FROM + k / FPS); }
      if (i === 0) { const tl = await page.evaluate(() => ({ stops: window.__timeline.stops.map(s => [s.goal.label, s.goal.player.short, +s.t0.toFixed(2)]), fullTime: +window.__timeline.T_FULLTIME.toFixed(2) }));
        console.log('timeline', JSON.stringify(tl)); }
      else { console.log('resuming at frame', i); if (!TIMES) await page.evaluate(t => window.__seekTo(t), times[i - 1]); }
      for (; i < times.length; i++) {
        const info = await page.evaluate(t => window.__seek(t), times[i]);
        if (info && info.done && !TIMES) { console.log('timeline finished at', times[i]); break; }
        const name = TIMES ? `t_${times[i].toFixed(2)}.png` : `f_${String(i).padStart(5, '0')}.jpg`;
        await page.screenshot(TIMES ? { path: path.join(OUT, name), clip: { x: 0, y: 0, width: 1257, height: 835 } } : { path: path.join(OUT, name), type: 'jpeg', quality: 96, clip: { x: 0, y: 0, width: 1257, height: 835 } });
        if (i % 100 === 0) console.log(i, '/', times.length, times[i].toFixed(2), 's', ((Date.now() - t0) / 1000).toFixed(0) + 's elapsed');
      }
      done = true;
    } catch (e) {
      console.error('render error at frame', i, e.message); if (++tries > 8) throw e;
      try { await browser.close(); } catch (_) {}
    }
  }
  await browser.close(); server.close();
  console.log('frames written to', OUT);
})().catch(e => { console.error(e); process.exit(1); });

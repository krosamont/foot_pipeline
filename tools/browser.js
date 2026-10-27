// Headless Chrome for the 3D page, on a Mac or on a server (Linux, Docker), shared by render.js, check_engine.js and
// tools/debug/*.js.
//   Chrome: $CHROME, else the newest Chrome for Testing in the puppeteer cache ($PUPPETEER_CACHE_DIR or
//           ~/.cache/puppeteer, installed by setup.sh), else a system Chrome / Chromium.
//   WebGL:  macOS -> the GPU (ANGLE on Metal); elsewhere, or with GL=swiftshader -> software WebGL (SwiftShader),
//           which needs no graphics card (servers, Docker). On Linux the sandbox is off (containers run as root).
const fs = require('fs'), path = require('path'), os = require('os');

function chromePath() {
  if (process.env.CHROME) return process.env.CHROME;
  const cache = path.join(process.env.PUPPETEER_CACHE_DIR || path.join(os.homedir(), '.cache', 'puppeteer'), 'chrome');
  const inside = {
    darwin: ['chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing', 'chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'],
    linux: ['chrome-linux64/chrome'], win32: ['chrome-win64/chrome.exe'] }[process.platform] || [];
  if (fs.existsSync(cache)) {
    const dirs = fs.readdirSync(cache).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));   // newest first
    for (const d of dirs) for (const rel of inside) { const p = path.join(cache, d, rel); if (fs.existsSync(p)) return p; }
  }
  const system = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'];
  const found = system.find(p => fs.existsSync(p));
  if (found) return found;
  throw new Error('Chrome not found: run ./setup.sh (installs Chrome for Testing) or set CHROME=/path/to/chrome');
}

function chromeArgs(extra = []) {
  const software = process.env.GL === 'swiftshader' || process.platform !== 'darwin';
  const gl = software ? ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : ['--use-gl=angle', '--use-angle=metal'];
  const linux = process.platform === 'linux' ? ['--no-sandbox', '--disable-dev-shm-usage'] : [];
  return [...gl, '--enable-webgl', '--ignore-gpu-blocklist', ...linux, ...extra];
}

// puppeteer.launch options for the 3D page
function launchOptions(extraArgs = []) {
  return { executablePath: chromePath(), headless: true, args: chromeArgs(extraArgs), protocolTimeout: 600000 };
}

module.exports = { chromePath, chromeArgs, launchOptions };

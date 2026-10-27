#!/usr/bin/env bash
# One-time setup of the project, on a Mac or on a Linux server (Debian / Ubuntu).
#
#   ./setup.sh               Python env (.venv) + Node packages + Chrome for Testing + ffmpeg check
#   ./setup.sh --system      also install the system packages (Linux: apt-get, needs root / sudo; macOS: Homebrew ffmpeg)
#   ./setup.sh --playwright  also install Playwright's Chromium (last-resort WhoScored download, rarely needed)
#   ./setup.sh --check       finish with the engine rules on France-England (a few minutes)
#
# Afterwards:   .venv/bin/python -m pmd.make3d --fotmob <FotMob match id>
set -euo pipefail
cd "$(dirname "$0")"

CHROME_VERSION="131.0.6778.204"          # the Chrome for Testing the 3D was checked with (puppeteer-core 23)
SYSTEM=0; PLAYWRIGHT=0; CHECK=0
for a in "$@"; do case "$a" in
  --system) SYSTEM=1 ;; --playwright) PLAYWRIGHT=1 ;; --check) CHECK=1 ;;
  *) echo "unknown option $a"; exit 2 ;; esac; done
say() { printf '\n== %s\n' "$*"; }
OS="$(uname -s)"

# ---------------------------------------------------------------- system packages
if [ "$SYSTEM" = 1 ]; then
  say "system packages"
  if [ "$OS" = "Linux" ] && command -v apt-get >/dev/null; then
    SUDO=""; [ "$(id -u)" != 0 ] && SUDO="sudo"
    $SUDO apt-get update
    # python, node, ffmpeg, fonts, and the libraries headless Chrome needs
    $SUDO apt-get install -y --no-install-recommends python3 python3-venv python3-pip nodejs npm ffmpeg ca-certificates \
      fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libxshmfence1 libx11-xcb1 libxss1 libgtk-3-0
  elif [ "$OS" = "Darwin" ] && command -v brew >/dev/null; then
    command -v ffmpeg >/dev/null || brew install ffmpeg
    command -v node >/dev/null || brew install node
  else
    echo "install python3 (>= 3.10), node (>= 18) and ffmpeg yourself"
  fi
fi

# ---------------------------------------------------------------- Python
say "Python environment (.venv)"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python >= 3.10 needed"'
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import pandas, curl_cffi, matplotlib, mplsoccer; print('python packages ok, pandas', pandas.__version__)"
if [ "$PLAYWRIGHT" = 1 ]; then .venv/bin/python -m playwright install --with-deps chromium; fi

# ---------------------------------------------------------------- Node + Chrome for Testing
say "Node packages and Chrome for Testing $CHROME_VERSION"
command -v node >/dev/null || { echo "node not found (./setup.sh --system, or install Node >= 18)"; exit 1; }
node -e 'if (+process.versions.node.split(".")[0] < 18) { console.error("Node >= 18 needed"); process.exit(1) }'
(cd tools && npm ci --no-audit --no-fund)
CACHE="${PUPPETEER_CACHE_DIR:-$HOME/.cache/puppeteer}"
(cd tools && npx --yes @puppeteer/browsers install "chrome@$CHROME_VERSION" --path "$CACHE" >/dev/null)
node -e "console.log('chrome:', require('./tools/browser').chromePath())"

# ---------------------------------------------------------------- ffmpeg
say "ffmpeg"
if command -v ffmpeg >/dev/null || [ -x /opt/homebrew/bin/ffmpeg ]; then echo "ffmpeg ok"; else echo "ffmpeg missing: ./setup.sh --system (or install it) - needed for the video only"; fi

# ---------------------------------------------------------------- check
if [ "$CHECK" = 1 ]; then
  say "engine rules on France-England"
  .venv/bin/python tools/build_data.py data/France_vs_England/France_vs_England_qualifiers_expanded.csv >/dev/null
  node tools/check_engine.js --match France_vs_England
fi

say "done"
echo "make a match video:   .venv/bin/python -m pmd.make3d --fotmob <FotMob match id>"
echo "open the 3D page:     .venv/bin/python tools/serve.py   then  http://localhost:8000/fabric/index.html?match=<match>"

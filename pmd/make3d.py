"""One command from a FotMob match id to the 3D video.

    python -m pmd.make3d --fotmob 6106254
    python -m pmd.make3d --fotmob 4737562 --whoscored 1891177 --no-render

Steps (the run stops at the first failed check unless --force):
  1. WhoScored id: --whoscored, else looked up in data/fixtures/whoscored_fixtures.csv (column fotmob_match_id);
  2. pipeline (pmd.run): FotMob + WhoScored downloads (kept in output/<fotmob id>/raw and reused), exports;
     the exports are copied to data/<match>/;
  3. data checks: tools/validate_events.py;
  4. 3D data: tools/build_data.py -> fabric/data/<date>_<home>_vs_<away>.js (open fabric/index.html?match=<that name>);
  5. engine checks: node tools/check_engine.js --match <match>;
  6. video: node tools/render.js --match <match> --out out/frames_<match>, then ffmpeg -> out/<match>_3d.mp4.
Needs: this Python environment (requirements.txt), Node.js with puppeteer-core in tools/node_modules, Chrome for
Testing (see tools/render.js), ffmpeg.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import pandas as pd

from .config import MatchConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, 'data', 'fixtures', 'whoscored_fixtures.csv')


def step(title):
    print(f'\n=== {title}', flush=True)


def whoscored_id_for(fotmob_id):
    """WhoScored id of a FotMob match from the linked fixtures file (None when it is not there)."""
    if not os.path.exists(FIXTURES):
        return None
    fx = pd.read_csv(FIXTURES)
    hit = fx[pd.to_numeric(fx['fotmob_match_id'], errors='coerce') == int(fotmob_id)]
    return str(int(hit['whoscored_match_id'].iloc[0])) if len(hit) else None


def run_cmd(cmd, force, what):
    """Run a command from the project root; stop the whole run when it fails (unless force)."""
    print('$', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    code = subprocess.call(cmd, cwd=ROOT)
    if code != 0:
        msg = f'{what} failed (exit code {code})'
        if not force:
            sys.exit(msg + ' - fix the data or rerun with --force')
        print('WARNING:', msg, '(continuing: --force)')
    return code


def tool(name):
    """Path of an external program (node, ffmpeg), also looking in Homebrew's folder."""
    path = shutil.which(name) or next((p for p in (f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}') if os.path.exists(p)), None)
    if not path:
        sys.exit(f'{name} not found: install it or add it to PATH')
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fotmob', required=True, help='FotMob match id')
    ap.add_argument('--whoscored', help='WhoScored match id (default: from data/fixtures/whoscored_fixtures.csv)')
    ap.add_argument('--proxy', help='residential proxy for WhoScored, http://user:pass@host:port')
    ap.add_argument('--dashboard', action='store_true', help='also draw the dashboard PNG')
    ap.add_argument('--no-render', action='store_true', help='stop after the checks (no video)')
    ap.add_argument('--fps', default='30', help='video frames per second (default 30)')
    ap.add_argument('--force', action='store_true', help='go on when a check fails')
    a = ap.parse_args(argv)
    py = sys.executable

    step('1. WhoScored id')
    ws = a.whoscored or whoscored_id_for(a.fotmob)
    if not ws:
        sys.exit(f'FotMob {a.fotmob} is not in {os.path.relpath(FIXTURES, ROOT)}: give --whoscored <id>')
    print(f'FotMob {a.fotmob} -> WhoScored {ws}')

    step('2. pipeline (downloads + exports)')
    from .run import run
    work = os.path.join(ROOT, 'output', str(a.fotmob))
    paths = run(MatchConfig(str(a.fotmob), ws, out_dir=work, cache_dir=os.path.join(work, 'raw'), proxy=a.proxy, dashboard=a.dashboard))
    csv = next(p for p in paths if p.endswith('_qualifiers_expanded.csv'))
    match = os.path.basename(csv)[:-len('_qualifiers_expanded.csv')]
    from .slug import match_slug
    slug = match_slug(os.path.join(ROOT, 'data', match, os.path.basename(csv)))   # date + teams, as in tools/build_data.py
    data_dir = os.path.join(ROOT, 'data', match)
    os.makedirs(data_dir, exist_ok=True)
    for p in paths:
        shutil.copy2(p, data_dir)
    csv = os.path.join(data_dir, os.path.basename(csv))
    print(f'match {match!r}: exports copied to {os.path.relpath(data_dir, ROOT)}/')

    step('3. data checks')
    run_cmd([py, 'tools/validate_events.py', csv, '--momentum', os.path.join(data_dir, f'{match}_momentum.csv'),
             '--fotmob', os.path.join(work, 'raw', 'fotmob.json')], a.force, 'data checks')

    step('4. 3D data')
    run_cmd([py, 'tools/build_data.py', csv], False, 'build_data')

    step('5. engine checks')
    node = tool('node')
    run_cmd([node, 'tools/check_engine.js', '--match', slug], a.force, 'engine checks')
    if a.no_render:
        print(f'\ndone (no video): open fabric/index.html?match={slug} (python tools/serve.py)')
        return

    step('6. video')
    frames = os.path.join('out', f'frames_{slug}')
    for f in glob.glob(os.path.join(ROOT, frames, '*.jpg')):
        os.remove(f)
    run_cmd([node, 'tools/render.js', '--match', slug, '--out', frames, '--fps', a.fps], False, 'render')
    video = os.path.join('out', f'{slug}_3d.mp4')
    run_cmd([tool('ffmpeg'), '-v', 'error', '-y', '-framerate', a.fps, '-i', os.path.join(frames, 'f_%05d.jpg'),
             # standard-range yuv420p H.264 (the JPEG frames are full range): plays in QuickTime, browsers and phones
             '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2,scale=in_range=pc:out_range=tv,format=yuv420p', '-c:v', 'libx264', '-profile:v', 'high',
             '-crf', '18', '-preset', 'medium', '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
             '-movflags', '+faststart', '-tag:v', 'avc1', video], False, 'encode')
    print(f'\ndone: {video}  (3D page: fabric/index.html?match={slug})')


if __name__ == '__main__':
    main()

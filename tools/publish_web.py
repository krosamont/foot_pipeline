"""Publish matches to the website: the 3D page (fabric/), its fonts, logos and photos, the match list and the
pages to choose a season and a match (web/index.html, web/match.html).

    python tools/publish_web.py "data/matches/premier-league_2025-2026/1903117_Liverpool_vs_AFC Bournemouth" [...]
    python tools/publish_web.py --all            (every match of data/matches/)

For each match folder (as written by tools/run_missing.py): the 3D data fabric/data/<slug>.js is built when missing
(tools/build_data.py), then copied with the images it uses; matches.json (one entry per match, kept from earlier
publications, data/matches/matches_all.json) is rewritten with the latest season only (--all-seasons: every season).
Only what the pages need is copied: no CSV, no raw download.
Default target: ~/data-workers.com/projet/foot_3d (--out).
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from pmd.slug import match_slug  # noqa: E402

STATIC = ['fabric/index.html', 'fabric/camera.js', 'fabric/js', 'fabric/lib', 'assets/fonts', 'assets/howto']
PAGES = ['web/index.html', 'web/match.html', 'web/.htaccess']   # copied to the root of the site
MEDIA = re.compile(r'\.\./(assets/media/[^"\']+)')
ALL_LIST = os.path.join(ROOT, 'data', 'matches', 'matches_all.json')   # every match ever published, all seasons


def competition_name(name):
    """FotMob sometimes says 'UEFA Champions League' for 'Champions League': one tab per competition on the site."""
    return re.sub(r'^UEFA\s+', '', name)


def round_name(name):
    """'League Stage - Round 3' -> '3', like the matchdays of the other rounds; other names are kept."""
    m = re.fullmatch(r'(?:.*\bRound|Matchday)\s+(\d+)', name.strip())
    return m.group(1) if m else name


def copy(src, dst):
    """Copy a file or a folder (only files that changed)."""
    if os.path.isdir(src):
        for f in glob.glob(os.path.join(src, '**', '*'), recursive=True):
            if os.path.isfile(f):
                copy(f, os.path.join(dst, os.path.relpath(f, src)))
        return
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def entry(folder, out):
    """Build (if needed) and copy one match; returns its matches.json entry, or None when it cannot be published."""
    csvs = glob.glob(os.path.join(folder, '*_qualifiers_expanded.csv'))
    if not csvs:
        print(f'[skip] no export in {folder}')
        return None
    csv = csvs[0]
    slug = match_slug(csv)
    js = os.path.join(ROOT, 'fabric', 'data', slug + '.js')
    if not os.path.exists(js):
        code = subprocess.call([sys.executable, os.path.join(ROOT, 'tools', 'build_data.py'), csv], cwd=ROOT,
                               stdout=subprocess.DEVNULL)
        if code != 0 or not os.path.exists(js):
            print(f'[skip] build_data failed for {folder}')
            return None
    text = open(js, encoding='utf-8').read()
    copy(js, os.path.join(out, 'fabric', 'data', slug + '.js'))
    for rel in sorted(set(MEDIA.findall(text))):
        src = os.path.join(ROOT, rel)
        if os.path.exists(src):
            copy(src, os.path.join(out, rel))
    info = pd.read_csv(csv.replace('_qualifiers_expanded.csv', '_match_info.csv')).set_index('side')
    match = json.loads(text[text.index('{'):text.rindex('}') + 1])
    comp_season = os.path.basename(os.path.dirname(os.path.abspath(folder)))      # premier-league_2025-2026
    season = comp_season.rsplit('_', 1)[-1].replace('-', '/')
    score = lambda side: info.loc[side, 'score']
    logo = lambda side: (match[side].get('logo') or '').replace('../', '', 1) or None
    ws_id = os.path.basename(os.path.normpath(folder)).split('_', 1)[0]
    return {
        'slug': slug, 'match_id': int(ws_id) if ws_id.isdigit() else None, 'date': slug[:10], 'season': season,
        'competition': competition_name(str(info['leagueName'].iloc[0])),
        'round': None if pd.isna(info['leagueRoundName'].iloc[0]) else round_name(str(info['leagueRoundName'].iloc[0])),
        'home': str(info.loc['home', 'team_name']), 'away': str(info.loc['away', 'team_name']),
        'score': f"{int(score('home'))} - {int(score('away'))}" if not pd.isna(score('home')) else '-',
        'home_logo': logo('home'), 'away_logo': logo('away'),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folders', nargs='*', help='match folders (data/matches/<competition>_<season>/<match>)')
    ap.add_argument('--all', action='store_true', help='every match of data/matches/')
    ap.add_argument('--out', default=os.path.expanduser('~/data-workers.com/projet/foot_3d'))
    ap.add_argument('--all-seasons', action='store_true', help='list every season on the site, not only the latest')
    a = ap.parse_args(argv)
    folders = sorted(glob.glob(os.path.join(ROOT, 'data', 'matches', '*', '*', ''))) if a.all else a.folders
    if not folders:
        ap.error('give match folders or --all')

    for rel in STATIC:
        copy(os.path.join(ROOT, rel), os.path.join(a.out, rel))
    for page in PAGES:
        copy(os.path.join(ROOT, page), os.path.join(a.out, os.path.basename(page)))

    # every published match is remembered in ALL_LIST; the site's matches.json only lists the latest season
    # (the 3D pages of earlier seasons stay on the server)
    list_path = os.path.join(a.out, 'matches.json')
    seed = ALL_LIST if os.path.exists(ALL_LIST) else list_path
    known = {m['slug']: m for m in json.load(open(seed))} if os.path.exists(seed) else {}
    added = 0
    for f in folders:
        e = entry(f, a.out)
        if e:
            known[e['slug']] = e
            added += 1
    every = sorted(known.values(), key=lambda m: (m['date'], m['slug']))
    latest = max((m['season'] for m in every), default=None)
    shown = every if a.all_seasons else [m for m in every if m['season'] == latest]
    write_json(ALL_LIST, every)
    write_json(list_path, shown)
    print(f'[web] {added} match(es) published, {len(shown)} in {list_path} '
          f'({"all seasons" if a.all_seasons else latest}; {len(every)} in {ALL_LIST})')


def write_json(path, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


if __name__ == '__main__':
    main()

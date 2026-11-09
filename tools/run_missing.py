"""Run the pipeline (pmd.run) on every played match not yet in data/matches/, one match at a time.

Pairs (WhoScored id, FotMob id) are read from data/fixtures/: whoscored_fixtures.csv, whoscored_schedule_*.csv and
whoscored_links_*.csv. `--link-lists` first builds whoscored_links_<season>.csv from WhoScored match lists (CSV with
competition, match_id, link columns), linked to the FotMob calendar of the season (pmd.fixtures).

Matches listed in data/fixtures/whoscored_in_old_parquet.csv (already in the old project) are left out (--exclude-ids),
and those of tools/fotmob_only_matches.csv (WhoScored has no events for them: loaded from FotMob alone).
Each match goes to data/matches/<competition>_<season>/<whoscored id>_<Home>_vs_<Away>/ (raw downloads in raw/), the
dashboard is skipped, and the match is published on the website right away (tools/publish_web.py, --no-publish to
skip). After the run (and once an hour during a long one) the four Parquet files go to Google Cloud
(tools/export_gcp.py --upload, --no-gcp). The check that every match played is everywhere (tools/check_matches.py, with
an e-mail when one is missing) has its own cron job; --check runs it here too. Matches are taken newest season first, the list being read again before
each match. A match already done is skipped, so the run can be stopped and started again. Between two
matches the script waits a random 5-35 s. Failures are appended to data/matches/failed.csv.

    python tools/run_missing.py --link-lists ~/data/foot/whoscored/data/*_2025_2026.csv --season 2025/2026
    python tools/run_missing.py [--seasons 2025/2026 2026/2027] [--limit 1] [--dry-run]   (default: 2020/2021 to 2026/2027)
"""
import argparse
import csv
import glob
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIXTURES = os.path.join(ROOT, 'data', 'fixtures')
MATCHES = os.path.join(ROOT, 'data', 'matches')

import warnings  # noqa: E402

import pandas as pd  # noqa: E402

warnings.filterwarnings('ignore', category=DeprecationWarning)   # numpy 'generic' timedelta notice from pandas, harmless

from pmd.fixtures import LEAGUES, league_fixtures  # noqa: E402
from pmd.whoscored_fixtures import _team_sim  # noqa: E402

SLUG_OF = {name: slug for slug, (_, name) in LEAGUES.items()}


# WhoScored short names that share too few letters with FotMob's name
SHORT_NAMES = {'wolves': 'wolverhampton wanderers', 'm gladbach': 'monchengladbach'}


def teams_from_link(link, names):
    """(home, away) as FotMob names, from the teams part of a WhoScored match link ('...-2025-2026-manchester-city-wolves'):
    the cut between the two teams is the one whose two halves are closest to two of the season's FotMob team `names`."""
    words = re.split(r'-\d{4}-\d{4}-', link.rstrip('/'))[-1].split('-')

    def best(part):
        part = SHORT_NAMES.get(part, part)
        return max(((_team_sim(part, n), n) for n in names), default=(0, None))

    cuts = [(best(' '.join(words[:i])), best(' '.join(words[i:]))) for i in range(1, len(words))]
    (sh, home), (sa, away) = max(cuts, key=lambda c: c[0][0] + c[1][0])
    return (home, away) if sh + sa >= 1.6 and home != away else (None, None)


def link_lists(paths, season):
    """WhoScored match lists of one season -> data/fixtures/whoscored_links_<season>.csv (with the FotMob ids).

    The lists' home_team / away_team columns are cut at the wrong hyphen for names of several words ('Manchester' /
    'City Arsenal'), so both teams are read again from the match link, against the FotMob calendar's team names,
    and the FotMob match is the one with exactly those two teams."""
    raw = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True).drop_duplicates('match_id')
    frames = []
    for comp in sorted(raw['competition'].unique()):
        slug, tag = SLUG_OF[comp], season.replace('/', '-')
        path = os.path.join(FIXTURES, f'{slug}_{tag}.csv')
        if os.path.exists(path):
            cal = pd.read_csv(path)
        else:
            cal = league_fixtures(slug, season, 0, 1000)
            cal.to_csv(path, index=False)
            print(f'[link] FotMob calendar {comp} {season}: {len(cal)} matches -> {path}')
        names = sorted(set(cal['home']) | set(cal['away']))
        r = raw[raw['competition'] == comp]
        teams = [teams_from_link(l, names) for l in r['link']]
        ws = pd.DataFrame({
            'whoscored_match_id': r['match_id'].astype(int).values, 'date': None,
            'competition': comp, 'competition_slug': slug, 'season': season,
            'home': [t[0] for t in teams], 'away': [t[1] for t in teams],
            'home_score': pd.array([None] * len(r), dtype='Int64'), 'away_score': pd.array([None] * len(r), dtype='Int64'),
            'played': False, 'match_url': r['link'].values,
        })
        # the teams are FotMob's own names now: the fixture (home, away) is unique in a league season
        key = cal.drop_duplicates(['home', 'away'], keep=False).set_index(['home', 'away'])
        hit = [key.loc[(h, w)] if (h, w) in key.index else None for h, w in zip(ws['home'], ws['away'])]
        ws['fotmob_match_id'] = pd.array([x['match_id'] if x is not None else None for x in hit], dtype='Int64')
        ws['fotmob_match_url'] = [x['match_url'] if x is not None else None for x in hit]
        ws['date'] = [pd.Timestamp(x['date_utc']).strftime('%Y-%m-%d') if x is not None else None for x in hit]
        ws['date_source'] = ['fotmob' if x is not None else None for x in hit]
        frames.append(ws[ws['home'].notna()])
        if ws['home'].isna().any():
            frames.append(ws[ws['home'].isna()])
            print(f"[link] {comp}: teams not recognised in {ws['home'].isna().sum()} links")
    out = pd.concat(frames, ignore_index=True)
    path = os.path.join(FIXTURES, f"whoscored_links_{season.replace('/', '-')}.csv")
    out.to_csv(path, index=False)
    print(out.groupby('competition')['fotmob_match_id'].agg(['size', 'count'])
          .rename(columns={'size': 'matches', 'count': 'with FotMob id'}).to_string())
    print(f'[link] -> {path}')


def kickoffs():
    """FotMob match id -> kick-off (UTC), from the FotMob calendars in data/fixtures/ (<slug>_<season>.csv)."""
    frames = []
    for slug in LEAGUES:
        for p in glob.glob(os.path.join(FIXTURES, f'{slug}_*.csv')):
            cal = pd.read_csv(p, usecols=['match_id', 'date_utc'])
            frames.append(cal)
    cal = pd.concat(frames, ignore_index=True).drop_duplicates('match_id', keep='last')
    return dict(zip(cal['match_id'].astype(int), pd.to_datetime(cal['date_utc'], utc=True, format='ISO8601')))


def todo(seasons, after_hours):
    """Matches of `seasons` with both ids that kicked off at least `after_hours` hours ago, in date order."""
    files = [os.path.join(FIXTURES, 'whoscored_fixtures.csv')] + sorted(glob.glob(os.path.join(FIXTURES, 'whoscored_schedule_*.csv'))) \
        + sorted(glob.glob(os.path.join(FIXTURES, 'whoscored_links_*.csv')))
    df = pd.concat([pd.read_csv(f) for f in files if os.path.exists(f)], ignore_index=True)
    df = df[df['season'].astype(str).isin(seasons) & df['fotmob_match_id'].notna()].drop_duplicates('whoscored_match_id')
    df['kickoff_utc'] = pd.to_datetime(df['fotmob_match_id'].astype(int).map(kickoffs()), utc=True)
    now = pd.Timestamp.now(tz='UTC')
    today = now.strftime('%Y-%m-%d')
    # kick-off known (FotMob calendar): wait `after_hours`; else the day must be over; no date at all: try it
    ready = df['kickoff_utc'].notna() & (df['kickoff_utc'] <= now - pd.Timedelta(hours=after_hours))
    ready |= df['kickoff_utc'].isna() & (df['date'].isna() | (df['date'].astype(str) < today))
    df = df[ready]
    # newest season first (the website fills up from the current season), in kick-off order inside a season
    df = df.assign(_season=df['season'].astype(str))
    return df.sort_values(['_season', 'kickoff_utc', 'whoscored_match_id'], ascending=[False, True, True], na_position='last') \
        .drop(columns='_season').reset_index(drop=True)


def failures(path):
    """WhoScored id -> number of failed attempts recorded in failed.csv."""
    if not os.path.exists(path):
        return {}
    return pd.read_csv(path)['whoscored_match_id'].value_counts().to_dict()


def out_dir(m):
    slug = m['competition_slug'] if isinstance(m.get('competition_slug'), str) and m['competition_slug'] in LEAGUES \
        else SLUG_OF.get(m['competition'], str(m['competition']).lower().replace(' ', '-'))
    name = f"{int(m['whoscored_match_id'])}_{m['home']}_vs_{m['away']}".replace('/', '-')
    return os.path.join(MATCHES, f"{slug}_{str(m['season']).replace('/', '-')}", name)


def publish(d):
    """Put the match on the website at once (tools/publish_web.py); a failure there does not stop the scraping."""
    code = subprocess.call([sys.executable, os.path.join(ROOT, 'tools', 'publish_web.py'), d], cwd=ROOT)
    if code:
        print(f'[web] publication failed (exit code {code}): {d}', flush=True)


def tool(name, *args):
    """Run another tool of tools/ (Google Cloud export, check); its failure does not stop this one."""
    code = subprocess.call([sys.executable, os.path.join(ROOT, 'tools', name), *args], cwd=ROOT)
    if code:
        print(f'[missing] {name} failed (exit code {code})', flush=True)


def gcp_behind():
    """True when the four files of data/gcp/ differ from what the last upload sent (or were never sent)."""
    import hashlib
    state_path = os.path.join(ROOT, 'data', 'gcp', 'uploaded.json')
    sent = json.load(open(state_path)) if os.path.exists(state_path) else {}
    for t in ('match_df', 'player_df', 'event_df', 'metrics_df'):
        p = os.path.join(ROOT, 'data', 'gcp', t + '.parquet')
        if not os.path.exists(p):
            return True
        h = hashlib.md5()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        if sent.get(t) != h.hexdigest():
            return True
    return False


def done(d):
    return bool(glob.glob(os.path.join(d, '*_qualifiers_expanded.csv')))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--link-lists', nargs='+', help='WhoScored match lists to link to FotMob (then exit)')
    ap.add_argument('--season', help='season of --link-lists, like 2025/2026')
    ap.add_argument('--seasons', nargs='+', default=[f'{y}/{y + 1}' for y in range(2020, 2027)])
    ap.add_argument('--exclude-ids', default=os.path.join(FIXTURES, 'whoscored_in_old_parquet.csv'),
                    help='CSV with a whoscored_match_id column: matches to leave out (default: those of the old project)')
    ap.add_argument('--limit', type=int, default=None, help='stop after this many matches')
    ap.add_argument('--min-wait', type=float, default=5)
    ap.add_argument('--max-wait', type=float, default=35)
    ap.add_argument('--after-hours', type=float, default=4, help='hours after the kick-off before a match is fetched')
    ap.add_argument('--max-tries', type=int, default=3, help='a match that failed this many times is left out')
    ap.add_argument('--no-publish', action='store_true', help='do not put the new matches on the website')
    ap.add_argument('--no-gcp', action='store_true', help='do not send the four Parquet files to Google Cloud (tools/export_gcp.py)')
    ap.add_argument('--check', action='store_true', help='also run tools/check_matches.py at the end (e-mail when a match is missing; '
                                                         'by default it has its own cron job)')
    ap.add_argument('--dry-run', action='store_true', help='only list what would run')
    a = ap.parse_args(argv)

    if a.link_lists:
        link_lists(a.link_lists, a.season)
        return 0

    from pmd.config import MatchConfig
    from pmd.run import run

    failed_path = os.path.join(MATCHES, 'failed.csv')
    skip = set(pd.read_csv(a.exclude_ids)['whoscored_match_id'].astype(int)) if a.exclude_ids and os.path.exists(a.exclude_ids) else set()
    fotmob_only = os.path.join(ROOT, 'tools', 'fotmob_only_matches.csv')
    if os.path.exists(fotmob_only):
        skip |= set(pd.read_csv(fotmob_only)['whoscored_match_id'].astype(int))

    def pending(attempted):
        """Matches still to fetch, newest season first; read again before every match, so that a match whose 4 hours
        are up during a long run goes ahead of the backlog of older seasons."""
        tries = failures(failed_path)
        matches = todo(a.seasons, a.after_hours)
        matches = matches[~matches['whoscored_match_id'].astype(int).isin(skip | attempted)]
        return [m for _, m in matches.iterrows() if not done(out_dir(m)) and tries.get(int(m['whoscored_match_id']), 0) < a.max_tries]

    attempted = set()
    left = pending(attempted)
    print(f'[missing] {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {len(left)} matches to run for {", ".join(a.seasons)}', flush=True)
    print(pd.DataFrame(left).groupby(['competition', 'season']).size().to_string() if left else '', flush=True)
    if a.dry_run:
        return 0
    os.makedirs(MATCHES, exist_ok=True)
    ok = ko = 0
    synced, last_sync = 0, time.monotonic()
    while left and not (a.limit and ok + ko >= a.limit):
        if ok + ko:
            wait = random.uniform(a.min_wait, a.max_wait)
            print(f'[wait] {wait:.1f} s', flush=True)
            time.sleep(wait)
        m = left[0]
        attempted.add(int(m['whoscored_match_id']))
        d = out_dir(m)
        print(f"\n[{ok + ko + 1}, {len(left) - 1} after this one] {m['competition']} {m['season']} {m['home']} - {m['away']} "
              f"(WhoScored {int(m['whoscored_match_id'])}, FotMob {int(m['fotmob_match_id'])})", flush=True)
        try:
            run(MatchConfig(str(int(m['fotmob_match_id'])), str(int(m['whoscored_match_id'])), d, os.path.join(d, 'raw'),
                            dashboard=False))
            ok += 1
            if not a.no_publish:
                publish(d)
        except Exception as e:
            ko += 1
            print(f'[failed] {e}', flush=True)
            traceback.print_exc()
            new = not os.path.exists(failed_path)
            with open(failed_path, 'a', newline='') as f:
                w = csv.writer(f)
                if new:
                    w.writerow(['when', 'whoscored_match_id', 'fotmob_match_id', 'competition', 'season', 'home', 'away', 'error'])
                w.writerow([datetime.now(timezone.utc).isoformat(timespec='seconds'), int(m['whoscored_match_id']),
                            int(m['fotmob_match_id']), m['competition'], m['season'], m['home'], m['away'], str(e)[:300]])
        if time.monotonic() - last_sync > 3600:   # long run: Google Cloud and the check once an hour
            if ok > synced and not a.no_gcp:
                tool('export_gcp.py', '--upload'); synced = ok
            # the check, only once no match of the current season is waiting in the queue (no false alarm while catching up)
            if a.check and all(str(x['season']) != max(a.seasons) for x in left[1:]):
                tool('check_matches.py')
            last_sync = time.monotonic()
        left = pending(attempted)
    if not a.no_gcp and (ok > synced or gcp_behind()):
        tool('export_gcp.py', '--upload')
    if a.check:
        tool('check_matches.py')
    print(f'\n[missing] done: {ok} written, {ko} failed (see {failed_path})')
    return 0


if __name__ == '__main__':
    sys.exit(main())

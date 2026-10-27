"""WhoScored match ids of whole seasons, fetched automatically (soccerdata), linked to the FotMob calendar.

Replaces the manual page exports (data/fixtures/sources/whoscored*.csv) for any past or current season:
soccerdata drives a real Chrome on WhoScored's fixtures pages and returns every match with its WhoScored id,
kick-off time, teams and score. The FotMob calendar of the same season is fetched too (pmd.fixtures) and both are
linked with the rules of pmd.whoscored_fixtures (same competition, same day +-1, same teams).

Command line:
    python -m pmd.whoscored_schedule --season 2025/2026                        (the five leagues)
    python -m pmd.whoscored_schedule --season 2025/2026 --leagues laliga ligue-1 --out data/fixtures
Output (in --out): whoscored_schedule_<season>.csv and fotmob_without_whoscored_<season>.csv.
About 3 minutes per league season (soccerdata caches the pages: re-runs are fast).
"""
import argparse
import os

import pandas as pd

from .fixtures import LEAGUES, league_fixtures
from .whoscored_fixtures import link_fotmob

# pmd slug -> soccerdata league id (the Champions League is not one of soccerdata's WhoScored defaults)
SOCCERDATA_LEAGUES = {
    "ligue-1": "FRA-Ligue 1", "laliga": "ESP-La Liga", "serie": "ITA-Serie A",
    "bundesliga": "GER-Bundesliga", "premier-league": "ENG-Premier League",
}


def _sd_season(season):
    """'2025/2026' -> '2526' (soccerdata's season code)."""
    a, b = season.split('/')
    return a[-2:] + b[-2:]


def whoscored_schedule(slug, season, headless=True):
    """One row per match of a league season, same columns as pmd.whoscored_fixtures (+ kickoff_utc)."""
    import soccerdata as sd
    ws = sd.WhoScored(leagues=SOCCERDATA_LEAGUES[slug], seasons=_sd_season(season), headless=headless)
    s = ws.read_schedule().reset_index()
    when = pd.to_datetime(s['date'], utc=True)
    played = s['home_score'].notna() & s['away_score'].notna()
    return pd.DataFrame({
        'whoscored_match_id': s['game_id'].astype(int),
        'date': when.dt.strftime('%Y-%m-%d'), 'kickoff_utc': when.dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'competition': LEAGUES[slug][1], 'competition_slug': slug, 'season': season,
        'home': s['home_team'], 'away': s['away_team'],
        'home_team_id': s['home_team_id'].astype('Int64'), 'away_team_id': s['away_team_id'].astype('Int64'),
        'home_score': s['home_score'].astype('Int64'), 'away_score': s['away_score'].astype('Int64'), 'played': played,
        'match_url': 'https://www.whoscored.com/matches/' + s['game_id'].astype(int).astype(str) + '/live',
    }).sort_values(['date', 'whoscored_match_id']).reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--season', required=True, help='season like 2025/2026')
    ap.add_argument('--leagues', nargs='*', default=list(SOCCERDATA_LEAGUES), choices=list(SOCCERDATA_LEAGUES))
    ap.add_argument('--out', default=os.path.join('data', 'fixtures'))
    ap.add_argument('--show-browser', action='store_true', help='run Chrome with a window (if WhoScored blocks headless)')
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    tag = a.season.replace('/', '-')
    ws_all, fm_all = [], []
    for slug in a.leagues:
        ws = whoscored_schedule(slug, a.season, headless=not a.show_browser)
        fm = league_fixtures(slug, a.season, 0, 1000)
        ws = link_fotmob(ws, fm)
        ws_all.append(ws); fm_all.append(fm)
        print(f"[schedule] {LEAGUES[slug][1]:<15} WhoScored {len(ws)} matches, FotMob {len(fm)}, linked {ws['fotmob_match_id'].notna().sum()}")
    ws_all, fm_all = pd.concat(ws_all, ignore_index=True), pd.concat(fm_all, ignore_index=True)
    out = os.path.join(a.out, f'whoscored_schedule_{tag}.csv'); ws_all.to_csv(out, index=False)
    linked = set(ws_all['fotmob_match_id'].dropna().astype(int).astype(str))
    missing = fm_all[~fm_all['match_id'].astype(str).isin(linked)]
    miss = os.path.join(a.out, f'fotmob_without_whoscored_{tag}.csv'); missing.to_csv(miss, index=False)
    print(f"[schedule] {len(ws_all)} matches -> {out}")
    print(f"[schedule] FotMob matches without a WhoScored id: {len(missing)} -> {miss}")


if __name__ == '__main__':
    main()

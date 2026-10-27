"""WhoScored match ids (fixtures page export) -> one clean row per match, linked to the FotMob calendar.

Input: the CSV saved from a WhoScored fixtures page with a web-scraper extension (one row per day: the day header,
then for each match of that day a block of columns: match link `Match-module_score__5Ghhj href*`, two score cells,
two team names + team links). The match link holds everything else:
    https://www.whoscored.com/matches/1994147/live/spain-laliga-2026-2027-rayo-vallecano-espanyol
                                     ^ match id     ^ competition ^ season  ^ teams
(`/show/` instead of `/live/` for matches not played yet, whose score cells are '-').

Output columns: whoscored_match_id, date (yyyy-mm-dd), competition, competition_slug, season, home, away,
home_team_id, away_team_id, home_score, away_score, played, match_url, and, when the FotMob calendar
(python -m pmd.fixtures) is given, fotmob_match_id / fotmob_match_url (same day +-1, same teams).

Command line:
    python -m pmd.whoscored_fixtures data/fixtures/sources/*.csv     (several exports are merged, duplicates removed)
Also writes fotmob_without_whoscored.csv: the FotMob matches no export covers yet.
"""
import argparse
import difflib
import os
import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd

MATCH_LINK = re.compile(r"/matches/(\d+)/(live|show)/([^/#?]+)")
TEAM_LINK = re.compile(r"/teams/(\d+)/")
SEASON = re.compile(r"^(.*?)-(\d{4})-(\d{4})-")
COMPETITIONS = {   # WhoScored slug -> name used in the FotMob calendar
    "spain-laliga": "LaLiga", "england-premier-league": "Premier League", "italy-serie-a": "Serie A",
    "germany-bundesliga": "Bundesliga", "france-ligue-1": "Ligue 1", "europe-champions-league": "Champions League",
}


def _day(header):
    """'Tuesday, Sep 15 2026' -> '2026-09-15'."""
    try:
        return datetime.strptime(str(header).split(', ', 1)[1], '%b %d %Y').strftime('%Y-%m-%d')
    except (IndexError, ValueError):
        return None


def _goals(cell):
    """Goals in a score cell ('2', '2.0' when the CSV made it a number, '1*' / '1 (4)' after extra time / penalties);
    None for a match not played ('-' or empty)."""
    m = re.match(r'\s*(\d+)', str(cell)) if cell is not None else None
    return int(m.group(1)) if m else None


def parse(csv_path):
    """One row per match (duplicates removed), sorted by date."""
    raw = pd.read_csv(csv_path)
    # exports of a day list have a day header column; exports of a single list of matches (one row each) have none
    day_col = next((c for c in raw.columns if c.startswith('Accordion-module_header')), None)
    rows = []
    for _, r in raw.iterrows():
        day = _day(r[day_col]) if day_col else None
        match = None
        for col, val in r.items():          # columns are in page order: a match link opens the block of its match
            if pd.isna(val):
                continue
            if col.startswith('Match-module_score__') and ' href' in col:
                m = MATCH_LINK.search(str(val))
                if not m:
                    continue
                match = {'whoscored_match_id': int(m.group(1)), 'date': day, 'slug': m.group(3), 'status': m.group(2),
                         'scores': [], 'teams': [], 'team_ids': []}
                rows.append(match)
            elif match is not None and col.startswith('Match-module_score__'):
                match['scores'].append(str(val).strip())
            elif match is not None and col.startswith('Match-module_teamNameText') and ' href' in col:
                t = TEAM_LINK.search(str(val)); match['team_ids'].append(int(t.group(1)) if t else None)
            elif match is not None and col.startswith('Match-module_teamNameText'):
                match['teams'].append(str(val).strip())
    out = []
    for m in rows:
        s = SEASON.match(m['slug'])
        comp_slug, season = (s.group(1), f"{s.group(2)}/{s.group(3)}") if s else (None, None)
        sc = [_goals(x) for x in (m['scores'] + [None, None])[:2]]
        played = all(x is not None for x in sc)
        out.append({
            'whoscored_match_id': m['whoscored_match_id'], 'date': m['date'],
            'competition': COMPETITIONS.get(comp_slug, comp_slug), 'competition_slug': comp_slug, 'season': season,
            'home': (m['teams'] + [None, None])[0], 'away': (m['teams'] + [None, None])[1],
            'home_team_id': (m['team_ids'] + [None, None])[0], 'away_team_id': (m['team_ids'] + [None, None])[1],
            'home_score': sc[0] if played else None, 'away_score': sc[1] if played else None, 'played': played,
            'match_url': f"https://www.whoscored.com/matches/{m['whoscored_match_id']}/live/{m['slug']}",
        })
    df = pd.DataFrame(out).drop_duplicates('whoscored_match_id').sort_values(['date', 'whoscored_match_id'], na_position='last').reset_index(drop=True)
    for c in ('home_team_id', 'away_team_id', 'home_score', 'away_score'):
        df[c] = df[c].astype('Int64')
    return df


# same club, different spelling between WhoScored and FotMob (applied after accents are removed, lower case)
ALIASES = {'copenhagen': 'kobenhavn', 'munich': 'munchen', 'crvena zvezda': 'red star', 'bodoe': 'bodo',
           'internazionale': 'inter', 'sporting cp': 'sporting', 'sporting lisbon': 'sporting', 'psv eindhoven': 'psv'}


def _norm(name):
    n = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().lower()
    for a, b in ALIASES.items():
        n = n.replace(a, b)
    for w in (' fc', 'fc ', ' cf', 'cf ', 'real club ', 'club ', 'deportivo ', ' de ', '.', '-'):
        n = n.replace(w, ' ')
    return ' '.join(n.split())


def _team_sim(a, b):
    """1 = same name, 0.95 = one name inside the other, else the string similarity (0..1)."""
    a, b = _norm(a), _norm(b)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a):
        return 0.95
    return difflib.SequenceMatcher(None, a, b).ratio()


def _same_team(a, b):
    return _team_sim(a, b) >= 0.8


def _best(candidates, home, away, used=(), score=None):
    """The candidate whose two teams match best, if it clearly beats the others (else None: ambiguous).
    FotMob matches already given to another WhoScored match (`used`) are left out; when the same fixture was played
    twice in the season (league phase + knock-out), the final `score` ('2 - 1') decides."""
    candidates = [f for f in candidates if str(f['match_id']) not in used]
    if score is not None:
        same = [f for f in candidates if str(f.get('score')) == score and _team_sim(home, f['home']) + _team_sim(away, f['away']) >= 1.6]
        if len(same) == 1 and sum(_team_sim(home, f['home']) + _team_sim(away, f['away']) >= 1.6 for f in candidates) > 1:
            return same[0]
    scored = sorted(((_team_sim(home, f['home']) + _team_sim(away, f['away']), k) for k, f in enumerate(candidates)), reverse=True)
    scored = [x for x in scored if x[0] >= 1.6]   # both teams similar enough
    if not scored or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.1):
        return None
    return candidates[scored[0][1]]


def link_fotmob(ws, fotmob_csv):
    """Add fotmob_match_id / fotmob_match_url: same competition, same day (+-1, UTC vs local time), same two teams.

    `fotmob_csv`: path of a FotMob calendar (python -m pmd.fixtures) or that table as a DataFrame.
    """
    fm = fotmob_csv.copy() if isinstance(fotmob_csv, pd.DataFrame) else pd.read_csv(fotmob_csv)
    fm['day'] = pd.to_datetime(fm['date_utc'], utc=True, format='ISO8601').dt.strftime('%Y-%m-%d')
    fm['season'] = fm['season'].astype(str)
    by_key = {}
    for _, f in fm.iterrows():
        by_key.setdefault((f['league'], f['season'], f['day']), []).append(f)
    by_comp = {}   # (competition, season) -> matches: the same fixture can come back another season
    for _, f in fm.iterrows():
        by_comp.setdefault((f['league'], f['season']), []).append(f)
    ids, urls, dates, src, shifted = [], [], [], [], []
    used = set()
    # dated matches first: an undated one (knock-out export) then cannot take a FotMob match already given to a dated one
    order = sorted(range(len(ws)), key=lambda k: pd.isna(ws.iloc[k]['date']))
    found_at = {}
    for k in order:
        w = ws.iloc[k]
        sc = f"{int(w['home_score'])} - {int(w['away_score'])}" if bool(w['played']) else None
        found = None
        if pd.isna(w['date']):
            # no day in the export: the two teams within the competition (unique while no knock-out tie repeats them)
            found = _best(by_comp.get((w['competition'], str(w['season'])), []), w['home'], w['away'], used, sc)
        else:
            d0 = datetime.strptime(w['date'], '%Y-%m-%d')
            for dd in (0, -1, 1):
                day = (d0 + timedelta(days=dd)).strftime('%Y-%m-%d')
                found = _best(by_key.get((w['competition'], str(w['season']), day), []), w['home'], w['away'], used, sc)
                if found is not None:
                    break
            if found is None:   # the export's day can be off (seen: 2 days): same two teams within the season
                found = _best(by_comp.get((w['competition'], str(w['season'])), []), w['home'], w['away'], used, sc)
                if found is not None:
                    shifted.append(w['whoscored_match_id'])
        if found is not None:
            used.add(str(found['match_id']))
        found_at[k] = found
    for k in range(len(ws)):
        w, found = ws.iloc[k], found_at[k]
        ids.append(found['match_id'] if found is not None else None)
        urls.append(found['match_url'] if found is not None else None)
        wrong_day = found is not None and w['whoscored_match_id'] in shifted
        missing_day = pd.isna(w['date']) or wrong_day
        dates.append(found['day'] if (missing_day and found is not None) else w['date'])
        src.append(('fotmob' if found is not None else None) if missing_day else 'whoscored')
    ws = ws.copy()
    ws['date'] = dates
    ws['date_source'] = src   # 'fotmob' when the WhoScored export had no day or a wrong one (FotMob UTC day)
    ws['fotmob_match_id'] = pd.array(ids, dtype='Int64')
    ws['fotmob_match_url'] = urls
    return ws


def complete_fotmob_calendar(ws, fm, out_dir):
    """Fetch (pmd.fixtures) the FotMob calendar of every competition / season of `ws` missing from `fm`."""
    from .fixtures import LEAGUES, league_fixtures
    slug_of = {name: slug for slug, (_, name) in LEAGUES.items()}
    have = set(zip(fm['league'], fm['season'].astype(str))) if len(fm) else set()
    frames = [fm]
    for comp, season in sorted(set(zip(ws['competition'], ws['season'].astype(str)))):
        if (comp, season) in have or comp not in slug_of:
            continue
        cal = league_fixtures(slug_of[comp], season, 0, 1000)
        cal.to_csv(os.path.join(out_dir, f"{slug_of[comp]}_{season.replace('/', '-')}.csv"), index=False)
        print(f"[whoscored] fetched the FotMob calendar {comp} {season}: {len(cal)} matches")
        frames.append(cal)
    out = pd.concat(frames, ignore_index=True)
    out['match_id'] = out['match_id'].astype(str)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('csv', nargs='+', help='CSV(s) saved from the WhoScored fixtures page (several exports are merged)')
    ap.add_argument('--fotmob', default=os.path.join('data', 'fixtures', 'fixtures_all.csv'),
                    help='FotMob calendar from `python -m pmd.fixtures` (linked when the file exists)')
    ap.add_argument('--out', default=os.path.join('data', 'fixtures', 'whoscored_fixtures.csv'))
    a = ap.parse_args(argv)
    df = pd.concat([parse(p) for p in a.csv]).drop_duplicates('whoscored_match_id').sort_values(['date', 'whoscored_match_id']).reset_index(drop=True)
    fm = pd.read_csv(a.fotmob) if a.fotmob and os.path.exists(a.fotmob) else pd.DataFrame(columns=['league', 'season'])
    fm = complete_fotmob_calendar(df, fm, os.path.dirname(a.out) or '.')
    df = link_fotmob(df, fm)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"[whoscored] {len(df)} matches ({df['played'].sum()} played) -> {a.out}")
    print(df.groupby(['competition', 'season']).size().to_string())
    if 'fotmob_match_id' in df:
        print(f"[whoscored] linked to FotMob: {df['fotmob_match_id'].notna().sum()} / {len(df)}")
        linked = set(df['fotmob_match_id'].dropna().astype(int).astype(str))
        seasons = set(zip(df['competition'], df['season'].astype(str)))   # only the competitions / seasons the exports cover
        fm_cov = fm[[(l, str(s)) in seasons for l, s in zip(fm['league'], fm['season'])]]
        missing = fm_cov[~fm_cov['match_id'].astype(str).isin(linked)]
        miss_path = os.path.join(os.path.dirname(a.out) or '.', 'fotmob_without_whoscored.csv')
        missing.to_csv(miss_path, index=False)
        print(f"[whoscored] FotMob matches without a WhoScored id: {len(missing)} / {len(fm_cov)} -> {miss_path}")


if __name__ == '__main__':
    main()

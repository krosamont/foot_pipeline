"""Are all the matches of each season there? Rules on the structure of each competition, checked on the agenda
(data/fixtures/) and on MotherDuck (raw + raw_legacy).

    python tools/check_fixtures.py                          (the past seasons, 2020-2021 to 2025-2026)
    python tools/check_fixtures.py --seasons 2025-2026 --competitions champions-league
    python tools/check_fixtures.py --missing-csv data/fixtures/missing.csv   (the missing matches, one per line)

Rules
  L1  league (round robin): N teams (20; Bundesliga 18; Ligue 1 18 from 2023-2024), N x (N - 1) matches, every
      ordered pair (home, away) exactly once: each team plays every other team once at home and once away.
  C1  Champions League, league phase (from 2024-2025): 36 teams, 144 matches, 8 per team (4 at home, 4 away).
      Group stage (before): 32 teams, 96 matches, 6 per team (3 at home, 3 away), each pair of a group twice.
  C2  knockout rounds: every tie has its two legs, the second with home and away reversed; only the final is one
      match. Matches: play-off 16 (from 2024-2025), round of 16 16, quarter-finals 8, semi-finals 4, final 1.
A pair is missing when the rule expects it and no source has it; a missing pair whose WhoScored id is in the agenda
can be downloaded right away (run_missing.py), otherwise its id must first be found (WhoScored schedule).
Exit code 1 when a rule is broken.
"""
import argparse
import glob
import os
import sys
from collections import Counter

import duckdb
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, 'data', 'fixtures')
PAST = ['2020-2021', '2021-2022', '2022-2023', '2023-2024', '2024-2025', '2025-2026']
LEAGUES = ['premier-league', 'laliga', 'serie-a', 'bundesliga', 'ligue-1']
UCL = 'champions-league'
SLUG = {'Premier League': 'premier-league', 'LaLiga': 'laliga', 'La Liga': 'laliga', 'Serie A': 'serie-a',
        'Bundesliga': 'bundesliga', 'Ligue 1': 'ligue-1', 'Champions League': UCL}
# knockout rounds by date (UEFA calendar): play-off in February, round of 16 until mid-March, ...
# short names of the old Parquet files that no other rule links to the full name
ALIASES = {'Sheff Utd': 'Sheffield United', 'WBA': 'West Bromwich Albion', 'Wolves': 'Wolverhampton Wanderers',
           'Man Utd': 'Manchester United', 'Man City': 'Manchester City', 'Brighton': 'Brighton & Hove Albion',
           'PSG': 'Paris Saint-Germain', 'Spurs': 'Tottenham Hotspur', 'Nottm Forest': 'Nottingham Forest'}
KO_ROUNDS_NEW = [('playoff', 16), ('round_of_16', 16), ('quarter_finals', 8), ('semi_finals', 4), ('final', 1)]
KO_ROUNDS_OLD = [('round_of_16', 16), ('quarter_finals', 8), ('semi_finals', 4), ('final', 1)]


def n_teams(comp, season):
    if comp == 'bundesliga' or (comp == 'ligue-1' and season >= '2023-2024'):
        return 18
    return 20


def token():
    if not os.environ.get('motherduck_token'):
        os.environ['motherduck_token'] = open(os.path.expanduser('~/.motherduck_token')).read().strip()


def agenda():
    """The WhoScored matches of data/fixtures/ (whoscored_fixtures, schedules, links), one row per WhoScored id."""
    files = [os.path.join(FIXTURES, 'whoscored_fixtures.csv')] + sorted(
        glob.glob(os.path.join(FIXTURES, 'whoscored_schedule_*.csv'))) + sorted(
        glob.glob(os.path.join(FIXTURES, 'whoscored_links_*.csv')))
    cols = ['whoscored_match_id', 'date', 'competition', 'season', 'home', 'away', 'home_team_id', 'away_team_id']
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in cols) for f in files if os.path.exists(f)])
    d['competition'] = d['competition'].map(SLUG).fillna(d['competition'])
    d['season'] = d['season'].str.replace('/', '-')
    d = d.rename(columns={'whoscored_match_id': 'match_id'})
    d['date'] = pd.to_datetime(d['date'])
    d = d.rename(columns={'home_team_id': 'home_id', 'away_team_id': 'away_id'})
    return d.drop_duplicates('match_id')[['match_id', 'competition', 'season', 'date', 'home', 'away', 'home_id', 'away_id']]


def motherduck():
    """The matches loaded in md:foot: raw (pipeline) and raw_legacy (old project), with WhoScored team names."""
    con = duckdb.connect(os.environ.get('FOOT_DB', os.path.expanduser('~/data/foot.duckdb')), read_only=True)
    raw = con.sql("""
        select match_id::bigint as match_id, competition, season, cast(fm_utcTime as date) as date,
               ws_home_name as home, ws_away_name as away,
               ws_home_teamId::bigint as home_id, ws_away_teamId::bigint as away_id
        from raw.match_status""").df()
    legacy = con.sql("""
        select m.match_id, m.competition, m.season, cast(m.date as date) as date,
               max(case when p.field = 'home' then p.team end) as home,
               max(case when p.field = 'away' then p.team end) as away,
               max(case when p.field = 'home' then p.teamId end) as home_id,
               max(case when p.field = 'away' then p.teamId end) as away_id
        from raw_legacy.match as m
        left join raw_legacy.player as p on p.match_id = m.match_id
        group by all""").df()
    raw['source'], legacy['source'] = 'raw', 'raw_legacy'
    d = pd.concat([raw, legacy]).drop_duplicates('match_id')   # raw first: it wins when both have a match
    d['date'] = pd.to_datetime(d['date'])
    return d


def one_name(known):
    """The sources name some clubs differently (PSG / Paris Saint-Germain, Man City / Manchester City, Verona /
    Hellas Verona): every club takes one name, by its WhoScored team id; a row without ids (links files) gets the id
    of its name from the other rows."""
    known = known.replace({'home': ALIASES, 'away': ALIASES})
    sides = pd.concat([known[['home', 'home_id']].set_axis(['name', 'id'], axis=1),
                       known[['away', 'away_id']].set_axis(['name', 'id'], axis=1)]).dropna()
    sides['id'] = sides['id'].astype('int64')
    id_of = sides.groupby('name')['id'].agg(lambda x: x.mode()[0])
    name_of = sides.groupby('id')['name'].agg(lambda x: x.mode()[0])
    k = known.replace({'home': ALIASES, 'away': ALIASES})
    for side in ('home', 'away'):
        ids = k[f'{side}_id'].fillna(k[side].map(id_of))
        k[side] = ids.map(name_of).fillna(k[side])
    return k


def same_names(k, loaded):
    """What the ids leave (links files without team ids, other spellings: Tottenham / Tottenham Hotspur): a name that
    MotherDuck does not use in this season takes the MotherDuck name that it contains or that contains it."""
    names = set(loaded.home) | set(loaded.away)
    alias = {}
    for t in (set(k.home) | set(k.away)) - names:
        hits = [n for n in names if n.lower() in t.lower() or t.lower() in n.lower()]
        if len(hits) == 1:
            alias[t] = hits[0]
    return k.replace({'home': alias, 'away': alias})


def check_league(m, comp, season):
    """L1: every ordered pair once. Returns (problems, missing pairs)."""
    n = n_teams(comp, season)
    teams = sorted(set(m.home) | set(m.away))
    problems = []
    if len(teams) != n:
        problems.append(f'L1 {len(teams)} teams, expected {n}')
    pairs = Counter(zip(m.home, m.away))
    problems += [f'L1 {h} - {a} {k} times' for (h, a), k in pairs.items() if k > 1]
    missing = [(h, a) for h in teams for a in teams if h != a and (h, a) not in pairs]
    return problems, missing


def ko_rounds(season):
    return KO_ROUNDS_NEW if season >= '2024-2025' else KO_ROUNDS_OLD


def check_ucl(m, season):
    """C1-C3. Returns (problems, missing pairs)."""
    problems, missing = [], []
    year = int(season[:4]) + 1
    league = m[m.date < pd.Timestamp(f'{year}-02-01')]
    ko = m[m.date >= pd.Timestamp(f'{year}-02-01')].sort_values('date')
    new = season >= '2024-2025'
    n, per_team, total = (36, 8, 144) if new else (32, 6, 96)
    teams = set(league.home) | set(league.away)
    if len(league) != total:
        problems.append(f'C1 {len(league)} league-phase matches, expected {total}')
    if teams and len(teams) != n:
        problems.append(f'C1 {len(teams)} teams in the league phase, expected {n}')
    for t in sorted(teams):
        h, a = (league.home == t).sum(), (league.away == t).sum()
        if (h, a) != (per_team // 2, per_team // 2):
            problems.append(f'C1 {t}: {h} at home, {a} away, expected {per_team // 2} + {per_team // 2}')
    if not new:   # group stage: each pair of a group home and away
        pairs = set(zip(league.home, league.away))
        missing += [(a, h) for h, a in pairs if (a, h) not in pairs]
    # C2: two legs per tie, one final
    expected = sum(k for _, k in ko_rounds(season))
    if len(ko) != expected:
        problems.append(f'C2 {len(ko)} knockout matches, expected {expected}')
    final = ko.iloc[-1:] if len(ko) and ko.date.iloc[-1] >= pd.Timestamp(f'{year}-05-20') else ko.iloc[:0]
    legs = Counter(frozenset(p) for p in zip(ko.home, ko.away))
    for _, r in ko.drop(final.index).iterrows():
        if legs[frozenset((r.home, r.away))] == 1:
            missing.append((r.away, r.home))   # the other leg, home and away reversed
    if not len(final):
        problems.append('C2 no final (a match from 20 May)')
    return problems, sorted(set(missing))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', nargs='+', default=PAST)
    ap.add_argument('--competitions', nargs='+', default=LEAGUES + [UCL])
    ap.add_argument('--missing-csv', help='write the missing matches there')
    a = ap.parse_args(argv)

    ag, md = agenda(), motherduck()
    known = one_name(pd.concat([md, ag.assign(source='agenda')]).drop_duplicates('match_id'))
    md = known[known.source != 'agenda']
    out, broken = [], False
    print(f'{"competition":17} {"season":10} {"expected":>8} {"agenda":>7} {"motherduck":>10} {"missing":>8}')
    for comp in a.competitions:
        for season in a.seasons:
            exp = (n_teams(comp, season) * (n_teams(comp, season) - 1) if comp != UCL
                   else (144 if season >= '2024-2025' else 96) + sum(k for _, k in ko_rounds(season)))
            k = known[(known.competition == comp) & (known.season == season)].dropna(subset=['home', 'away'])
            loaded = md[(md.competition == comp) & (md.season == season)].dropna(subset=['home', 'away'])
            g = ag[(ag.competition == comp) & (ag.season == season)]
            k = same_names(k, loaded)
            # rules on everything known (agenda + MotherDuck), then what of it is not in MotherDuck
            problems, missing = check_league(k, comp, season) if comp != UCL else check_ucl(k, season)
            not_loaded = k[~k.match_id.isin(loaded.match_id)]
            print(f'{comp:17} {season:10} {exp:8} {len(g):7} {len(loaded):10} {len(missing) + len(not_loaded):8}')
            for p in problems:
                print(f'    {p}')
            for h, a_ in missing:
                out.append(dict(competition=comp, season=season, home=h, away=a_, match_id=None, status='id unknown'))
            for r in not_loaded.itertuples():
                out.append(dict(competition=comp, season=season, home=r.home, away=r.away, match_id=r.match_id,
                                status='in the agenda, not in MotherDuck'))
            broken |= bool(problems or missing or len(not_loaded))
    if a.missing_csv:
        pd.DataFrame(out).to_csv(a.missing_csv, index=False)
        print(f'{len(out)} missing matches -> {a.missing_csv}')
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())

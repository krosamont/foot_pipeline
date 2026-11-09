"""One-off (2026-11-09): the kick-off of the old project's matches (its files only give the start of the week) from the
FotMob calendars (data/fixtures/<league>_<season>.csv): in the same competition and season, the FotMob match with the
closest team names between the day before the week start and 7 days after it. Writes /tmp/legacy_dates.csv, which
became foot_db seeds/legacy_match_kickoffs.csv (7,009 matches, all found, no FotMob match used twice).

    .venv/bin/python tools/oneoff/legacy_match_kickoffs.py      (on the server, reads the read copy of foot.duckdb)
"""
import sys, glob, duckdb, pandas as pd
sys.path.insert(0, '.')
from pmd.whoscored_fixtures import _team_sim
c = duckdb.connect('/home/mjzg4129/data/lecture/foot.duckdb', read_only=True)
leg = c.sql("select match_id, competition, season, match_date, home_team, away_team from b_intermediate.int_match where data_convention='ancienne'").df()
out = []
for (comp, season), g in leg.groupby(['competition', 'season']):
    f = f"data/fixtures/{ {'serie-a': 'serie'}.get(comp, comp) }_{season}.csv"
    try:
        cal = pd.read_csv(f)
    except FileNotFoundError:
        print('no calendar', f); continue
    cal['day'] = pd.to_datetime(cal.date_utc, utc=True)
    for r in g.itertuples():
        cand = cal.assign(s=[_team_sim(r.home_team, h) + _team_sim(r.away_team, a) for h, a in zip(cal.home, cal.away)])
        delta = (cand.day.dt.tz_convert(None).dt.normalize() - pd.Timestamp(r.match_date)).dt.days
        cand = cand[(delta >= -1) & (delta <= 7)]
        if cand.empty: out.append((r.match_id, None, None, 0, comp, season, r.home_team, r.away_team)); continue
        b = cand.sort_values('s', ascending=False).iloc[0]
        out.append((r.match_id, b.day.isoformat(), int(b.match_id), round(b.s, 2), comp, season, r.home_team, r.away_team))
df = pd.DataFrame(out, columns=['match_id', 'kickoff_utc', 'fotmob_match_id', 'sim', 'competition', 'season', 'home', 'away'])
print(len(df), df.kickoff_utc.notna().sum(), (df.sim < 1.4).sum())
print(df[df.sim < 1.4].head(30).to_string())
print(df.fotmob_match_id.dropna().duplicated().sum(), 'fotmob ids used twice')
df.to_csv('/tmp/legacy_dates.csv', index=False)

"""One-off (2026-11-09): the league matches the old project missed whose WhoScored id was unknown (gaps in the id
sequence of the season) -> the usual pipeline (pmd.run: WhoScored + FotMob, raw/ JSON and CSV), from the Mac.

How the 95 missing league matches were found (missing_league_matches_20261109.csv): in each league and season, every
team must host every other once; the (home, away) pairs absent from int_match, then their FotMob match in the FotMob
calendar (data/fixtures/<league>_<season>.csv) by the closest team names (pmd.whoscored_fixtures._team_sim).
25 had a WhoScored id, but WhoScored has no events for them (matchCentreData null): tools/fotmob_only_matches.csv,
loaded from FotMob alone by tools/load_raw.py. The other 70 had none: WhoScored gives the matches of a season
consecutive ids, so the missing ones are the gaps between the ids int_match has (Bundesliga 2021-2022: 49 gaps and the
ids just after; Premier League 2021-2022: 8; 2022-2023: 7). Each gap is fetched, its teams give its FotMob id; all 70
were found (Bundesliga 12 March to 24 April 2022, the old project's hole).

    python tools/oneoff/whoscored_id_gaps.py <out folder> tools/oneoff/missing_league_matches_20261109.csv
    then rsync <out folder>/ to data/matches/ on the server and tools/load_raw.py --seasons 2021-2022 2022-2023
Each WhoScored page is fetched once (saved as raw/whoscored.json, then reused by pmd.run); its FotMob id is the one of
missing_fotmob.csv whose teams are the closest. Waits 5-35 s between two matches, like tools/run_missing.py."""
import json, os, random, sys, time, traceback
import pandas as pd
sys.path.insert(0, os.getcwd())
from pmd import fetch
from pmd.run import run
from pmd.config import MatchConfig
from pmd.whoscored_fixtures import _team_sim

OUT = sys.argv[1]
miss = pd.read_csv(sys.argv[2])
miss = miss[miss.whoscored_id.isna()]
gaps = {('bundesliga', '2021-2022'): [1557517, 1557519, 1557521, 1557523, 1557525, 1557527, 1557529, 1557531, 1557533,
        1557535, 1557537, 1557539, 1557541, 1557543, 1557545, 1557547, 1557549, 1557551, 1557553, 1557555, 1557557,
        1557559, 1557561, 1557563, 1557565, 1557567, 1557569, 1557572, 1557582, 1557584, 1557586, 1557588, 1557590,
        1557592, 1557594, 1557596, 1557598, 1557600, 1557602, 1557604, 1557606, 1557608, 1557610, 1557612, 1557614,
        1557616, 1557618, 1557620, 1557622] + list(range(1557624, 1557632)),
        ('premier-league', '2021-2022'): [1549625, 1549643, 1549654, 1549678, 1549886, 1549888, 1549889, 1549892],
        ('premier-league', '2022-2023'): [1640765, 1640781, 1640893, 1640903, 1640935, 1640997, 1641008]}
done_fm = set()
log = open(os.path.join(OUT, 'ws_gaps.csv'), 'a')
first = True
for (comp, season), ids in gaps.items():
    left = miss[(miss.competition == comp) & (miss.season == season)]
    for ws in ids:
        if len(left[~left.fotmob_id.isin(done_fm)]) == 0:
            break
        if not first:
            time.sleep(random.uniform(5, 35))
        first = False
        try:
            data = fetch.fetch_whoscored(ws)
            if not isinstance(data, dict) or 'events' not in data:
                print(ws, 'no data', flush=True); log.write(f'{ws},,no data\n'); continue
            h, a = data['home']['name'], data['away']['name']
            cand = left[~left.fotmob_id.isin(done_fm)].copy()
            cand['s'] = [_team_sim(h, x) + _team_sim(a, y) for x, y in zip(cand.fotmob_home, cand.fotmob_away)]
            best = cand.sort_values('s', ascending=False).iloc[0]
            if best.s < 1.3:
                print(ws, h, a, 'not a missing match', round(best.s, 2), flush=True); log.write(f'{ws},,not missing {h} - {a}\n'); continue
            d = os.path.join(OUT, f'{comp}_{season}', f'{ws}_{h}_vs_{a}'.replace('/', '-'))
            os.makedirs(os.path.join(d, 'raw'), exist_ok=True)
            json.dump(data, open(os.path.join(d, 'raw', 'whoscored.json'), 'w'))
            run(MatchConfig(str(int(best.fotmob_id)), str(ws), d, os.path.join(d, 'raw'), dashboard=False))
            done_fm.add(best.fotmob_id)
            print(ws, h, a, '-> FotMob', int(best.fotmob_id), 'ok', flush=True); log.write(f'{ws},{int(best.fotmob_id)},ok {h} - {a}\n')
        except Exception as e:
            traceback.print_exc(); print(ws, 'failed', e, flush=True); log.write(f'{ws},,failed {e!r}\n')
        log.flush()

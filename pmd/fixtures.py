"""Match lists (URL, date, teams, score) of whole competitions from FotMob, round by round.

One FotMob API call per competition returns every match of the season with its round; the rows are kept for the
rounds asked (0..40 by default; rounds that are not numbers, e.g. Champions League knock-out stages, are always kept).

Command line:
    python -m pmd.fixtures                               (the six default competitions, current season)
    python -m pmd.fixtures --leagues ligue-1 laliga --season 2025/2026 --rounds 0 40 --out data/fixtures
Output: one CSV per competition (<slug>_<season>.csv) + fixtures_all.csv in --out.
"""
import argparse
import os
import time

import pandas as pd
import requests

from .config import HEADERS

FOTMOB_LEAGUE_API = "https://www.fotmob.com/api/data/leagues?id={}"
FOTMOB_SITE = "https://www.fotmob.com"

# slug -> (FotMob league id, name); the pages are https://www.fotmob.com/leagues/<id>/fixtures/<slug>?group=by-round
LEAGUES = {
    "ligue-1": (53, "Ligue 1"),
    "laliga": (87, "LaLiga"),
    "serie": (55, "Serie A"),
    "bundesliga": (54, "Bundesliga"),
    "premier-league": (47, "Premier League"),
    "champions-league": (42, "Champions League"),
}


def fetch_league(league_id, season=None, retries=3):
    """FotMob league JSON (fixtures of the whole season); `season` like '2025/2026' (default: current season)."""
    url = FOTMOB_LEAGUE_API.format(league_id)
    params = {"season": season} if season else None
    for k in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if k == retries - 1:
                raise
            print(f"[fixtures] retry {league_id}: {e}")
            time.sleep(2 * (k + 1))


def league_fixtures(slug, season=None, round_min=0, round_max=40):
    """One row per match: competition, season, round, match id / URL, UTC date, teams, status, score."""
    league_id, name = LEAGUES[slug]
    data = fetch_league(league_id, season)
    season_name = (data.get("details") or {}).get("selectedSeason") or season
    rows = []
    for m in (data.get("fixtures") or {}).get("allMatches") or []:
        rnd = m.get("round")
        rnd_num = int(rnd) if str(rnd).isdigit() else None
        if rnd_num is not None and not (round_min <= rnd_num <= round_max):
            continue
        st = m.get("status") or {}
        home, away = m.get("home") or {}, m.get("away") or {}
        rows.append({
            "league": name, "league_id": league_id, "season": season_name,
            "round": rnd_num if rnd_num is not None else rnd, "round_name": m.get("roundName"),
            "match_id": m.get("id"), "match_url": FOTMOB_SITE + m["pageUrl"] if m.get("pageUrl") else None,
            "date_utc": st.get("utcTime"),
            "home": home.get("name"), "home_id": home.get("id"), "away": away.get("name"), "away_id": away.get("id"),
            "started": st.get("started"), "finished": st.get("finished"), "cancelled": st.get("cancelled"),
            "score": st.get("scoreStr"),
        })
    df = pd.DataFrame(rows)
    if len(df):
        df["date_utc"] = pd.to_datetime(df["date_utc"], utc=True, format="ISO8601")   # FotMob mixes "...:00Z" and "...:00.000Z"
        df = df.sort_values(["date_utc", "match_id"]).reset_index(drop=True)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", nargs="*", default=list(LEAGUES), choices=list(LEAGUES), help="competitions (default: all six)")
    ap.add_argument("--season", default=None, help="season like 2025/2026 (default: the current one)")
    ap.add_argument("--rounds", nargs=2, type=int, default=[0, 40], metavar=("MIN", "MAX"), help="rounds kept (default 0 40)")
    ap.add_argument("--out", default=os.path.join("data", "fixtures"), help="output folder")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    frames = []
    for slug in a.leagues:
        df = league_fixtures(slug, a.season, *a.rounds)
        season = str(df["season"].iloc[0]).replace("/", "-") if len(df) else (a.season or "current").replace("/", "-")
        path = os.path.join(a.out, f"{slug}_{season}.csv")
        df.to_csv(path, index=False)
        n_rounds = df["round"].nunique() if len(df) else 0
        print(f"[fixtures] {LEAGUES[slug][1]:<17} {len(df):4d} matches, {n_rounds:2d} rounds -> {path}")
        frames.append(df)
    allp = os.path.join(a.out, "fixtures_all.csv")
    pd.concat(frames, ignore_index=True).to_csv(allp, index=False)
    print(f"[fixtures] all competitions -> {allp}")


if __name__ == "__main__":
    main()

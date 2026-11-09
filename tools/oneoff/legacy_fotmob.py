"""One-off (2026-11-09): the FotMob JSON of the old project's matches (seasons 2020-2021 to 2024-2025, WhoScored events
from the old Parquet files, no FotMob data), for their xG / xGOT, line-ups and stats. The FotMob id of each match is
the one found for foot_db's seed legacy_match_kickoffs (tools/oneoff/legacy_match_kickoffs.csv: 7,009 matches).

Each match -> data/legacy_fotmob/<competition>_<season>/<WhoScored id>/fotmob.json (kept apart from data/matches/,
whose folders tools/load_raw.py and tools/run_missing.py read). A match already downloaded is skipped: the run can
be stopped and started again. Polite: one request at a time, 4-10 s (random) between two; HTTP 403 / 429 / 5xx:
wait 2, 6 then 18 minutes, then stop. Log on stdout, failures in data/legacy_fotmob/failed.csv.

    .venv/bin/python -u tools/oneoff/legacy_fotmob.py [--limit 10]     (on the server, from ~/data/foot_3d)
"""
import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pmd.config import FOTMOB_URL, HEADERS  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'legacy_fotmob')
LIST = os.path.join(ROOT, 'tools', 'oneoff', 'legacy_match_kickoffs.csv')
BACKOFF = (120, 360, 1080)


def get(fotmob_id):
    for pause in (*BACKOFF, None):
        r = requests.get(FOTMOB_URL.format(fotmob_id), headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code not in (403, 429) and r.status_code < 500:
            raise RuntimeError(f'HTTP {r.status_code}')
        if pause is None:
            raise SystemExit(f'FotMob keeps refusing (HTTP {r.status_code}): stopped; run again later')
        print(f'HTTP {r.status_code}: pause {pause // 60} min', flush=True)
        time.sleep(pause)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int)
    a = ap.parse_args(argv)
    rows = list(csv.DictReader(open(LIST)))
    todo = [r for r in rows if not os.path.exists(os.path.join(OUT, f"{r['competition']}_{r['season']}", r['match_id'], 'fotmob.json'))]
    print(f'{datetime.now():%F %T} {len(rows)} matches, {len(todo)} to download', flush=True)
    done = 0
    for r in todo[:a.limit]:
        folder = os.path.join(OUT, f"{r['competition']}_{r['season']}", r['match_id'])
        try:
            data = get(int(float(r['fotmob_match_id'])))
            os.makedirs(folder, exist_ok=True)
            tmp = os.path.join(folder, 'fotmob.json.part')
            json.dump(data, open(tmp, 'w'))
            os.replace(tmp, os.path.join(folder, 'fotmob.json'))
            done += 1
        except Exception as e:   # noqa: BLE001  (one match must not stop the others; listed in failed.csv)
            os.makedirs(OUT, exist_ok=True)
            with open(os.path.join(OUT, 'failed.csv'), 'a', newline='') as f:
                csv.writer(f).writerow([datetime.now().isoformat(timespec='seconds'), r['match_id'], r['fotmob_match_id'], repr(e)])
            print(f"{r['match_id']} failed: {e!r}", flush=True)
        if done % 50 == 0:
            print(f'{datetime.now():%F %T} {done} downloaded', flush=True)
        time.sleep(random.uniform(4, 10))
    print(f'{datetime.now():%F %T} done: {done} downloaded', flush=True)


if __name__ == '__main__':
    main()

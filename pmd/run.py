"""Run the whole pipeline for one match.

Command line:
    python -m pmd.run --fotmob 4653857 --whoscored 2007643 [--out output] [--cache cache] [--proxy URL] [--no-dashboard]
From Python / a notebook:
    from pmd.run import run
    from pmd.config import MatchConfig
    paths = run(MatchConfig(fotmob_match_id="4653857", whoscored_match_id="2007643"))
"""
import argparse
import json
import os
import sys

from .config import MatchConfig


def _cached(cache_dir, name, fetch):
    """Raw download `name` from `cache_dir` when present, else fetch it (and save it there when a cache is set)."""
    path = os.path.join(cache_dir, name) if cache_dir else None
    if path and os.path.exists(path):
        with open(path) as f:
            print(f"[cache] {name}")
            return json.load(f)
    value = fetch()
    if path and value is not None:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(value, f)
    return value


def run(cfg: MatchConfig):
    """Fetch, process, export and draw one match; returns the list of files written."""
    import matplotlib
    if 'ipykernel' not in sys.modules:
        matplotlib.use('Agg')                     # no screen needed outside notebooks
    import pandas as pd
    from . import fetch, events, export

    pd.set_option('display.max_columns', None)
    os.makedirs(cfg.out_dir, exist_ok=True)
    fotmob = _cached(cfg.cache_dir, 'fotmob.json', lambda: fetch.fetch_fotmob(cfg.fotmob_match_id))
    whoscored = _cached(cfg.cache_dir, 'whoscored.json', lambda: fetch.fetch_whoscored(cfg.whoscored_match_id, cfg.proxy))
    if not isinstance(whoscored, dict) or 'events' not in whoscored:
        raise RuntimeError('WhoScored match centre data could not be fetched (see the messages above)')
    if cfg.cache_dir:
        from . import brut_csv
        brut_csv.convert(cfg.cache_dir)   # the raw JSON as flat CSV files (raw/csv/), loaded as they are into z_raw

    ns = events.build_events(whoscored, fotmob, cfg.out_dir)
    df_export, momentum_df, match_info_df = export.build_exports(ns['df'], fotmob, ns['hteamName'], ns['ateamName'])
    paths = export.write_exports(cfg.out_dir, ns['file_header'], df_export, momentum_df, match_info_df, fotmob)
    if cfg.dashboard:
        from . import dashboard
        paths.append(dashboard.render(ns, cfg.out_dir))
    for p in paths:
        print('[written]', p)
    return paths


def download(paths):
    """On Google Colab, send the files to the browser (no-op elsewhere)."""
    try:
        from google.colab import files
    except ImportError:
        return
    for p in paths:
        files.download(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fotmob', required=True, help='FotMob match id (fotmob.com/match/<id>)')
    ap.add_argument('--whoscored', required=True, help='WhoScored match id (whoscored.com/matches/<id>/live)')
    ap.add_argument('--out', default='output', help='output folder (default: output)')
    ap.add_argument('--cache', default=None, help='folder where the raw downloads are saved / reused')
    ap.add_argument('--proxy', default=None, help='residential proxy for WhoScored, http://user:pass@host:port')
    ap.add_argument('--no-dashboard', action='store_true', help='skip the dashboard PNG')
    ap.add_argument('--download', action='store_true', help='on Colab, download the files to the browser')
    a = ap.parse_args(argv)
    paths = run(MatchConfig(a.fotmob, a.whoscored, a.out, a.cache, a.proxy, not a.no_dashboard))
    if a.download:
        download(paths)
    return paths


if __name__ == '__main__':
    main()

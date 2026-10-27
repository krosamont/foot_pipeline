"""Post-match dashboard of one match: WhoScored + FotMob -> enriched CSV exports + 18-panel dashboard PNG.

This file is only the entry point; the code lives in the `pmd/` package:
    config.py    match ids, URLs, HTTP headers          fetch.py     FotMob + WhoScored downloads
    events.py    event table (metres, players, xG)      export.py    CSV / JSON exports
    dashboard.py the 18-panel figure                    run.py       chains everything

Run it:
    python postmatchdashboard_whoscored_v2.py                     (uses the ids below)
    python -m pmd.run --fotmob 4653857 --whoscored 2007643 --out output --cache output/raw
On Colab: notebooks/run_on_colab.ipynb (or upload dist/pmd_colab.zip, `pip install -r requirements.txt`, run this file).
The original notebook script, unchanged, is in legacy/postmatchdashboard_whoscored_v2_legacy.py.
"""
from pmd.config import MatchConfig
from pmd.run import download, run

FOTMOB_MATCH_ID = "4653857"      # fotmob.com/match/<id>
WHOSCORED_MATCH_ID = "2007643"   # whoscored.com/matches/<id>/live
OUT_DIR = "output"
CACHE_DIR = "output/raw"         # raw downloads kept here: re-runs work offline
PROXY = None                     # optional residential proxy for WhoScored: "http://user:pass@host:port"

if __name__ == "__main__":
    paths = run(MatchConfig(FOTMOB_MATCH_ID, WHOSCORED_MATCH_ID, OUT_DIR, CACHE_DIR, PROXY))
    download(paths)              # on Colab: sends the files to the browser (does nothing elsewhere)

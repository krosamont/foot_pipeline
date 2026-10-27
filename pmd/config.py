"""Settings shared by the whole pipeline: source URLs, HTTP headers and the match to process."""
import os
from dataclasses import dataclass
from typing import Optional

# HTTPS certificates: some Python builds (python.org on macOS, slim containers) have no CA bundle of their own;
# use certifi's unless the environment already sets one
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

FOTMOB_URL = "https://www.fotmob.com/api/data/matchDetails?matchId={}"
WHOSCORED_URL = "https://www.whoscored.com/matches/{}/live/"
# xT grid of the dashboard (McKay Johns), different from the export's AKapich grid (see export.py)
XT_GRID_DASHBOARD_URL = "https://raw.githubusercontent.com/mckayjohns/youtube-videos/main/data/xT_Grid.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class MatchConfig:
    """What to process and where to write it."""
    fotmob_match_id: str                 # e.g. "4653857"  (fotmob.com/match/<id>)
    whoscored_match_id: str              # e.g. "2007643"  (whoscored.com/matches/<id>/live)
    out_dir: str = "output"              # every file of the run goes here
    cache_dir: Optional[str] = None      # raw downloads are saved / reused here (offline re-runs, tests)
    proxy: Optional[str] = None          # optional residential proxy for WhoScored: "http://user:pass@host:port"
    dashboard: bool = True               # draw the 18-panel dashboard PNG

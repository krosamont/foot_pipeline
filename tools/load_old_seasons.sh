#!/bin/sh
# One-off (2026-10-28): the matches found missing by tools/check_fixtures.py that have a WhoScored id:
# Premier League 2020-2021 (data/fixtures/whoscored_links_premier-league_2020-2021.csv, the matches not in the old
# Parquet files), the 2025-2026 matches stopped after 3 failures (Bodoe/Glimt, Nantes - Toulouse; bugs fixed since),
# then into the MotherDuck sources (raw, foot_3d conventions, apart from raw_legacy) and a dbt build of foot_db.
HERE=/home/mjzg4129/data/foot_3d
LOG=$HERE/data/matches/old_seasons.log
cd "$HERE" || exit 1
flock -w 7200 data/matches/.run.lock sh -c "
  echo === \$(date -u +%FT%T) download
  .venv/bin/python -u tools/run_missing.py --seasons 2020/2021 --max-tries 3 --no-publish --no-gcp
  .venv/bin/python -u tools/run_missing.py --seasons 2025/2026 --max-tries 6 --no-gcp
  echo === \$(date -u +%FT%T) load raw
  .venv/bin/python -u tools/load_raw.py --seasons 2020-2021 2021-2022 2022-2023 2023-2024 2025-2026
  echo === \$(date -u +%FT%T) dbt build
  cd /home/mjzg4129/data/foot_db && git pull -q --ff-only && DBT=$HERE/.venv/bin/dbt scripts/dbt_build.sh
  echo === \$(date -u +%FT%T) done
" >> "$LOG" 2>&1

#!/bin/sh
# One-off (2026-10-28): the matches of 2021-2022 to 2024-2025 that failed 3 times (WhoScored match centre data not
# fetched, mostly on 2026-10-19/20), with up to 6 tries; then into the MotherDuck sources (raw) and a dbt build.
HERE=/home/mjzg4129/data/foot_3d
LOG=$HERE/data/matches/retry_failed.log
cd "$HERE" || exit 1
flock -w 7200 data/matches/.run.lock sh -c "
  echo === \$(date -u +%FT%T) download
  .venv/bin/python -u tools/run_missing.py --seasons 2021/2022 2022/2023 2023/2024 --max-tries 6 --no-publish --no-gcp
  .venv/bin/python -u tools/run_missing.py --seasons 2024/2025 --exclude-ids  --max-tries 6 --no-publish --no-gcp
  echo === \$(date -u +%FT%T) load raw
  .venv/bin/python -u tools/to_bronze.py --seasons 2021-2022 2022-2023 2023-2024 2024-2025
  echo === \$(date -u +%FT%T) dbt build
  cd /home/mjzg4129/data/foot_db && git pull -q --ff-only && DBT=$HERE/.venv/bin/dbt scripts/dbt_build.sh
  echo === \$(date -u +%FT%T) done
" >> "$LOG" 2>&1

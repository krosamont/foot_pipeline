#!/bin/sh
# Every 15 minutes (cron, under the shared lock data/matches/.run.lock): load the new matches into the sources of
# the server database (~/data/foot.duckdb, schema raw), then, only when matches were loaded, rebuild bronze, silver and gold with the dbt
# project foot_db (clone ~/data/foot_db, updated first) and run its tests.
#   loader:  tools/to_bronze.py   -> data/matches/bronze.log  (exit 0: matches loaded, 3: nothing new)
#   dbt:     foot_db scripts/dbt_build.sh -> data/matches/dbt.log
HERE=/home/mjzg4129/data/foot_3d
DB=/home/mjzg4129/data/foot_db
LOGS=$HERE/data/matches
cd "$HERE" || exit 1
.venv/bin/python -u tools/to_bronze.py >> "$LOGS/bronze.log" 2>&1
rc=$?
[ "$rc" -eq 3 ] && exit 0          # nothing new: silver and gold are up to date
[ "$rc" -ne 0 ] && exit "$rc"      # the loader failed: see bronze.log
{
    echo "=== $(date -u '+%Y-%m-%d %H:%M UTC') dbt build after a load"
    cd "$DB" && git pull -q --ff-only && git log --oneline -1
    DBT="$HERE/.venv/bin/dbt" "$DB/scripts/dbt_build.sh"
} >> "$LOGS/dbt.log" 2>&1

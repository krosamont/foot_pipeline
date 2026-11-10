#!/bin/bash
# Off-server copy of the football database (launchd on the Mac, every day at 09:00; a run missed while the Mac sleeps
# runs when it wakes): the latest nightly export of the server (~/data/sauvegardes/foot-<date>, pipeline nuit, task
# sauvegarde: EXPORT DATABASE in Parquet), its raw data only (z_raw, z_technique, schema.sql, load.sql: about 700 MB;
# a_staging, b_intermediate and c_marts are rebuilt from them by dbt), into $FOOT_BACKUP_DIR (default
# ~/Documents/dataScience/sport/football/sauvegardes_foot/foot-<date>), the 2 latest kept. Then a restore test
# (tools/test_restauration.py): every raw table imported into a temporary DuckDB file, its rows counted against the
# Parquet file. Log: $FOOT_BACKUP_DIR/sauvegarde.log; exit code 1 (and the reason in the log) when it fails.
#   tools/sauvegarde_mac.sh                  install: tools/launchd/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
SRV=${FOOT_SERVER:-mjzg4129@${FOOT_SERVER_HOST:-data-workers.com}}
DEST=${FOOT_BACKUP_DIR:-$HOME/Documents/dataScience/sport/football/sauvegardes_foot}
PY=${FOOT_BACKUP_PY:-$HOME/Documents/dataScience/sport/football/transfermarkt/.venv/bin/python}
mkdir -p "$DEST"
exec >> "$DEST/sauvegarde.log" 2>&1
echo "=== $(date '+%F %T')"
latest=$(ssh -q "$SRV" 'ls -1d ~/data/sauvegardes/foot-* | tail -1' </dev/null)
name=$(basename "$latest")
rsync -a --partial --include='z_raw_*.parquet' --include='z_technique_*.parquet' --include='schema.sql' \
  --include='load.sql' --exclude='*' -e "ssh -q" "$SRV:$latest/" "$DEST/$name/"
echo "copied $name: $(du -sh "$DEST/$name" | cut -f1)"
"$PY" tools/test_restauration.py "$DEST/$name"
ls -1d "$DEST"/foot-* | sort -r | tail -n +3 | while read -r old; do rm -rf "$old"; echo "removed $(basename "$old")"; done
echo "ok"

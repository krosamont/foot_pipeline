#!/bin/bash
# Runs a job of dagster_foot from the cron (o2switch allows no dagster-daemon):
#   dagster_foot/dagster_run.sh journee|nuit|controles|sauvegarde
# Takes the lock of the base (the same as the old orchestrator: never two writers), pulls foot_db first for the job
# nuit, refreshes the dbt manifest (dbt parse) that dagster-dbt reads, runs the job with the Dagster CLI (run history
# in $DAGSTER_HOME, seen in the UI), writes a log per run (~/data/dagster/logs, 30 days kept) and e-mails a failure.
# UI on demand: dagster_foot/dagster_ui.sh on the server, then ssh -L 3333:127.0.0.1:3333 from the Mac.
set -uo pipefail
JOB=${1:?usage: dagster_run.sh journee|nuit|controles|sauvegarde}
HERE=$(cd "$(dirname "$0")/.." && pwd)
DATA=$HOME/data
VENV=${DAGSTER_VENV:-$DATA/dagster/.venv}
export DAGSTER_HOME=${DAGSTER_HOME:-$DATA/dagster/home} FOOT_3D=${FOOT_3D:-$DATA/foot_3d}
mkdir -p "$DAGSTER_HOME" "$DATA/dagster/logs" "$DATA/pipelines"
[ -f "$DAGSTER_HOME/dagster.yaml" ] || printf 'telemetry:\n  enabled: false\n' > "$DAGSTER_HOME/dagster.yaml"
LOG=$DATA/dagster/logs/$JOB-$(date +%F_%H%M).log
WAIT=1800; [ "$JOB" = nuit ] && WAIT=3600
exec 9>"$DATA/pipelines/.base_foot.lock"
if ! flock -w "$WAIT" 9; then echo "$(date '+%F %T') $JOB: lock of the base still taken after ${WAIT}s, not run" >> "$LOG"; exit 0; fi
{
  echo "=== $(date '+%F %T') $JOB"
  if [ "$JOB" = nuit ]; then (cd "$DATA/foot_db" && git pull -q --ff-only && git log --oneline -1); fi
  (cd "$DATA/foot_db" && "$VENV/bin/dbt" parse --profiles-dir . --quiet) &&
  cd "$HERE" && "$VENV/bin/dagster" job execute -m dagster_foot -j "$JOB"
} >> "$LOG" 2>&1
code=$?
echo "=== $(date '+%F %T') $JOB: exit $code" >> "$LOG"
if [ $code -ne 0 ]; then
  { printf 'From: pipelines <noreply@data-workers.com>\nTo: %s\nSubject: [dagster] %s failed\n\n' \
      "${PIPELINES_MAIL:-krosamont@data-workers.com}" "$JOB"; tail -n 80 "$LOG"; } | /usr/sbin/sendmail -t -oi || true
fi
find "$DATA/dagster/logs" -name '*.log' -mtime +30 -delete 2>/dev/null
exit $code

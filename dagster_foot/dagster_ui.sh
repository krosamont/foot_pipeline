#!/bin/bash
# The Dagster UI on demand (no permanent process on o2switch): on the server
#   dagster_foot/dagster_ui.sh            (stops by itself after 2 hours; Ctrl-C to stop earlier)
# then on the Mac: ssh -N -L 3333:127.0.0.1:3333 mjzg4129@data-workers.com  and open http://localhost:3333
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
VENV=${DAGSTER_VENV:-$HOME/data/dagster/.venv}
export DAGSTER_HOME=${DAGSTER_HOME:-$HOME/data/dagster/home} FOOT_3D=${FOOT_3D:-$HOME/data/foot_3d}
cd "$HERE" && exec timeout 2h "$VENV/bin/dagster-webserver" -m dagster_foot -h 127.0.0.1 -p 3333

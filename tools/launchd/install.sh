#!/bin/bash
# Installs the launchd job of the off-server backup (tools/sauvegarde_mac.sh) for the current user, pointing at this
# checkout of foot_pipeline (keep it in a stable place, not a temporary folder).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
PLIST=~/Library/LaunchAgents/com.krosamont.foot-sauvegarde.plist
sed "s#__REPO__#$REPO#" "$REPO/tools/launchd/com.krosamont.foot-sauvegarde.plist" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed: $PLIST -> $REPO/tools/sauvegarde_mac.sh"

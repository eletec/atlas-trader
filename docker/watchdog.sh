#!/bin/sh
# Watchdog : redémarre le trader si aucun heartbeat depuis 30min
while true; do
    sleep 300
    if [ -f /tmp/atlas_heartbeat ]; then
        NOW=$(date +%s)
        MTIME=$(stat -c %Y /tmp/atlas_heartbeat)
        AGE=$(( NOW - MTIME ))
        if [ "$AGE" -gt 1800 ]; then
            echo "[WATCHDOG] Heartbeat age=${AGE}s > 30min — restart trader"
            supervisorctl -s unix:///tmp/supervisor.sock restart trader
        fi
    fi
done

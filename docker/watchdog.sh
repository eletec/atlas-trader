#!/bin/sh
# Watchdog : redémarre le trader si aucun heartbeat depuis 30min
while true; do
    sleep 300
    if [ -f /tmp/atlas_heartbeat ]; then
        NOW=$(date +%s)
        MTIME=$(stat -c %Y /tmp/atlas_heartbeat)
        AGE=$(( NOW - MTIME ))
        if [ "$AGE" -gt 1800 ]; then
            echo "[WATCHDOG] Heartbeat age=${AGE}s > 30min — stack dump + restart trader"
            # Dump toutes les stacks AVANT le restart pour diagnostiquer la cause
            TRADER_PID=$(ps aux | grep "main.py --daemon" | grep -v grep | awk '{print $2}' | head -1)
            if [ -n "$TRADER_PID" ]; then
                echo "[WATCHDOG] Sending SIGUSR1 to PID=$TRADER_PID for stack dump"
                kill -USR1 "$TRADER_PID"
                sleep 2
            fi
            supervisorctl -s unix:///tmp/supervisor.sock restart trader
        fi
    fi
done

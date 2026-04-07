#!/bin/sh
# Watchdog : redémarre le trader si aucun heartbeat depuis 30min
# Supporte V1 (/tmp/atlas_heartbeat) et V2 (/tmp/atlas_heartbeat_*)
while true; do
    sleep 300
    NOW=$(date +%s)
    NEWEST_AGE=99999

    # Chercher le heartbeat le plus récent parmi tous les actifs (V2)
    for hb in /tmp/atlas_heartbeat /tmp/atlas_heartbeat_*; do
        [ -f "$hb" ] || continue
        MTIME=$(stat -c %Y "$hb" 2>/dev/null) || continue
        AGE=$(( NOW - MTIME ))
        if [ "$AGE" -lt "$NEWEST_AGE" ]; then
            NEWEST_AGE=$AGE
            NEWEST_FILE=$hb
        fi
    done

    if [ "$NEWEST_AGE" -lt 99999 ]; then
        if [ "$NEWEST_AGE" -gt 1800 ]; then
            echo "[WATCHDOG] Heartbeat le plus récent: $NEWEST_FILE age=${NEWEST_AGE}s > 30min — stack dump + restart trader"
            TRADER_PID=$(ps aux | grep "main.py --daemon" | grep -v grep | awk '{print $2}' | head -1)
            if [ -n "$TRADER_PID" ]; then
                echo "[WATCHDOG] Sending SIGUSR1 to PID=$TRADER_PID for stack dump"
                kill -USR1 "$TRADER_PID"
                sleep 2
            fi
            supervisorctl -s unix:///tmp/supervisor.sock restart trader
        else
            echo "[WATCHDOG] OK — heartbeat le plus récent: ${NEWEST_AGE}s ($(basename $NEWEST_FILE))"
        fi
    else
        echo "[WATCHDOG] Aucun heartbeat trouvé dans /tmp/ — trader pas encore démarré ?"
    fi
done

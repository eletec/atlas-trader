#!/bin/bash
# ============================================================
# healthcheck.sh — Atlas Trader
# Vérifie que le container est opérationnel
# ============================================================
set -euo pipefail

EXIT_OK=0
EXIT_FAIL=1

# ---- 1. Vérifier que Streamlit répond (dashboard) ----
check_streamlit() {
    curl -sf --max-time 5 "http://localhost:8501/_stcore/health" > /dev/null 2>&1
    return $?
}

# ---- 2. Vérifier que le process supervisord est actif ----
check_supervisord() {
    pgrep -x supervisord > /dev/null 2>&1 || \
    pgrep -f "supervisord" > /dev/null 2>&1
    return $?
}

# ---- 3. Vérifier que la base de données SQLite est accessible ----
check_database() {
    python -c "
import sys
try:
    from storage.database import get_connection
    with get_connection() as conn:
        conn.execute('SELECT 1').fetchone()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
    return $?
}

# ============================================================
# Logique de healthcheck
# ============================================================
FAILED=0

# Vérification Streamlit (critique)
if ! check_streamlit; then
    echo "HEALTHCHECK FAIL: Streamlit dashboard ne répond pas sur le port 8501" >&2
    FAILED=1
fi

# Vérification supervisord (si mode all-in-one)
if ! check_supervisord; then
    # Non critique si on tourne en mode daemon ou dashboard seul
    echo "HEALTHCHECK INFO: supervisord non actif (mode service unique)" >&2
fi

# Vérification DB (critique)
if ! check_database; then
    echo "HEALTHCHECK FAIL: Base de données SQLite inaccessible" >&2
    FAILED=1
fi

if [ "${FAILED}" -eq 0 ]; then
    echo "HEALTHCHECK OK"
    exit ${EXIT_OK}
else
    exit ${EXIT_FAIL}
fi

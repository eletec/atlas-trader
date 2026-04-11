#!/bin/bash
# ============================================================
# entrypoint.sh — Atlas Trader
# Gère les différents modes de démarrage du container
# ============================================================
set -euo pipefail

WORKDIR="/app"
ENV_FILE="${WORKDIR}/.env"
CMD="${1:-all}"

# ---- Couleurs pour les logs ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[ATLAS]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[ATLAS]${NC} $*"; }
log_error() { echo -e "${RED}[ATLAS]${NC} $*" >&2; }

# ============================================================
# 1. Vérification du fichier .env
# ============================================================
check_env() {
    if [ -f "${ENV_FILE}" ]; then
        log_info "Fichier .env détecté — chargement des variables d'environnement."
    else
        if [ -f "${WORKDIR}/.env.example" ]; then
            log_warn "Pas de fichier .env trouvé — copie depuis .env.example."
            log_warn "IMPORTANT : Renseignez vos clés API dans /app/.env puis relancez le container."
            cp "${WORKDIR}/.env.example" "${ENV_FILE}"
        else
            log_warn "Aucun fichier .env ni .env.example trouvé. Les variables d'environnement doivent être injectées via docker-compose."
        fi
    fi
}

# ============================================================
# 2. Initialisation de la base de données
# ============================================================
init_db() {
    log_info "Initialisation de la base de données SQLite..."
    python -c "
from storage.database import init_db
init_db()
print('Base de données initialisée.')
"
}

# ============================================================
# 3. Création des répertoires persistants + fix permissions
# ============================================================
init_dirs() {
    mkdir -p /app/logs /app/storage /app/config
    # Fix permissions sur config/assets (bind-mount host peut être owned par un autre UID)
    chmod -R a+rw /app/config/assets 2>/dev/null || true
}

# ============================================================
# 4. Démarrage selon le mode
# ============================================================
MODE="${CMD}"
log_info "======================================================"
log_info "  Atlas Trader — démarrage en mode : ${MODE}"
log_info "======================================================"

check_env
init_dirs
init_db

case "${MODE}" in

    # ----- Mode tout-en-un : supervisord gère les deux processus -----
    all)
        log_info "Démarrage de supervisord (trader + dashboard)..."
        exec /usr/bin/supervisord -c /app/docker/supervisord.conf
        ;;

    # ----- Mode daemon uniquement -----
    trader)
        log_info "Démarrage du daemon trader uniquement..."
        exec python /app/main.py --daemon
        ;;

    # ----- Mode dashboard uniquement -----
    dashboard)
        log_info "Démarrage du dashboard Streamlit uniquement (port 8501)..."
        exec streamlit run /app/dashboard/streamlit_app.py \
            --server.headless true \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.enableCORS false \
            --server.enableXsrfProtection true
        ;;

    # ----- Mode run-once : un seul cycle -----
    run-once)
        log_info "Exécution d'un seul cycle de trading..."
        exec python /app/main.py --run-once
        ;;

    # ----- Mode test : lancement de pytest -----
    test)
        log_info "Exécution de la suite de tests..."
        exec python -m pytest /app/test_run_full_cycle.py -v --tb=short
        ;;

    # ----- Mode post-mortem manuel -----
    post-mortem)
        log_info "Exécution de l'agent post-mortem..."
        exec python /app/main.py --post-mortem
        ;;

    # ----- Shell interactif (debug) -----
    shell|bash)
        log_info "Ouverture d'un shell bash interactif."
        exec /bin/bash
        ;;

    # ----- Commande arbitraire passée directement -----
    *)
        log_warn "Mode inconnu '${MODE}'. Exécution comme commande directe : $*"
        exec "$@"
        ;;
esac

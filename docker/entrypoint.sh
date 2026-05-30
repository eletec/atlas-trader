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
    mkdir -p /app/logs /app/storage /app/config /app/config/assets

    CURRENT_USER=$(id -u)
    log_info "Utilisateur container : UID=${CURRENT_USER} ($(id -un 2>/dev/null || echo unknown))"

    if [ "${CURRENT_USER}" = "0" ]; then
        # On tourne en root → chmod garanti sur tous les bind-mounts
        log_info "Fix permissions config (root) — chmod 666 *.yaml, chmod 777 assets/"
        find /app/config -maxdepth 1 -name "*.yaml" -exec chmod 666 {} + 2>/dev/null || true
        chmod -R 777 /app/config/assets 2>/dev/null || true
        chown -R atlas:atlas /app/logs /app/storage 2>/dev/null || true
    else
        # On tourne en utilisateur non-root (atlas) — tentative best-effort
        log_warn "Démarrage en non-root (UID=${CURRENT_USER}) — tentative chmod best-effort"
        find /app/config -maxdepth 1 -name "*.yaml" -exec chmod a+rw {} + 2>/dev/null || true
        chmod -R a+rwx /app/config/assets 2>/dev/null || true
        log_warn "Si la sauvegarde échoue : docker exec -u root atlas-trader-gx10 chmod -R 666 /app/config/"
    fi
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

# ── Injection des fichiers Python storage (masqués par le volume nommé) ──────
# Le volume atlas_storage_gx10 monte /app/storage et masque les .py copiés
# dans l'image au build. On les copie depuis le staging /app/_storage_src/
# à chaque démarrage pour que git pull + rebuild soient toujours reflétés.
if [ -d /app/_storage_src ]; then
    cp -f /app/_storage_src/*.py /app/storage/ 2>/dev/null || true
    log_info "storage/*.py injectés depuis _storage_src ($(ls /app/_storage_src/*.py 2>/dev/null | wc -l) fichiers)"
fi

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

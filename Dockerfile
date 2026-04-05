# ============================================================
# Atlas Trader — Dockerfile multi-stage
# Stage 1 : builder (installation des dépendances + wheels)
# Stage 2 : runtime (image finale légère)
# ============================================================

# ----- Stage 1 : Builder -----
FROM python:3.11-slim AS builder

WORKDIR /build

# Dépendances système pour la compilation des wheels Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier uniquement le requirements pour bénéficier du cache Docker
COPY requirements.txt .

# Installer les dépendances dans un répertoire isolé
# NOTE: on installe d'abord pip/wheel/packaging avec --prefix pour éviter qu'ils
# restent uniquement au niveau système et soient absents du stage runtime.
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir wheel packaging && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# MiroFish optionnel — echec tolere (mode fallback actif si absent)
RUN pip install --prefix=/install --no-cache-dir git+https://github.com/666ghj/MiroFish.git || \
    echo "WARNING: MiroFish unavailable, fallback mode active"

# Pré-télécharger le modèle TimesFM 500M (~2GB) dans le cache HuggingFace
# pour éviter le téléchargement au premier lancement du container
RUN PYTHONPATH=/install/lib/python3.11/site-packages \
    python -c "from huggingface_hub import snapshot_download; snapshot_download('google/timesfm-2.0-500m-pytorch')" || \
    echo "WARNING: TimesFM model download failed, will retry at runtime"

# Installer Playwright browsers (pour le fallback crawling)
RUN pip install --prefix=/install --no-cache-dir playwright && \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    /install/bin/playwright install chromium --with-deps || true


# ----- Stage 2 : Runtime -----
FROM python:3.11-slim AS runtime

LABEL maintainer="Atlas Trader"
LABEL description="Système de trading IA autonome — MiroFish + LangGraph"
LABEL version="1.0.0-MVP"

# Variables d'environnement par défaut
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HF_HOME=/home/atlas/.cache/huggingface \
    PORT_DASHBOARD=8501 \
    LOG_LEVEL=INFO \
    ENVIRONMENT=production

# Dépendances système runtime uniquement
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    procps \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copier les wheels installés depuis le builder
COPY --from=builder /install /usr/local

# Copier le cache HuggingFace (modèle TimesFM pré-téléchargé)
COPY --from=builder /root/.cache/huggingface /home/atlas/.cache/huggingface

# Créer l'utilisateur non-root pour la sécurité
RUN groupadd -r atlas && useradd -r -g atlas -d /app -s /bin/bash atlas

# Répertoire de travail
WORKDIR /app

# Copier le code source
COPY --chown=atlas:atlas agents/           ./agents/
COPY --chown=atlas:atlas comparison/       ./comparison/
COPY --chown=atlas:atlas config/           ./config/
COPY --chown=atlas:atlas dashboard/        ./dashboard/
COPY --chown=atlas:atlas execution/        ./execution/
COPY --chown=atlas:atlas graph/            ./graph/
COPY --chown=atlas:atlas mirofish/         ./mirofish/
COPY --chown=atlas:atlas storage/          ./storage/
COPY --chown=atlas:atlas utils/            ./utils/
COPY --chown=atlas:atlas decision_engine.py main.py ./

# Copier les scripts Docker
COPY --chown=atlas:atlas docker/           ./docker/
RUN chmod +x ./docker/entrypoint.sh ./docker/healthcheck.sh ./docker/watchdog.sh

# Créer les répertoires persistables (montés en volumes)
RUN mkdir -p /app/logs /app/storage /data && \
    chown -R atlas:atlas /app /data /home/atlas

# Exposer le port Streamlit
EXPOSE 8501

# Healthcheck sur le dashboard
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /app/docker/healthcheck.sh

# Volumes pour la persistance des données
VOLUME ["/app/storage", "/app/logs", "/app/config"]

USER atlas

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["all"]

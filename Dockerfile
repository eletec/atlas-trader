# ============================================================
# Atlas Trader — Dockerfile multi-stage
# Stage 1: builder (dependency and wheel installation)
# Stage 2: runtime (lightweight final image)
# ============================================================

# ----- Stage 1 : Builder -----
FROM python:3.11-slim AS builder

WORKDIR /build

# System dependencies for compiling the Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file to take advantage of the Docker cache
COPY requirements.txt .

# Install the dependencies into an isolated directory
# NOTE: pip/wheel/packaging are installed first with --prefix so that they do not
# stay at system level only and end up missing from the runtime stage.
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir wheel packaging && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# (MiroFish, TimesFM, Playwright removed — the V2 pipeline does not use them)


# ----- Stage 2 : Runtime -----
FROM python:3.11-slim AS runtime

LABEL maintainer="Atlas Trader"
LABEL description="Autonomous AI trading system — MiroFish + LangGraph"
LABEL version="1.0.0-MVP"

# Default environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HF_HOME=/home/atlas/.cache/huggingface \
    PORT_DASHBOARD=8501 \
    LOG_LEVEL=INFO \
    ENVIRONMENT=production

# Runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    procps \
    sqlite3 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed wheels from the builder
COPY --from=builder /install /usr/local

# Create the non-root user for security
RUN groupadd -r atlas && useradd -r -g atlas -d /app -s /bin/bash atlas

# Working directory
WORKDIR /app

# Copy the source code
COPY --chown=atlas:atlas backtest/         ./backtest/
COPY --chown=atlas:atlas comparison/       ./comparison/
COPY --chown=atlas:atlas config/           ./config/
COPY --chown=atlas:atlas dashboard/        ./dashboard/
COPY --chown=atlas:atlas execution/        ./execution/
COPY --chown=atlas:atlas graph/            ./graph/
COPY --chown=atlas:atlas quant/            ./quant/
COPY --chown=atlas:atlas storage/          ./storage/
# Staging copy of the storage Python files — injected into the volume
# at startup by the entrypoint (a named volume would otherwise hide the image's .py files)
COPY --chown=atlas:atlas storage/*.py      ./_storage_src/
COPY --chown=atlas:atlas utils/            ./utils/
COPY --chown=atlas:atlas main.py ./

# Copy the Docker scripts
COPY --chown=atlas:atlas docker/           ./docker/
RUN chmod +x ./docker/entrypoint.sh ./docker/healthcheck.sh ./docker/watchdog.sh

# Create the persistable directories (mounted as volumes)
RUN mkdir -p /app/logs /app/storage /data && \
    chown -R atlas:atlas /app /data
EXPOSE 8501

# Healthcheck on the dashboard
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /app/docker/healthcheck.sh

# Volumes for data persistence
VOLUME ["/app/storage", "/app/logs", "/app/config"]

USER atlas

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["all"]

#!/bin/sh
# Entrypoint nginx — Atlas Trader GX10
# Bootstrap : génère un certificat auto-signé temporaire au chemin Let's Encrypt
# pour que nginx puisse démarrer avant que Certbot obtienne le vrai certificat.
DOMAIN=atlastrader.org
CERT_DIR=/etc/letsencrypt/live/$DOMAIN

if ! command -v openssl > /dev/null 2>&1; then
    apk add --no-cache openssl 2>/dev/null
fi

if [ ! -f "$CERT_DIR/fullchain.pem" ]; then
    echo "[nginx] Aucun certificat Let's Encrypt trouvé — génération d'un certificat temporaire..."
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$CERT_DIR/privkey.pem" \
        -out    "$CERT_DIR/fullchain.pem" \
        -subj "/CN=$DOMAIN"
    echo "[nginx] Certificat temporaire généré. Lancez certbot pour obtenir le vrai."
else
    echo "[nginx] Certificat Let's Encrypt trouvé."
fi

exec nginx -g "daemon off;"

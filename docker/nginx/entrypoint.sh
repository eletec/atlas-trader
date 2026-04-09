#!/bin/sh
# Génère un certificat auto-signé si absent (valide 10 ans)
CERT_DIR=/etc/nginx/certs

# openssl n'est pas inclus dans nginx:alpine — installation si absent
if ! command -v openssl > /dev/null 2>&1; then
    apk add --no-cache openssl
fi

if [ ! -f "$CERT_DIR/cert.pem" ]; then
    echo "[nginx-entrypoint] Génération du certificat auto-signé..."
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$CERT_DIR/key.pem" \
        -out    "$CERT_DIR/cert.pem" \
        -subj "/CN=atlas-trader/O=Atlas/C=FR" \
        -addext "subjectAltName=IP:127.0.0.1"
    echo "[nginx-entrypoint] Certificat généré."
else
    echo "[nginx-entrypoint] Certificat existant trouvé."
fi

exec nginx -g "daemon off;"

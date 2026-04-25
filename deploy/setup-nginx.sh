#!/usr/bin/env bash
# Run ON THE GCP VM (as a user with sudo). Proxies port 80 → uvicorn on 127.0.0.1:8000
# with WebSocket headers. Usage:
#   ./deploy/setup-nginx.sh 35.232.28.166
# Or from repo root after clone:
#   bash deploy/setup-nginx.sh 35.232.28.166

set -euo pipefail

SERVER_NAME="${1:?Usage: $0 <public_ip_or_dns_name>}"
SITE_PATH="/etc/nginx/sites-available/claude-bridge"

if ! command -v nginx >/dev/null 2>&1; then
  echo "Installing nginx..."
  sudo apt-get update -qq
  sudo apt-get install -y nginx
fi

echo "Writing ${SITE_PATH} (server_name=${SERVER_NAME})..."
sudo tee "${SITE_PATH}" >/dev/null <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${SERVER_NAME};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
EOF

sudo ln -sf "${SITE_PATH}" /etc/nginx/sites-enabled/claude-bridge
if [[ -f /etc/nginx/sites-enabled/default ]]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi

sudo nginx -t
sudo systemctl reload nginx
echo "Done. Ensure uvicorn listens on 127.0.0.1:8000 and GCP firewall allows tcp:80."

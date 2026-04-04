#!/bin/bash
# update.sh — aktualizacja UODO RAG po zmianach w kodzie
#
# Użycie:
#   bash deploy/update.sh              # tylko kod Python (git pull + restart)
#   bash deploy/update.sh --frontend   # + przebudowa frontendu

set -euo pipefail

REMOTE_HOST="root@steve141.mikrus.xyz"
REMOTE_PORT="10141"
REMOTE_DIR="/home/kwasiucionek/uodo_rag"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VITE_API_URL=""

SSH="ssh -p $REMOTE_PORT $REMOTE_HOST"

REBUILD_FRONTEND=false
for arg in "$@"; do
    [ "$arg" = "--frontend" ] && REBUILD_FRONTEND=true
done

echo "=== UODO RAG Update ==="

# ── Frontend (opcjonalnie) ────────────────────────────────────────
if [ "$REBUILD_FRONTEND" = true ]; then
    echo "[1] Build frontendu..."
    cd "$LOCAL_DIR/frontend"
    VITE_API_URL="" npm run build

    echo "  Kopiowanie dist na serwer..."
    scp -P "$REMOTE_PORT" -r "$LOCAL_DIR/frontend/dist/." \
        "$REMOTE_HOST:$REMOTE_DIR/frontend/dist/"
    echo "✅ Frontend zaktualizowany"
fi

# ── Git pull + restart ────────────────────────────────────────────
echo "[2] Git pull + restart..."
$SSH bash << 'REMOTE'
set -euo pipefail
cd /home/kwasiucionek/uodo_rag

git config --global --add safe.directory /home/kwasiucionek/uodo_rag 2>/dev/null || true
git pull

source .venv/bin/activate
pip install -q -r requirements.txt

# Zaktualizuj nginx jeśli się zmieniła konfiguracja
sudo cp deploy/nginx-uodo-rag.conf /etc/nginx/sites-available/uodo-rag
sudo nginx -t && sudo systemctl reload nginx

# Zaktualizuj systemd jeśli się zmienił service
sudo cp deploy/uodo-rag.service /etc/systemd/system/
sudo systemctl daemon-reload

# Restart FastAPI
sudo systemctl restart uodo-rag
sleep 3
sudo systemctl status uodo-rag --no-pager | tail -3
REMOTE

echo ""
echo "✅ Aktualizacja zakończona"
echo "   curl http://pro01.mikr.us:44306/health"

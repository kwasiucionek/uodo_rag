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
VITE_API_URL="http://pro01.mikr.us:44306"

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
    VITE_API_URL="$VITE_API_URL" npm run build

    echo "  Kopiowanie dist na serwer..."
    scp -P "$REMOTE_PORT" -r "$LOCAL_DIR/frontend/dist/app" \
        "$REMOTE_HOST:$REMOTE_DIR/frontend/dist/"
    echo "✅ Frontend zaktualizowany"
fi

# ── Git pull + restart ────────────────────────────────────────────
echo "[2] Git pull + restart..."
$SSH bash << 'REMOTE'
set -euo pipefail
cd /home/kwasiucionek/uodo_rag

git pull

source .venv/bin/activate
pip install -q -r requirements.txt

# Zaktualizuj konfiguracje systemd jeśli się zmieniły
cp deploy/uodo-rag.service    /etc/systemd/system/ 2>/dev/null || true
cp deploy/uodo-update.service /etc/systemd/system/ 2>/dev/null || true
cp deploy/uodo-update.timer   /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload

# Zaktualizuj nginx jeśli się zmieniła konfiguracja
cp deploy/nginx-uodo-rag.conf /etc/nginx/sites-available/uodo-rag
nginx -t && systemctl reload nginx

# Restart FastAPI
systemctl restart uodo-rag
sleep 3
systemctl status uodo-rag --no-pager | tail -3
REMOTE

echo ""
echo "✅ Aktualizacja zakończona"
echo "   curl http://pro01.mikr.us:44306/health"

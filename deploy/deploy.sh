#!/bin/bash
# deploy.sh — pierwsze wdrożenie UODO RAG na Mikrus steve141
#
# Uruchom lokalnie:
#   bash deploy/deploy.sh

set -euo pipefail

# ── Konfiguracja ─────────────────────────────────────────────────
REMOTE_HOST="root@steve141.mikrus.xyz"
REMOTE_PORT="10141"
REMOTE_DIR="/home/kwasiucionek/uodo_rag"
GIT_REPO="https://github.com/kwasiucionek/uodo-rag.git"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VITE_API_URL="http://pro01.mikr.us:44306"

SSH="ssh -p $REMOTE_PORT $REMOTE_HOST"

echo "=== UODO RAG — Pierwsze wdrożenie ==="
echo "Repo:   $GIT_REPO"
echo "Remote: $REMOTE_HOST:$REMOTE_DIR"
echo ""

# ── 1. Build frontendu (lokalnie) ────────────────────────────────
echo "[1/6] Build frontendu..."
cd "$LOCAL_DIR/frontend"
VITE_API_URL="$VITE_API_URL" npm run build
echo "✅ Frontend zbudowany"

# ── 2. Skopiuj .env i dist na serwer ─────────────────────────────
echo ""
echo "[2/6] Kopiowanie .env i frontendu..."

scp -P "$REMOTE_PORT" "$LOCAL_DIR/.env" \
    "$REMOTE_HOST:/tmp/uodo_rag_env"

ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "mkdir -p $REMOTE_DIR/frontend/dist"

scp -P "$REMOTE_PORT" -r "$LOCAL_DIR/frontend/dist/." \
    "$REMOTE_HOST:$REMOTE_DIR/frontend/dist/"

echo "✅ Pliki skopiowane"

# ── 3. Git clone + konfiguracja serwera ──────────────────────────
echo ""
echo "[3/6] Git clone + konfiguracja..."
$SSH bash -s "$REMOTE_DIR" "$GIT_REPO" << 'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
GIT_REPO="$2"

if [ -d "$REMOTE_DIR/.git" ]; then
    echo "  Repo już istnieje — git pull"
    cd "$REMOTE_DIR"
    git config --global --add safe.directory "$REMOTE_DIR"  # ← dodaj
    git pull
else
    echo "  Klonowanie repo..."
    git clone "$GIT_REPO" "$REMOTE_DIR"
    cd "$REMOTE_DIR"
fi

mv /tmp/uodo_rag_env "$REMOTE_DIR/.env"
echo "  .env zainstalowany"

if ! grep -q "vm.max_map_count" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
    sysctl -w vm.max_map_count=262144
    echo "  vm.max_map_count ustawiony"
fi

cd "$REMOTE_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  Venv utworzony"
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q fastapi "uvicorn[standard]"
echo "  Zależności Python zainstalowane"

mkdir -p logs
REMOTE
# ── 4. OpenSearch ────────────────────────────────────────────────
echo ""
echo "[4/6] OpenSearch..."
$SSH bash << 'REMOTE'
cd /home/kwasiucionek/uodo_rag
cp deploy/docker-compose.yml docker-compose.yml
docker compose up -d
echo "  Czekam na OpenSearch (max 90s)..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:9200 > /dev/null 2>&1; then
        echo "  ✅ OpenSearch działa"
        break
    fi
    sleep 3
    echo "  ... $((i*3))s"
done
REMOTE

# ── 5. Nginx ─────────────────────────────────────────────────────
echo ""
echo "[5/6] Nginx..."
$SSH bash << 'REMOTE'
cp /home/kwasiucionek/uodo_rag/deploy/nginx-uodo-rag.conf \
   /etc/nginx/sites-available/uodo-rag
ln -sf /etc/nginx/sites-available/uodo-rag /etc/nginx/sites-enabled/uodo-rag
nginx -t && systemctl reload nginx
echo "  ✅ Nginx skonfigurowany"
REMOTE

# ── 6. Systemd ───────────────────────────────────────────────────
echo ""
echo "[6/6] Systemd..."
$SSH bash << 'REMOTE'
cp /home/kwasiucionek/uodo_rag/deploy/uodo-rag.service    /etc/systemd/system/
cp /home/kwasiucionek/uodo_rag/deploy/uodo-update.service /etc/systemd/system/
cp /home/kwasiucionek/uodo_rag/deploy/uodo-update.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now uodo-rag
systemctl enable --now uodo-update.timer
sleep 5
systemctl status uodo-rag --no-pager | tail -5
REMOTE

echo ""
echo "=== Deploy zakończony ==="
echo ""
echo "Następny krok — indeksowanie (na serwerze):"
echo "  ssh root@steve141.mikrus.xyz -p 10141"
echo "  cd /home/kwasiucionek/uodo_rag"
echo "  source .venv/bin/activate"
echo "  CUDA_VISIBLE_DEVICES='' python tools/opensearch_indexer.py --mode all \\"
echo "    --jsonl tools/uodo_decisions.jsonl \\"
echo "    --md-act tools/D20191781L.md \\"
echo "    --md-rodo tools/rodo_2016_679_pl.md"
echo ""
echo "Aplikacja po indeksowaniu:"
echo "  http://pro01.mikr.us:44306"
echo "  http://pro01.mikr.us:44306/developer"

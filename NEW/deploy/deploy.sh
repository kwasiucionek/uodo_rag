#!/bin/bash
# deploy.sh — pierwsze wdrożenie UODO RAG na Mikrus steve141
#
# Uruchom lokalnie:
#   bash deploy/deploy.sh
#
# Wymagania:
#   - Repo dostępne publicznie lub SSH key na serwerze
#   - Plik .env przygotowany lokalnie
#   - frontend/dist/ zbudowany i w repo (lub skopiowany przez scp)

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

# Napraw git safe.directory (Mikrus — root klonuje do katalogu innego usera)
git config --global --add safe.directory "$REMOTE_DIR" 2>/dev/null || true

if [ -d "$REMOTE_DIR/.git" ]; then
    echo "  Repo już istnieje — git pull"
    cd "$REMOTE_DIR"
    git pull
else
    echo "  Klonowanie repo..."
    git clone "$GIT_REPO" "$REMOTE_DIR"
    cd "$REMOTE_DIR"
fi

mv /tmp/uodo_rag_env "$REMOTE_DIR/.env"
echo "  .env zainstalowany"

# vm.max_map_count dla OpenSearch
if ! grep -q "vm.max_map_count" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf
    sysctl -w vm.max_map_count=262144
    echo "  vm.max_map_count ustawiony"
fi

# Python venv
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

echo "✅ Serwer skonfigurowany"

# ── 4. OpenSearch ────────────────────────────────────────────────
# Uwaga: docker compose nie działa na Mikrus (blokuje rlimits).
# Używamy docker run bezpośrednio.
echo ""
echo "[4/6] OpenSearch..."
$SSH bash << 'REMOTE'
# Usuń stary kontener jeśli istnieje
sudo docker rm -f opensearch-uodo 2>/dev/null || true

sudo docker run -d \
    --name opensearch-uodo \
    --restart unless-stopped \
    -p 127.0.0.1:9200:9200 \
    -p 127.0.0.1:9600:9600 \
    -v opensearch-uodo-data:/usr/share/opensearch/data \
    -e discovery.type=single-node \
    -e bootstrap.memory_lock=false \
    -e "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g" \
    -e DISABLE_SECURITY_PLUGIN=true \
    -e DISABLE_INSTALL_DEMO_CONFIG=true \
    opensearchproject/opensearch:2.18.0

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
sudo cp /home/kwasiucionek/uodo_rag/deploy/nginx-uodo-rag.conf \
    /etc/nginx/sites-available/uodo-rag
sudo ln -sf /etc/nginx/sites-available/uodo-rag \
    /etc/nginx/sites-enabled/uodo-rag

# Nginx wymaga execute na katalogu domowym
chmod o+x /home/kwasiucionek

sudo nginx -t && sudo systemctl reload nginx
echo "  ✅ Nginx skonfigurowany"
REMOTE

# ── 6. Systemd ───────────────────────────────────────────────────
echo ""
echo "[6/6] Systemd..."
$SSH bash << 'REMOTE'
sudo cp /home/kwasiucionek/uodo_rag/deploy/uodo-rag.service \
    /etc/systemd/system/

# Timer aktualizacji (opcjonalny)
if [ -f /home/kwasiucionek/uodo_rag/deploy/uodo-update.service ]; then
    sudo cp /home/kwasiucionek/uodo_rag/deploy/uodo-update.service \
        /etc/systemd/system/
    sudo cp /home/kwasiucionek/uodo_rag/deploy/uodo-update.timer \
        /etc/systemd/system/
fi

sudo systemctl daemon-reload
sudo systemctl enable --now uodo-rag

sleep 5
sudo systemctl status uodo-rag --no-pager | tail -5
REMOTE

echo ""
echo "=== Deploy zakończony ==="
echo ""
echo "Sprawdź:"
echo "  curl http://pro01.mikr.us:44306/health"
echo "  http://pro01.mikr.us:44306"
echo "  http://pro01.mikr.us:44306/developer"
echo ""
echo "Następny krok — indeksowanie (na serwerze):"
echo "  ssh root@steve141.mikrus.xyz -p 10141"
echo "  cd /home/kwasiucionek/uodo_rag"
echo "  source .venv/bin/activate"
echo "  CUDA_VISIBLE_DEVICES='' python tools/opensearch_indexer.py --mode all \\"
echo "    --jsonl tools/uodo_decisions.jsonl \\"
echo "    --md-act tools/D20191781L.md \\"
echo "    --md-rodo tools/rodo_2016_679_pl.md"

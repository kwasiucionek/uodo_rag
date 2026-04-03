# UODO RAG — Wyszukiwarka Decyzji z Odpowiedziami AI

System RAG (Retrieval-Augmented Generation) do przeszukiwania decyzji Prezesa Urzędu Ochrony Danych Osobowych, ustawy o ochronie danych osobowych oraz rozporządzenia RODO. Zaprojektowany jako serwis API-first z osadzalnym widgetem frontendowym.

## Architektura

```
FastAPI backend (api.py)          OpenSearch 2.18
     ↑ REST + SSE                      ↑
     │                           indeks wektorowy
     ├── widget.iife.js          (kNN + BM25 + RRF)
     │   osadzalny na dowolnej
     │   stronie przez <script>
     │
     └── standalone SPA
         React + Vite + TypeScript
```

**Trzy źródła wiedzy:**

| Typ | Źródło | Liczba |
|---|---|---|
| Decyzje UODO | [orzeczenia.uodo.gov.pl](https://orzeczenia.uodo.gov.pl) | ~560 |
| Ustawa o ochronie danych (u.o.d.o.) | [Dz.U. 2019 poz. 1781](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20190001781) | Art. 1–108 |
| RODO — artykuły i motywy | [EUR-Lex 32016R0679](https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:32016R0679) | 99 art. + 173 motywy |

**Model embeddingowy:** [`sdadas/stella-pl-retrieval-8k`](https://huggingface.co/sdadas/stella-pl-retrieval-8k) — #3 na [PIRB](https://huggingface.co/spaces/sdadas/pirb) (NDCG@10 = 62.69), 1.5B parametrów, kontekst 8192 tokenów, dim=1024.

---

## Wymagania

- Python 3.11+
- Node.js 20+
- Docker (dla OpenSearch)
- GPU z min. 8 GB VRAM (rekomendowane), lub CPU

---

## Instalacja

### 1. Klonowanie i środowisko

```bash
git clone <repo>
cd uodo-rag

python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
pip install fastapi "uvicorn[standard]"
```

### 2. Zmienne środowiskowe

Utwórz plik `.env` w katalogu głównym:

```env
# OpenSearch
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=uodo_decisions

# Model embeddingowy
EMBED_MODEL=sdadas/stella-pl-retrieval-8k

# LLM — Ollama Cloud (zalecany)
OLLAMA_URL=http://localhost:11434
OLLAMA_CLOUD_API_KEY=twoj_klucz

# LLM — Groq (alternatywny)
GROQ_API_KEY=twoj_klucz

# CORS — domeny frontendowe (przecinek jako separator)
ALLOWED_ORIGINS=http://localhost:5173,https://orzeczenia.uodo.gov.pl
```

### 3. OpenSearch

```bash
docker compose up -d

# Weryfikacja (poczekaj ~30 sekund)
curl http://localhost:9200
# {"version":{"number":"2.18.0",...}}
```

> **Linux:** Jeśli OpenSearch nie startuje, uruchom:
> ```bash
> sudo sysctl -w vm.max_map_count=262144
> ```

### 4. Przygotowanie danych

#### 4a. Scrapowanie decyzji UODO

```bash
# Pobierz wszystkie decyzje z portalu orzeczenia.uodo.gov.pl
python tools/uodo_scraper.py --output tools/uodo_decisions.jsonl

# Test (3 decyzje)
python tools/uodo_scraper.py --test
```

Scraper pobiera treść w formacie XML i automatycznie wyciąga:
- Pełną treść podzieloną na sekcje (`xType="sect"`)
- Referencje do aktów prawnych z tagów `<xLexLink xRef="...">`
- Metadane: taksonomia, status, daty, encje

#### 4b. Indeksowanie

```bash
python tools/opensearch_indexer.py --mode all \
  --jsonl   tools/uodo_decisions.jsonl \
  --md-act  tools/D20191781L.md \
  --md-rodo tools/rodo_2016_679_pl.md

# Jeśli OOM na GPU:
python tools/opensearch_indexer.py --mode all \
  --jsonl   tools/uodo_decisions.jsonl \
  --md-act  tools/D20191781L.md \
  --md-rodo tools/rodo_2016_679_pl.md \
  --batch-size 8

# Indeksowanie na CPU (bez GPU):
CUDA_VISIBLE_DEVICES="" python tools/opensearch_indexer.py --mode all ...
```

Czas indeksowania: ~20–40 min na GPU, ~2–4 h na CPU.

Tryby:

| Flaga | Opis |
|---|---|
| `--mode decisions` | Tylko decyzje UODO |
| `--mode act` | Tylko ustawa u.o.d.o. |
| `--mode rodo` | Tylko RODO |
| `--mode all` | Wszystkie typy |
| `--rebuild` | Usuń i przeindeksuj od nowa |

#### 4c. Opcjonalnie — słowa kluczowe dla artykułów

```bash
python tools/enrich_act_keywords.py --provider ollama --model qwen3:14b
```

---

## Uruchomienie

### Backend (FastAPI)

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Sprawdź:

```bash
curl http://localhost:8000/health
# {"status":"ok","opensearch":"ok","embedder":"ok"}

curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"dane genetyczne"}' | python -m json.tool
```

### Frontend

```bash
cd frontend
npm install

# Tryb deweloperski
VITE_API_URL=http://localhost:8000 npm run dev
# → http://localhost:5173
```

---

## Build produkcyjny

### Standalone SPA

```bash
cd frontend
VITE_API_URL=https://rag.uodo.gov.pl npm run build
# Wynik: frontend/dist/app/
```

Serwuj przez nginx:

```nginx
server {
    listen 443 ssl;
    server_name rag.uodo.gov.pl;

    root /var/www/uodo-rag/app;
    index index.html;

    # SPA — przekieruj wszystkie ścieżki do index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy do backendu FastAPI
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Connection '';        # SSE wymaga keep-alive
        proxy_buffering    off;                  # SSE wymaga wyłączonego bufora
        proxy_cache        off;
    }
}
```

### Osadzalny widget

```bash
cd frontend
VITE_API_URL=https://rag.uodo.gov.pl npm run build -- --mode widget
# Wynik: frontend/dist/widget.iife.js
```

Użycie na dowolnej stronie:

```html
<!-- Metoda 1: ręczna inicjalizacja -->
<div id="uodo-rag-root"></div>
<script src="https://rag.uodo.gov.pl/widget.iife.js"></script>
<script>
  UodoRag.mount('#uodo-rag-root', { useLLM: true })
</script>

<!-- Metoda 2: Web Component (automatyczna) -->
<script src="https://rag.uodo.gov.pl/widget.iife.js"></script>
<uodo-rag-widget api-url="https://rag.uodo.gov.pl"></uodo-rag-widget>
```

---

## Struktura projektu

```
.
├── api.py                        # FastAPI backend — endpointy REST + SSE
├── config.py                     # Stałe i zmienne środowiskowe
├── opensearch_client.py          # Klient OpenSearch, schemat indeksu, query builders
├── search.py                     # Logika wyszukiwania (kNN + BM25 + hybrid RRF + graf)
├── llm.py                        # Wywołania LLM (Ollama Cloud / Groq)
├── models.py                     # Modele Pydantic + szablony Jinja2 kontekstu
├── ui.py                         # Budowanie kontekstu LLM, karty wyników (Streamlit)
├── main.py                       # Aplikacja Streamlit (narzędzie deweloperskie)
├── requirements.txt
├── docker-compose.yml            # OpenSearch single-node
│
├── tools/
│   ├── uodo_scraper.py           # Scraper decyzji z API portalu UODO (XML)
│   ├── opensearch_indexer.py     # Indeksowanie wszystkich typów dokumentów
│   ├── enrich_act_keywords.py    # Generowanie tagów dla artykułów przez LLM
│   ├── eval.py                   # Automatyczna ewaluacja (10 złotych pytań)
│   ├── enrich_jsonl_taxonomy.py  # (legacy) wzbogacanie starych JSONL
│   ├── D20191781L.md             # Tekst ustawy o ochronie danych osobowych
│   └── rodo_2016_679_pl.md       # Tekst RODO w języku polskim
│
└── frontend/
    ├── package.json
    ├── vite.config.ts            # Dwa tryby: standalone app i widget IIFE
    └── src/
        ├── api.ts                # Typowany klient API
        ├── hooks/useSearch.ts    # Hook — stan wyszukiwania + streaming LLM
        ├── UodoRagWidget.tsx     # Główny komponent widgetu
        ├── main.tsx              # Entry point — standalone SPA
        ├── widget.tsx            # Entry point — osadzalny widget + Web Component
        └── styles/widget.css     # Style kompatybilne z UODO design system
```

---

## API

### `POST /api/search`

```json
{
  "query": "monitoring wizyjny w miejscu pracy",
  "filters": {
    "status": "prawomocna",
    "term_sector": ["Zatrudnienie"],
    "year_from": 2022
  },
  "use_graph": true,
  "top_k": 8
}
```

### `POST /api/answer/stream`

Streaming SSE. Klient odbiera zdarzenia:

```
data: {"type": "token", "content": "Na podstawie"}
data: {"type": "token", "content": " decyzji..."}
data: {"type": "done"}
```

### Pozostałe endpointy

| Endpoint | Opis |
|---|---|
| `GET /api/tags` | Wszystkie tagi (autocomplete) |
| `GET /api/taxonomy` | Opcje filtrów taksonomii |
| `GET /api/stats` | Statystyki kolekcji |
| `GET /api/signature/{sig}` | Decyzja po sygnaturze |
| `POST /api/decompose` | Dekompozycja zapytania przez LLM |
| `GET /health` | Health check |

Pełna dokumentacja interaktywna: `http://localhost:8000/docs`

---

## Ewaluacja

```bash
# Pełna ewaluacja (10 złotych pytań)
python tools/eval.py

# Jedno pytanie z pełną odpowiedzią
python tools/eval.py --question 3 --verbose

# Wyniki zapisywane do eval_results.json
```

---

## Zmiana modelu embeddingowego

Wszystkie modele produkują wektory dim=1024 — schemat OpenSearch nie wymaga zmian. Po zmianie modelu obowiązkowe przeindeksowanie:

```bash
# Usuń stary indeks
curl -X DELETE http://localhost:9200/uodo_decisions

# Zmień EMBED_MODEL w .env, potem przeindeksuj
python tools/opensearch_indexer.py --mode all ...
```

| Model | NDCG@10 (PIRB) | Params | VRAM |
|---|---|---|---|
| `sdadas/stella-pl-retrieval-8k` *(domyślny)* | 62.69 | 1.5B | ~6 GB |
| `sdadas/stella-pl-retrieval-mini-8k` | 61.29 | 435M | ~2 GB |
| `sdadas/mmlw-retrieval-roberta-large-v2` | 60.71 | 435M | ~1.5 GB |

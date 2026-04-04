# UODO RAG — Wyszukiwarka Decyzji z Odpowiedziami AI

System RAG (Retrieval-Augmented Generation) do przeszukiwania decyzji Prezesa Urzędu Ochrony Danych Osobowych, ustawy o ochronie danych osobowych oraz rozporządzenia RODO. Zaprojektowany jako serwis API-first z osadzalnym widgetem frontendowym.

## Architektura

```
Internet
  ↓
nginx (port 44306)
  ├── /          → frontend React (SPA)
  ├── /api/      → FastAPI :8503
  └── /developer → dokumentacja API

FastAPI backend ←→ OpenSearch 2.18
                    (kNN + BM25 + RRF + graf cytowań)
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
- GPU z min. 6 GB VRAM (rekomendowane do indeksowania), lub CPU

---

## Instalacja lokalna

### 1. Klonowanie i środowisko

```bash
git clone https://github.com/kwasiucionek/uodo-rag.git
cd uodo-rag

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install fastapi "uvicorn[standard]"
```

### 2. Zmienne środowiskowe

Utwórz plik `.env` w katalogu głównym (wzorzec w `.env.example`):

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

# CORS
ALLOWED_ORIGINS=http://localhost:5173

# Admin (opcjonalny klucz dla /api/admin/update)
ADMIN_KEY=

# Domyślny provider i model LLM
DEFAULT_LLM_PROVIDER=Ollama
DEFAULT_LLM_MODEL=mistral-large-3:675b-cloud
```

### 3. OpenSearch

```bash
docker compose up -d

# Weryfikacja (poczekaj ~30 sekund)
curl http://localhost:9200
```

> **Linux:** Jeśli OpenSearch nie startuje:
> ```bash
> sudo sysctl -w vm.max_map_count=262144
> ```

### 4. Przygotowanie danych

#### 4a. Scrapowanie decyzji UODO

```bash
# Pobierz wszystkie decyzje (~560, kilka godzin)
python tools/uodo_scraper.py --output tools/uodo_decisions.jsonl

# Test (3 decyzje)
python tools/uodo_scraper.py --test
```

Scraper pobiera XML i automatycznie wyciąga:
- Treść podzieloną na sekcje (`xType="sect"`) — Sentencja, Stan faktyczny, sekcje uzasadnienia
- Referencje z tagów `<xLexLink xRef="...">` z pełnym URN (ISAP, EUR-Lex, NSA, MS Portal)
- Metadane: taksonomia, status, daty, encje

#### 4b. Indeksowanie

```bash
python tools/opensearch_indexer.py --mode all \
  --jsonl   tools/uodo_decisions.jsonl \
  --md-act  tools/D20191781L.md \
  --md-rodo tools/rodo_2016_679_pl.md

# Jeśli OOM na GPU:
python tools/opensearch_indexer.py --mode all \
  --jsonl tools/uodo_decisions.jsonl \
  --md-act tools/D20191781L.md \
  --md-rodo tools/rodo_2016_679_pl.md \
  --batch-size 8

# Tylko CPU:
CUDA_VISIBLE_DEVICES="" python tools/opensearch_indexer.py --mode all ...
```

Czas: ~20–40 min na GPU, ~2–4 h na CPU.

| Flaga | Opis |
|---|---|
| `--mode decisions` | Tylko decyzje UODO |
| `--mode act` | Tylko ustawa u.o.d.o. |
| `--mode rodo` | Tylko RODO |
| `--mode all` | Wszystkie typy |
| `--rebuild` | Usuń i przeindeksuj od nowa |

---

## Uruchomienie

### Backend

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

```bash
curl http://localhost:8000/health
# {"status":"ok","opensearch":"ok","embedder":"ok"}
```

### Frontend

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
# → http://localhost:5173
```

---

## Funkcje UI

- **Wyszukiwanie hybrydowe** — BM25 + kNN + graf cytowań, wyniki pojawiają się natychmiast (równolegle ze streamingiem AI)
- **Autouzupełnianie** — tagi i sygnatury z debouncem 300ms
- **Sidebar z filtrami** — status, rok, sektor, rodzaj decyzji, środek naprawczy
- **Zakładki** — Decyzje UODO / Ustawa u.o.d.o. / RODO z licznikami wyników
- **Odpowiedź AI** — streaming SSE, renderowanie Markdown + tabele (remark-gfm)
- **Widok dokumentu** — sekcje z nawigacją ↑↓, referencje klikalne (ISAP, EUR-Lex, NSA, MS Portal, TSUE)
- **Paginacja** — 10 decyzji/stronę, po stronie klienta

---

## Widget osadzalny

```bash
cd frontend
VITE_API_URL=https://rag.uodo.gov.pl npm run build -- --mode widget
# → frontend/dist/widget.iife.js
```

```html
<!-- Web Component -->
<script src="widget.iife.js"></script>
<uodo-rag-widget api-url="https://rag.uodo.gov.pl"></uodo-rag-widget>

<!-- Ręczna inicjalizacja -->
<div id="uodo-rag"></div>
<script src="widget.iife.js"></script>
<script>UodoRag.mount('#uodo-rag', { useLLM: true })</script>
```

---

## Struktura projektu

```
.
├── api.py                     # FastAPI — REST + SSE + dokumentacja
├── config.py                  # Stałe i zmienne środowiskowe
├── opensearch_client.py       # Klient OpenSearch, schemat indeksu, query builders
├── search.py                  # Wyszukiwanie hybrydowe, graf, tagi, taksonomia
├── llm.py                     # LLM streaming i dekompozycja (Ollama / Groq)
├── models.py                  # Modele Pydantic + szablony Jinja2
├── ui.py                      # Budowanie kontekstu LLM
├── main.py                    # Aplikacja Streamlit (narzędzie deweloperskie)
├── requirements.txt
├── docker-compose.yml         # OpenSearch single-node (lokalny dev)
├── docs/
│   └── index.html             # Dokumentacja API dla developerów
├── deploy/
│   ├── deploy.sh              # Pierwsze wdrożenie (git clone + konfiguracja)
│   ├── update.sh              # Aktualizacja (git pull + restart)
│   ├── nginx-uodo-rag.conf    # Konfiguracja nginx (port 44306)
│   ├── uodo-rag.service       # Systemd service dla FastAPI
│   ├── uodo-update.service    # Systemd service dla delta-update
│   ├── uodo-update.timer      # Systemd timer (codziennie o 6:00)
│   └── docker-compose.yml     # OpenSearch produkcja (2GB heap)
├── frontend/
│   ├── package.json
│   ├── vite.config.ts         # Dwa tryby: standalone SPA i widget IIFE
│   └── src/
│       ├── api.ts             # Typowany klient API
│       ├── hooks/
│       │   ├── useSearch.ts   # Stan wyszukiwania + streaming LLM
│       │   └── useSuggest.ts  # Autouzupełnianie z debouncem
│       ├── UodoRagWidget.tsx  # Główny komponent (filtry, zakładki, paginacja)
│       ├── SearchInput.tsx    # Pole wyszukiwania z dropdownem sugestii
│       ├── FiltersPanel.tsx   # Sidebar z filtrami taksonomii
│       ├── DocumentView.tsx   # Widok pełnej decyzji z sekcjami i referencjami
│       ├── main.tsx           # Entry point — standalone SPA
│       ├── widget.tsx         # Entry point — osadzalny widget + Web Component
│       └── styles/widget.css  # Style (UODO design system)
└── tools/
    ├── uodo_scraper.py        # Scraper XML z portalu UODO
    ├── opensearch_indexer.py  # Indeksowanie (granularność: sekcja XML)
    ├── update_decisions.py    # Delta-aktualizacja nowych decyzji
    ├── enrich_act_keywords.py # Tagi dla artykułów przez LLM
    ├── eval.py                # Ewaluacja jakości (10 złotych pytań)
    ├── D20191781L.md          # Tekst ustawy u.o.d.o.
    └── rodo_2016_679_pl.md    # Tekst RODO
```

---

## API

Pełna dokumentacja: `http://localhost:8000/developer`  
Swagger UI: `http://localhost:8000/docs`

| Endpoint | Opis |
|---|---|
| `POST /api/search` | Wyszukiwanie hybrydowe (docs + tagi) |
| `POST /api/answer/stream` | Streaming odpowiedzi LLM (SSE) |
| `POST /api/decompose` | Dekompozycja zapytania przez LLM |
| `GET /api/suggest` | Autouzupełnianie (tagi + sygnatury) |
| `GET /api/document` | Pełna decyzja (wszystkie sekcje + referencje z URN) |
| `GET /api/signature/{sig}` | Metadane decyzji (chunk 0) |
| `GET /api/tags` | Wszystkie tagi |
| `GET /api/taxonomy` | Opcje filtrów taksonomii |
| `GET /api/stats` | Statystyki kolekcji i grafu |
| `POST /api/admin/update` | Delta-aktualizacja decyzji |
| `GET /api/admin/update/status` | Status ostatniej aktualizacji |
| `GET /health` | Health check |

---

## Deploy na Mikrus VPS

```bash
# Pierwsze wdrożenie (lokalnie)
bash deploy/deploy.sh

# Aktualizacja kodu
bash deploy/update.sh

# Aktualizacja kodu + przebudowa frontendu
bash deploy/update.sh --frontend
```

Po pierwszym deployu — indeksowanie na serwerze:

```bash
ssh root@steve141.mikrus.xyz -p 10141
cd /home/kwasiucionek/uodo_rag
source .venv/bin/activate
CUDA_VISIBLE_DEVICES="" python tools/opensearch_indexer.py --mode all \
  --jsonl tools/uodo_decisions.jsonl \
  --md-act tools/D20191781L.md \
  --md-rodo tools/rodo_2016_679_pl.md
```

Automatyczna aktualizacja nowych decyzji (systemd timer — codziennie o 6:00):

```bash
systemctl status uodo-update.timer
journalctl -u uodo-update --since today
```

---

## Zmiana modelu embeddingowego

Po zmianie `EMBED_MODEL` w `.env` obowiązkowe przeindeksowanie:

```bash
curl -X DELETE http://localhost:9200/uodo_decisions
python tools/opensearch_indexer.py --mode all ...
```

| Model | NDCG@10 (PIRB) | Params | VRAM |
|---|---|---|---|
| `sdadas/stella-pl-retrieval-8k` *(domyślny)* | 62.69 | 1.5B | ~6 GB |
| `sdadas/stella-pl-retrieval-mini-8k` | 61.29 | 435M | ~2 GB |
| `sdadas/mmlw-retrieval-roberta-large-v2` | 60.71 | 435M | ~1.5 GB |

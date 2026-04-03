# UODO RAG — Szczegółowy opis działania aplikacji

## Spis treści

1. [Cel i kontekst](#1-cel-i-kontekst)
2. [Architektura ogólna](#2-architektura-ogólna)
3. [Baza wiedzy i indeksowanie](#3-baza-wiedzy-i-indeksowanie)
4. [Przepływ danych — od zapytania do odpowiedzi](#4-przepływ-danych--od-zapytania-do-odpowiedzi)
5. [Moduł wyszukiwania (search.py)](#5-moduł-wyszukiwania-searchpy)
6. [Graf powiązań](#6-graf-powiązań)
7. [Moduł LLM (llm.py)](#7-moduł-llm-llmpy)
8. [Budowanie kontekstu (ui.py → build_context)](#8-budowanie-kontekstu-uipy--build_context)
9. [Backend API (api.py)](#9-backend-api-apipy)
10. [Frontend React](#10-frontend-react)
11. [Konfiguracja i modele danych](#11-konfiguracja-i-modele-danych)
12. [Narzędzia pomocnicze (tools/)](#12-narzędzia-pomocnicze-tools)
13. [Kluczowe decyzje projektowe](#13-kluczowe-decyzje-projektowe)

---

## 1. Cel i kontekst

### Co to jest RAG?

Aplikacja jest systemem **RAG (Retrieval-Augmented Generation)** — dosłownie "Generowanie wspomagane wyszukiwaniem". Żeby zrozumieć po co to istnieje, warto najpierw zrozumieć problem z samymi modelami językowymi.

Modele AI jak GPT czy Claude są trenowane na ogromnych zbiorach tekstu z internetu. Wiedzą dużo o świecie, ale ich wiedza ma dwie fundamentalne wady:
1. **Jest zamrożona w czasie** — model nie wie co wydarzyło się po dacie zakończenia treningu
2. **Może być nieprecyzyjna lub zmyślona** — modele potrafią generować przekonująco brzmiące, ale fałszywe informacje (tzw. halucynacje)

RAG rozwiązuje oba problemy: zamiast polegać na wiedzy modelu, **najpierw wyszukujemy odpowiednie dokumenty** z naszej własnej bazy, a potem podajemy je modelowi jako materiał źródłowy. Model odpowiada wyłącznie na podstawie tego co dostał — jak prawnik który cytuje konkretne przepisy, a nie swoją ogólną wiedzę o prawie.

### Problem który rozwiązuje

Baza decyzji Prezesa UODO liczy ponad 560 orzeczeń administracyjnych. Każde orzeczenie to kilka do kilkudziesięciu stron tekstu prawniczego. Analityk szukający precedensów dla konkretnego problemu (np. przetwarzania danych biometrycznych przez pracodawcę) musiałby ręcznie przejrzeć setki dokumentów.

Tradycyjne wyszukiwanie pełnotekstowe (jak w Google) szuka dokładnych słów — nie rozumie sensu pytania. Zapytanie "jak firma powinna postąpić gdy pracownik odmawia zgody na monitoring" nie znajdzie decyzji opisującej "brak podstawy prawnej przetwarzania w stosunku pracy", choć semantycznie mówią o tym samym.

Aplikacja łączy trzy techniki: wyszukiwanie po tagach (precyzyjne), wyszukiwanie semantyczne (rozumie sens) i syntezę odpowiedzi przez LLM (formułuje czytelną odpowiedź z odniesieniami do źródeł).

### Trzy źródła wiedzy

- **Decyzje UODO** — ~560 orzeczeń administracyjnych Prezesa Urzędu Ochrony Danych Osobowych, pobieranych z portalu orzeczenia.uodo.gov.pl
- **Ustawa o ochronie danych osobowych (u.o.d.o.)** — artykuły 1–108, Dz.U. 2019 poz. 1781
- **RODO** — 99 artykułów i 173 motywy preambuły rozporządzenia (UE) 2016/679

---

## 2. Architektura ogólna

Aplikacja składa się z backendu FastAPI, frontendu React i bazy OpenSearch:

```
┌─────────────────────────────────────────────────┐
│                  nginx :44306                   │
│  /         → frontend/dist (React SPA)          │
│  /api/*    → FastAPI :8503                      │
│  /developer → dokumentacja API                  │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                   api.py                        │
│              (FastAPI backend)                  │
│  POST /api/search        ← wyszukiwanie         │
│  POST /api/answer/stream ← streaming LLM (SSE) │
│  GET  /api/suggest       ← autouzupełnianie     │
│  GET  /api/document      ← pełna decyzja        │
│  POST /api/admin/update  ← delta-aktualizacja   │
└──────┬──────────────┬────────────────────────────┘
       │              │
       ▼              ▼
  search.py        llm.py
  (OpenSearch,     (Ollama Cloud /
  graf, tagi)      Groq, streaming)
       │
       ▼
  OpenSearch 2.18
  (kNN + BM25 + RRF)
  Docker :9200
```

**Zewnętrzne zależności:**

- **OpenSearch 2.18** — wektorowa baza danych z wbudowanym BM25. Przechowuje embeddingi (dim=1024) i metadane. Działa jako kontener Docker, dostępny tylko lokalnie (127.0.0.1:9200).
- **SentenceTransformers** — biblioteka do generowania embeddingów. Używa modelu `sdadas/stella-pl-retrieval-8k` (1.5B parametrów, NDCG@10=62.69 na PIRB).
- **NetworkX** — biblioteka do grafu cytowań między decyzjami. Graf jest budowany jednorazowo ze wszystkich `related_uodo_rulings` w indeksie i zapisywany do pliku `.pkl`.
- **Ollama** — lokalny daemon LLM. Modele cloud (sufiks `:cloud`) łączą się z Ollama.com przez klucz API w nagłówku `Authorization`.
- **Groq** — alternatywne zewnętrzne API dla modeli LLM.
- **FastAPI** — framework webowy dla backendu. Obsługuje REST i SSE (Server-Sent Events) dla streamingu odpowiedzi LLM.
- **React + Vite** — frontend. Budowany jako SPA (standalone) lub IIFE (widget osadzalny na zewnętrznych stronach).

---

## 3. Baza wiedzy i indeksowanie

### 3.1 Co to jest embedding i dlaczego jest potrzebny?

Komputery nie rozumieją tekstu — operują na liczbach. **Embedding** to sposób zamiany tekstu na listę liczb (wektor) w taki sposób, że teksty o podobnym znaczeniu mają podobne wektory, a teksty o różnym znaczeniu — różne.

Przykład: zdania "przetwarzanie danych osobowych bez zgody" i "brak podstawy prawnej przetwarzania" są napisane różnymi słowami, ale opisują to samo zjawisko prawne. Model embeddingowy umieszcza je blisko siebie w przestrzeni matematycznej. Zdanie "przepis na bigos" trafia daleko od obu.

Stella-pl-retrieval-8k wymaga **różnych prefiksów** dla zapytań i dokumentów:
- Dokumenty indeksowane są **bez prefiksu**
- Zapytania embedowane są **z prefiksem** `"Instruct: Given a web search query, retrieve relevant passages that answer the query.\nQuery: "`

### 3.2 Granularność indeksowania — sekcje XML

Decyzje UODO są indeksowane **na poziomie sekcji** (nie całego dokumentu). Każda decyzja ma typowo 3–5 sekcji:

| Sekcja | ID | Przykładowa długość |
|--------|----|-------------------|
| Sentencja | B1 | ~1500 znaków |
| Uzasadnienie: Stan faktyczny | B2:intro | ~4000 znaków |
| Uzasadnienie: I. [tytuł sekcji] | B2:C1:E1 | ~5000 znaków |
| Uzasadnienie: II. [tytuł sekcji] | B2:C1:E2 | ~11000 znaków |
| Uzasadnienie: III. [tytuł sekcji] | B2:C1:E3 | ~3500 znaków |

Każda sekcja to osobny dokument w OpenSearch z własnym embeddingiem. Metadane (keywords, status, terms, refs) są wspólne dla wszystkich sekcji tej samej decyzji. Pola `chunk_index` i `chunk_total` pozwalają zrekonstruować kolejność sekcji.

Zaletą granularnego indeksowania jest to, że wyszukiwanie semantyczne trafia do konkretnej, istotnej sekcji zamiast do "całej decyzji". Jeśli pytamy o podstawę prawną — system znajdzie sekcję uzasadnienia, a nie sentencję.

### 3.3 Struktura indeksu OpenSearch

Wszystkie dokumenty trafiają do jednego indeksu `uodo_decisions`. Każdy dokument ma:

- **Pole `embedding`** — wektor kNN (dim=1024, metoda HNSW, silnik Lucene)
- **Pole `content_text`** — pełny tekst sekcji (do BM25)
- **Metadane** — filtrowanie i wyświetlanie

Kluczowe pola:

| Pole | Typ | Przykład |
|------|-----|---------|
| `doc_type` | keyword | `uodo_decision` |
| `signature` | keyword | `DKN.5131.5.2024` |
| `chunk_index` | integer | `0` (sentencja) |
| `chunk_total` | integer | `5` |
| `section_title` | text | `Uzasadnienie: II. Ocena legalności` |
| `keywords` | keyword[] | `["dane genetyczne", "dane szczególnych kategorii"]` |
| `status` | keyword | `prawomocna` |
| `year` | integer | `2024` |
| `term_decision_type` | keyword[] | `["nakaz"]` |
| `term_violation_type` | keyword[] | `["brak podstawy prawnej przetwarzania"]` |
| `term_sector` | keyword[] | `["Zdrowie"]` |
| `related_uodo_rulings` | text[] | `["DKN.5131.9.2021"]` |
| `related_acts` | text[] | `["Dz.U. 2019 poz. 1781"]` |
| `refs_full` | object[] | `[{"urn": "urn:ndoc:court:pl:sa:...", "signature": "II SA/Wa 123/22", "category": "court_ruling"}]` |

### 3.4 Indeksowanie decyzji UODO

**Etap 1 — Scraping:** `uodo_scraper.py` pobiera decyzje przez REST API portalu. Treść pobierana jest jako XML (`000_pl.xml`) i parsowana przez `_extract_sections()`. Referencje wyciągane z tagów `<xLexLink xRef="urn:ndoc:...">` — URN pozwala precyzyjnie określić system docelowy (ISAP, EUR-Lex, NSA, MS Portal, TSUE).

**Etap 2 — Indeksowanie:** `opensearch_indexer.py` dla każdej sekcji buduje tekst embeddingu — nagłówek z sygnaturą, tytułem i słowami kluczowymi, po którym następuje treść sekcji. Embeddingowanie w batchach przez GPU lub CPU.

### 3.5 Referencje i URN

System `ref-publicators.json` (z portalu orzeczenia.uodo.gov.pl) mapuje prefiksy URN na systemy zewnętrzne:

| URN prefix | System | URL |
|------------|--------|-----|
| `urn:ndoc:court:pl:sa:` | NSA (CBOSA) | orzeczenia.nsa.gov.pl |
| `urn:ndoc:court:pl:sp:` | MS Portal orzeczeń | orzeczenia.ms.gov.pl |
| `urn:ndoc:court:pl:sn:` | Sąd Najwyższy | sn.pl |
| `urn:ndoc:court:eu:tsue:` | TSUE (Curia) | curia.europa.eu |
| `urn:ndoc:gov:pl:uodo:` | Decyzje UODO | widget wewnętrzny |
| `urn:ndoc:pro:pl:` | ISAP | isap.sejm.gov.pl |
| `urn:ndoc:pro:eu:` | EUR-Lex | eur-lex.europa.eu |

---

## 4. Przepływ danych — od zapytania do odpowiedzi

```
Użytkownik wpisuje zapytanie
         │
         ▼
[React: SearchInput] → debounce 300ms → GET /api/suggest
    → wyświetl dropdown z tagami i sygnaturami
         │
         ▼ (Enter lub kliknięcie Szukaj)
[React: useSearch.search()]
         │
         ├─── POST /api/decompose (jeśli >3 słowa)
         │    └── LLM analizuje zapytanie → enriched_query, keywords
         │
         ├─── POST /api/search
         │    ├── hybrid_search() w search.py
         │    │   ├── 1. Frazy 2-wyrazowe → exact tag match
         │    │   ├── 2. Tagi LLM (fallback)
         │    │   ├── 3. BM25 + kNN (last resort)
         │    │   └── 4. Graf cytowań (rozszerzenie)
         │    └── → lista dokumentów + tagi
         │
         └─── POST /api/answer/stream (równolegle z wyświetleniem wyników)
              └── SSE: token po tokenie → answer w UI
```

Kluczowa właściwość: **wyniki wyszukiwania pojawiają się natychmiast**, bez czekania na odpowiedź LLM. Streaming LLM startuje równolegle po zwróceniu wyników.

---

## 5. Moduł wyszukiwania (search.py)

### 5.1 Architektura bez Streamlit

`search.py` nie ma żadnych zależności od Streamlit. Zasoby (embedder, graf) są cachowane jako singletony modułowe:

- `_injected_embedder` — ustawiany przez FastAPI lifespan przez `set_embedder()`
- `_loaded_embedder` — leniwe ładowanie przy pierwszym wywołaniu (fallback)
- `_graph_cache` — graf cytowań (ładowany z `.pkl` lub budowany ze scratch)

Dane (tagi, taksonomia, statystyki) cachowane przez dekorator `@_ttl_cache(seconds=3600)` — prosty TTL cache oparty na `time.monotonic()`.

### 5.2 Czterostopniowa strategia wyszukiwania decyzji

**Krok 1 — Explicit keyword z UI.** Jeśli użytkownik wybrał konkretny tag z filtrów, szukamy wszystkich decyzji z tym tagiem przez `keyword_exact_search()`. Paginacja po tagach — jeśli tag ma >50 wyników, jest pomijany (zbyt ogólny).

**Krok 2 — Frazy 2-wyrazowe.** Zapytanie "dane genetyczne monitoring" generuje frazy "dane genetyczne" i "genetyczne monitoring". Pierwsza pasuje do tagu w bazie i zwraca 26 decyzji — dokładna, deterministyczna, bez LLM.

**Krok 3 — Tagi LLM.** Jeśli kroki 1-2 nie znalazły wyników, `extract_tags_with_llm()` wywołuje LLM z listą wszystkich tagów i zapytaniem. LLM wybiera pasujące tagi (max 8) i może dodać nowe (max 4, z prefiksem `[NOWY]`).

**Krok 4 — Hybrid BM25 + kNN.** Jeśli wyników jest <5, `hybrid_search_os()` wykonuje równoległe zapytanie BM25 i kNN z łączeniem przez RRF (lub fallback do kNN jeśli RRF niedostępny).

### 5.3 Grupowanie chunków

Po wyszukiwaniu chunki tej samej decyzji są grupowane przez `_group_decision_chunks()` — do wyników trafia jeden dokument per sygnatura, z najwyższym score (best matching section). Treść w `content_text` to tekst najlepiej pasującej sekcji, a `section_title` wskazuje która to sekcja.

---

## 6. Graf powiązań

Graf cytowań `G` (NetworkX DiGraph) ma węzły dla sygnatur decyzji UODO, aktów prawnych i aktów UE, oraz krawędzie `CITES_UODO`, `CITES_ACT`, `CITES_EU`.

Budowanie: scrollowanie przez cały indeks (tylko `chunk_index=0` żeby nie duplikować krawędzi), zapis do `uodo_graph.pkl`. Przy następnym starcie ładowany z pliku.

Rozszerzenie wyników (`graph_expand()`): dla znalezionych decyzji (seed) przeszukuje graf w głąb do 2 stopni. Decyzje cytowane przez seed (successor) dostają score 0.6 × decay, decyzje cytujące seed (predecessor) dostają 0.5 × decay. Decay = 0.65 za każdy kolejny stopień głębokości.

---

## 7. Moduł LLM (llm.py)

### 7.1 Providers

**Ollama** — daemon działający lokalnie na porcie 11434. Modele cloud (sufiks `:cloud`) są wirtualnymi modelami które Ollama uruchamia przez zewnętrzne API z kluczem w nagłówku `Authorization: Bearer <OLLAMA_CLOUD_API_KEY>`.

**Groq** — zewnętrzne API, dostęp przez bibliotekę `groq`. Szybsze od modeli cloud Ollama, dobre do dekompozycji zapytań (krótkie wywołania JSON).

### 7.2 Streaming SSE

`call_llm_stream()` to generator zwracający tokeny. FastAPI opakowuje go w `StreamingResponse` z `media_type="text/event-stream"`. Każdy token to zdarzenie SSE:

```
data: {"type": "token", "content": "Na podstawie"}
data: {"type": "token", "content": " decyzji..."}
data: {"type": "done"}
```

Nginx wymaga `proxy_buffering off` i `proxy_set_header Connection ''` dla poprawnego działania SSE.

### 7.3 Dekompozycja zapytania (Reasoning Step)

`decompose_query()` wywołuje LLM przed wyszukiwaniem dla zapytań >3 słów. LLM zwraca JSON z:
- `search_keywords` — synonimy i pojęcia prawne (max 5)
- `enriched_query` — rozszerzone zapytanie używane do kNN
- `gdpr_articles_hint` — sugerowane artykuły RODO
- `year_from_hint` / `year_to_hint` — sugerowany zakres lat

Dla krótkich zapytań dekompozycja jest pomijana (deterministyczny fallback).

### 7.4 Parametry LLM

`_get_llm_params()` zwraca provider, model i klucz API. Jeśli `model` jest pustym stringiem (co zdarza się gdy `st.session_state` jest pusty przy uruchomieniu bez Streamlit), fallback do `DEFAULT_OLLAMA_MODEL` z konfiguracji.

---

## 8. Budowanie kontekstu (ui.py → build_context)

### 8.1 Sortowanie dokumentów

Przed budowaniem kontekstu dokumenty sortowane są według priorytetu (`CONTEXT_TYPE_ORDER`): decyzje UODO pierwsze, RODO ostatnie. W ramach tego samego typu — malejąco po score wyszukiwania.

Duże modele językowe mają tendencję do "zapominania" informacji z środka długiego kontekstu ("lost in the middle"). Umieszczenie decyzji UODO na początku gwarantuje że model je przetworzy przed osiągnięciem limitu tokenów.

### 8.2 Szablony Jinja2

Każdy typ dokumentu ma własny szablon z wyraźnymi etykietami. LLM widzi `DECYZJA UODO`, `USTAWA`, `RODO` — nie musi sam kategoryzować dokumentów. Szablony zawierają sygnaturę, datę, status, tagi, powołane akty i fragment treści.

### 8.3 Ekstrakcja fragmentów i limit znaków

Decyzje UODO mogą mieć do 50 000 znaków, ale do kontekstu trafia max 2000 znaków — algorytm przesuwa okno o 150 znaków i szuka fragmentu z najwyższą gęstością słów kluczowych z zapytania.

Kontekst jest budowany do limitu 18 000 znaków. Gdy kolejny blok przekroczyłby limit, pętla się przerywa.

---

## 9. Backend API (api.py)

### 9.1 FastAPI i lifespan

`api.py` używa `@asynccontextmanager async def lifespan(app)` zamiast przestarzałych `on_startup`/`on_shutdown`. Przy starcie:
1. Ładuje model embeddingowy SentenceTransformer
2. Tworzy klienta OpenSearch
3. Inicjalizuje pipeline RRF (lub loguje fallback)
4. Wywołuje `set_embedder()` i `set_opensearch()` — wstrzykuje zasoby do `search.py`

### 9.2 Dependency Injection

`SearchService` i `LLMService` są tworzone per-request przez `Depends()`. `SearchService` korzysta z zasobów wstrzykniętych przy starcie do `search.py` (nie przechowuje własnych referencji).

### 9.3 Endpointy

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/search` | POST | Wyszukiwanie hybrydowe z filtrami |
| `/api/answer/stream` | POST | Streaming SSE odpowiedzi LLM |
| `/api/decompose` | POST | Dekompozycja zapytania przez LLM |
| `/api/suggest` | GET | Autouzupełnianie (tagi regex + sygnatury prefix) |
| `/api/document` | GET | Pełna decyzja — wszystkie sekcje + refs_full z URN |
| `/api/signature/{sig}` | GET | Metadane decyzji (chunk 0) |
| `/api/tags` | GET | Wszystkie tagi (cache TTL 1h) |
| `/api/taxonomy` | GET | Opcje filtrów taksonomii |
| `/api/stats` | GET | Statystyki kolekcji i grafu |
| `/api/admin/update` | POST | Delta-aktualizacja decyzji (wymaga ADMIN_KEY) |
| `/api/admin/update/status` | GET | Stan ostatniej aktualizacji |
| `/health` | GET | Health check |
| `/developer` | GET | Dokumentacja HTML dla developerów |

### 9.4 Autouzupełnianie (/api/suggest)

Dwie równoległe strategie:
- **Tagi** — agregacja `terms` z regex `.*q.*` na polu `keywords`, preferuje prefix match
- **Sygnatury** — `prefix` query na polu `signature`, tylko `chunk_index=0`, sortowane malejąco po roku

---

## 10. Frontend React

### 10.1 Dwa tryby budowania

**Standalone SPA** (`npm run build`) — pełna aplikacja pod własnym URL. Entry point: `main.tsx`.

**Widget IIFE** (`npm run build -- --mode widget`) — jeden plik JS osadzalny na dowolnej stronie. React bundlowany razem (brak zewnętrznych zależności). Entry point: `widget.tsx` eksportuje `UodoRag.mount()` i rejestruje Web Component `<uodo-rag-widget>`.

### 10.2 Zarządzanie stanem (useSearch)

`useSearch` hook zarządza całym cyklem wyszukiwania:
1. Dekompozycja zapytania (opcjonalna, dla >3 słów)
2. `POST /api/search` z `top_k=50` — wszystkie wyniki trafiają do `allDocs`
3. Podział `allDocs` na `decisions`, `actDocs`, `gdprDocs` po stronie klienta
4. Streaming LLM (pierwsze 8 dokumentów jako kontekst)

Paginacja jest po stronie klienta — `decisions.slice()` bez dodatkowych wywołań API.

### 10.3 Zakładki i karty

Wyniki podzielone na trzy zakładki z licznikami: **Decyzje UODO** (paginowane co 10), **Ustawa u.o.d.o.** (wszystkie, zwykle 3–5), **RODO** (wszystkie).

Karta artykułu (`ArticleCard`) pokazuje skrót tekstu z przyciskiem "Pokaż pełny tekst" (rozwijanie inline) i link do źródła (ISAP lub EUR-Lex).

### 10.4 Widok dokumentu (DocumentView)

Otwiera się w nowej karcie (`window.open('/?doc=SYG', '_blank')`). `main.tsx` sprawdza parametr `?doc=` i renderuje `DocumentView` zamiast `UodoRagWidget`.

Widok pobiera `GET /api/document?signature=...` — wszystkie sekcje + `refs_full` z URN. Nawigacja między sekcjami przez klikalne przyciski w sidebar lub strzałki ← → na klawiaturze.

Referencje (`RefsSection`) grupuje `refs_full` po kategorii i generuje linki przez `urnToUrl()` na podstawie URN prefix (zgodnie z `ref-publicators.json` portalu UODO).

### 10.5 Design system

CSS oparty na zmiennych z `root.css` portalu orzeczenia.uodo.gov.pl. Klasy kart (`doc-list-item`, `ui-result-tags`, status badges) identyczne jak w oryginalnym portalu — widget wygląda jak natywna część serwisu.

---

## 11. Konfiguracja i modele danych

### 11.1 config.py

```python
MAX_ACT_DOCS         = 10   # max artykułów u.o.d.o. w wynikach
MAX_GDPR_DOCS        = 10   # max artykułów RODO w wynikach
TOP_K                = 8    # domyślne top_k dla semantic search
GRAPH_DEPTH          = 2    # głębokość przeszukiwania grafu
_MAX_RESULTS_PER_TAG = 50   # max decyzji per tag (zbyt ogólne tagi odrzucamy)
```

`QUERY_STOPWORDS` — zbiór polskich słów funkcyjnych pomijanych przy ekstrakcji fraz. Bez nich zapytanie "w jakie dane genetyczne są przetwarzane" generowałoby frazy "jakie dane", "dane genetyczne" — stopwords zostawia tylko "dane genetyczne".

### 11.2 models.py — modele Pydantic

`QueryDecomposition` — wynik dekompozycji zapytania przez LLM. `AgentMemory`/`MemoryEntry` — pamięć epizodyczna sesji (używana w wersji Streamlit). Szablony Jinja2 kompilowane raz przy imporcie i współdzielone przez cały czas życia procesu.

---

## 12. Narzędzia pomocnicze (tools/)

### uodo_scraper.py

Pobiera decyzje przez REST API portalu. Treść w formacie XML parsowana przez `_extract_sections()`:

```
xBlock → bran (B1, B2)
  B1 → sentencja (chunk 0)
  B2 → passy bezpośrednie → "Stan faktyczny" (chunk 1)
  B2 → chpt → sect (B2:C1:E1, E2, E3...) → osobne chunki
```

Referencje z `<xLexLink xRef="urn:...">` — pełny URN pozwala precyzyjnie wygenerować linki. Metadane z `meta.json`, daty z `dates.json`.

### opensearch_indexer.py

Indeksuje trzy typy dokumentów:
- **Decyzje UODO** — `index_decisions()` — 1 dokument per sekcja
- **Ustawa u.o.d.o.** — `index_act()` — artykuły parsowane z Markdown, chunki do 3000 znaków
- **RODO** — `index_rodo()` — artykuły i motywy z Markdown

### update_decisions.py

Delta-aktualizacja: pobiera datę najnowszej zaindeksowanej decyzji, odejmuje 7 dni bufora, scrapuje tylko nowe decyzje. Po indeksowaniu czyści cache TTL w `search.py` i wymusza przebudowę grafu.

### eval.py

10 złotych pytań z binarnymi kryteriami. Każde pytanie ma 3 funkcje testujące obecność konkretnych słów/sygnatur/artykułów w odpowiedzi LLM. Wynik: `passed/total` zapisywany do `eval_results.json`.

### enrich_act_keywords.py

Dla artykułów u.o.d.o. i RODO wywołuje LLM z treścią artykułu i listą istniejących tagów. LLM wybiera pasujące tagi i aktualizuje dokumenty w OpenSearch przez `client.update()`.

---

## 13. Kluczowe decyzje projektowe

### Dlaczego FastAPI zamiast Streamlit?

Streamlit był odpowiedni dla wewnętrznego prototypu, ale ma fundamentalne ograniczenia dla skali publicznej: rerenderuje całą stronę przy każdej interakcji, nie obsługuje prawdziwego SSE, nie pozwala na osadzanie jako widget na zewnętrznych stronach. FastAPI + React daje pełną kontrolę nad UI, prawdziwy streaming i architekturę API-first którą można osadzić na portalu UODO lub innych serwisach prawnych.

### Dlaczego OpenSearch zamiast Qdrant?

OpenSearch łączy BM25 i kNN w jednym silniku z natywnym RRF (Reciprocal Rank Fusion). Qdrant wymaga osobnych zapytań i ręcznego łączenia wyników. OpenSearch ma też lepszą obsługę aggregacji (używaną do tagów i taksonomii) i jest bardziej dojrzałym rozwiązaniem dla skali produkcyjnej.

### Dlaczego granularne indeksowanie na poziomie sekcji?

Cała decyzja może mieć 30+ stron. Wyszukiwanie semantyczne na tak długim tekście jest mniej precyzyjne — embedding "rozmywa" semantykę. Sekcja (500–5000 znaków) daje znacznie lepsze trafienie. Chunk z najwyższym score trafia do wyników, ale użytkownik może przejrzeć pozostałe sekcje w widoku dokumentu.

### Dlaczego jedna kolekcja OpenSearch?

Wszystkie trzy typy dokumentów w jednym indeksie. Filtrowanie po `doc_type` w jednym zapytaniu jest prostsze niż osobne indeksy z ręcznym łączeniem. Aggregacje (tagi, taksonomia) działają na całym zbiorze bez złączeń.

### Dlaczego osobne kubełki zamiast jednej listy wyników?

Gdyby wszystkie dokumenty były w jednej liście sortowanej po score, artykuły RODO (które mają wysoki score dla pytań o dane genetyczne, bo Art. 9 RODO definiuje je wprost) wypychałyby decyzje UODO poza limit kontekstu. Osobne kubełki z twardymi limitami gwarantują że decyzje UODO zawsze trafiają do kontekstu LLM.

### Dlaczego wyniki pojawiają się przed odpowiedzią AI?

W `useSearch` wyszukiwanie i streaming LLM są uruchamiane równolegle — `POST /api/search` zwraca wyniki natychmiast, a `POST /api/answer/stream` startuje dopiero po otrzymaniu dokumentów. Użytkownik może przeglądać wyniki podczas gdy AI generuje odpowiedź. W starej wersji Streamlit trzeba było czekać na całą odpowiedź LLM.

### Dlaczego referencje przez URN zamiast regex?

Stare podejście (regex na treści decyzji) dawało sygnatury bez informacji o systemie docelowym. URN z tagów `<xLexLink>` zawiera precyzyjną informację: `urn:ndoc:court:pl:sa:` to NSA, `urn:ndoc:court:pl:sp:` to sądy powszechne. Dzięki temu linki w widoku dokumentu trafiają do właściwego systemu (NSA vs MS Portal vs TSUE).

"""
UODO RAG — FastAPI backend

Endpointy:
  POST /api/search               — wyszukiwanie hybrydowe (zwraca docs + tagi)
  POST /api/answer/stream        — streaming odpowiedzi LLM przez SSE
  GET  /api/tags                 — wszystkie tagi (autocomplete)
  GET  /api/taxonomy             — opcje filtrów taksonomii
  GET  /api/stats                — statystyki kolekcji
  GET  /api/signature/{sig}      — pojedyncza decyzja po sygnaturze
  GET  /health                   — health check

Uruchomienie:
  uvicorn api:app --host 0.0.0.0 --port 8000 --workers 2

Zmienne środowiskowe (z .env):
  OPENSEARCH_URL, OPENSEARCH_INDEX, EMBED_MODEL,
  OLLAMA_URL, OLLAMA_CLOUD_API_KEY, GROQ_API_KEY,
  ALLOWED_ORIGINS (comma-separated, default "*")
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ─────────────────────────── KONFIGURACJA ────────────────────────

OPENSEARCH_URL   = os.getenv("OPENSEARCH_URL",   "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "uodo_decisions")
EMBED_MODEL      = os.getenv("EMBED_MODEL",      "sdadas/stella-pl-retrieval-8k")
OLLAMA_URL       = os.getenv("OLLAMA_URL",       "http://localhost:11434")
OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY",     "")

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "ollama")
DEFAULT_LLM_MODEL    = os.getenv("DEFAULT_LLM_MODEL",    "mistral-large-3:675b-cloud")


# ─────────────────────────── LIFESPAN ────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ładuje zasoby raz przy starcie — embedder i klient OpenSearch.
    Zastępuje @st.cache_resource z wersji Streamlit.
    """
    logger.info("Ładowanie modelu embeddingowego: %s", EMBED_MODEL)
    from sentence_transformers import SentenceTransformer
    app.state.embedder = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    logger.info("Model załadowany.")

    from opensearchpy import OpenSearch
    app.state.opensearch = OpenSearch(
        hosts=[OPENSEARCH_URL], timeout=30, max_retries=3, retry_on_timeout=True
    )

    # Inicjalizacja pipeline RRF (jeśli OpenSearch to obsługuje)
    from opensearch_client import _ensure_rrf_pipeline
    _ensure_rrf_pipeline(app.state.opensearch)

    # Wstrzyknij zasoby do search.py (zastępuje @st.cache_resource)
    from search import set_embedder
    from opensearch_client import set_opensearch
    set_embedder(app.state.embedder)
    set_opensearch(app.state.opensearch)

    logger.info("Startup zakończony — API gotowe.")
    yield

    app.state.opensearch.close()
    logger.info("Zasoby zwolnione.")


# ─────────────────────────── APP ─────────────────────────────────

app = FastAPI(
    title="UODO RAG API",
    description="Wyszukiwarka decyzji UODO z odpowiedziami AI",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────── DEPENDENCIES ────────────────────────

def get_search_service(request: Request) -> "SearchService":
    return SearchService(
        embedder=request.app.state.embedder,
        opensearch=request.app.state.opensearch,
    )


def get_llm_service() -> "LLMService":
    return LLMService(
        ollama_url=OLLAMA_URL,
        ollama_api_key=OLLAMA_CLOUD_API_KEY,
        groq_api_key=GROQ_API_KEY,
    )


# ─────────────────────────── MODELE ──────────────────────────────

class FiltersModel(BaseModel):
    status:                  str | None = None
    keyword:                 str | None = None
    doc_types:               list[str]  = Field(default_factory=list)
    year_from:               int | None = None
    year_to:                 int | None = None
    term_decision_type:      list[str]  = Field(default_factory=list)
    term_violation_type:     list[str]  = Field(default_factory=list)
    term_legal_basis:        list[str]  = Field(default_factory=list)
    term_corrective_measure: list[str]  = Field(default_factory=list)
    term_sector:             list[str]  = Field(default_factory=list)


class SearchRequest(BaseModel):
    query:        str
    search_query: str | None = None   # wzbogacone przez LLM
    filters:      FiltersModel = Field(default_factory=FiltersModel)
    use_graph:    bool = True
    top_k:        int  = Field(default=8, ge=1, le=50)


class DocumentModel(BaseModel):
    """Reprezentacja dokumentu zwracanego przez API."""
    doc_id:        str | None = None
    doc_type:      str
    signature:     str | None = None
    title:         str | None = None
    title_full:    str | None = None
    status:        str | None = None
    year:          int | None = None
    content_text:  str | None = None
    section_title: str | None = None
    chunk_index:   int | None = None
    chunk_total:   int | None = None
    article_num:   str | None = None
    keywords:      list[str]  = Field(default_factory=list)
    source_url:    str | None = None
    score:         float      = 0.0
    source:        str | None = None
    graph_relation: str | None = None

    model_config = {"extra": "ignore"}


class SearchResponse(BaseModel):
    docs:        list[DocumentModel]
    tags:        list[str]
    search_time: float
    total:       int


class AnswerRequest(BaseModel):
    query:    str
    docs:     list[DocumentModel]
    provider: str  = DEFAULT_LLM_PROVIDER
    model:    str  = DEFAULT_LLM_MODEL


class DecomposeRequest(BaseModel):
    query:    str
    provider: str = DEFAULT_LLM_PROVIDER
    model:    str = DEFAULT_LLM_MODEL


class DecomposeResponse(BaseModel):
    query_type:             str
    search_keywords:        list[str]
    gdpr_articles_hint:     list[str]
    uodo_act_articles_hint: list[str]
    year_from_hint:         int | None
    year_to_hint:           int | None
    enriched_query:         str
    reasoning:              str


# ─────────────────────────── SEARCH SERVICE ──────────────────────

class SearchService:
    """
    Warstwa wyszukiwania — odpowiednik search.py bez zależności od Streamlit.
    Przyjmuje embedder i klienta OpenSearch przez DI (nie przez @st.cache_resource).
    """

    QUERY_PREFIX = (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query.\nQuery: "
    )

    def __init__(self, embedder, opensearch):
        self.embedder   = embedder
        self.opensearch = opensearch

    def embed_query(self, text: str) -> list[float]:
        return self.embedder.encode(
            self.QUERY_PREFIX + text, normalize_embeddings=True
        ).tolist()

    def embed_document(self, text: str) -> list[float]:
        return self.embedder.encode(text, normalize_embeddings=True).tolist()

    def search(
        self,
        query: str,
        search_query: str | None = None,
        filters: dict[str, Any] | None = None,
        use_graph: bool = True,
        top_k: int = 8,
    ) -> tuple[list[dict], list[str]]:
        from search import hybrid_search
        return hybrid_search(
            query,
            search_query=search_query,
            filters=filters or {},
            use_graph=use_graph,
            top_k=top_k,
        )

    def fetch_by_signature(self, sig: str) -> dict | None:
        from search import fetch_by_signature
        return fetch_by_signature(sig)

    def get_all_tags(self) -> list[str]:
        from search import get_all_tags
        return get_all_tags()

    def get_taxonomy(self) -> dict[str, list[str]]:
        from search import get_taxonomy_options
        return get_taxonomy_options()

    def get_stats(self) -> dict[str, Any]:
        from search import get_collection_stats
        return get_collection_stats()


# ─────────────────────────── LLM SERVICE ─────────────────────────

class LLMService:
    """
    Warstwa LLM — streaming i dekompozycja zapytań.
    Odpowiednik llm.py bez zależności od Streamlit.
    """

    def __init__(
        self,
        ollama_url: str,
        ollama_api_key: str,
        groq_api_key: str,
    ):
        self.ollama_url     = ollama_url
        self.ollama_api_key = ollama_api_key
        self.groq_api_key   = groq_api_key

    def stream(
        self,
        query: str,
        context: str,
        provider: str,
        model: str,
    ):
        """Generator tokenów z LLM."""
        from llm import call_llm_stream
        yield from call_llm_stream(
            query, context,
            provider=provider, model=model,
            api_key=self.groq_api_key if provider == "groq" else "",
        )

    def decompose(self, query: str, provider: str, model: str) -> dict:
        from llm import decompose_query
        result = decompose_query(query, provider=provider, model=model)
        return result.model_dump()


# ─────────────────────────── HELPERS ─────────────────────────────

def _docs_to_models(docs: list[dict]) -> list[DocumentModel]:
    result = []
    for d in docs:
        result.append(DocumentModel(
            doc_id        = d.get("doc_id"),
            doc_type      = d.get("doc_type", ""),
            signature     = d.get("signature"),
            title         = d.get("title"),
            title_full    = d.get("title_full"),
            status        = d.get("status"),
            year          = d.get("year"),
            content_text  = d.get("content_text"),
            section_title = d.get("section_title"),
            chunk_index   = d.get("chunk_index"),
            chunk_total   = d.get("chunk_total"),
            article_num   = d.get("article_num"),
            keywords      = d.get("keywords", []) if isinstance(d.get("keywords"), list) else [],
            source_url    = d.get("source_url"),
            score         = d.get("_score", 0.0),
            source        = d.get("_source"),
            graph_relation = d.get("_graph_relation"),
        ))
    return result


def _build_context_from_docs(docs: list[DocumentModel], query: str) -> str:
    """Buduje kontekst tekstowy dla LLM z listy dokumentów."""
    from ui import build_context
    raw_docs = [d.model_dump(exclude_none=True) for d in docs]
    # Przywróć klucze używane przez build_context
    for d in raw_docs:
        d["_score"]  = d.pop("score", 0.0)
        d["_source"] = d.pop("source", "api")
    return build_context(raw_docs, query)


# ─────────────────────────── ENDPOINTY ───────────────────────────

@app.get("/health")
async def health(request: Request):
    """Health check — sprawdza połączenie z OpenSearch i obecność embeddera."""
    try:
        request.app.state.opensearch.info()
        os_status = "ok"
    except Exception as e:
        os_status = f"error: {e}"

    embedder_ok = hasattr(request.app.state, "embedder")

    return {
        "status":     "ok" if os_status == "ok" and embedder_ok else "degraded",
        "opensearch": os_status,
        "embedder":   "ok" if embedder_ok else "not loaded",
        "index":      OPENSEARCH_INDEX,
    }


@app.post("/api/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    svc: SearchService = Depends(get_search_service),
):
    """
    Wyszukiwanie hybrydowe (kNN + BM25 + graf cytowań).
    Zwraca dokumenty gotowe do wyświetlenia i ewentualnego przekazania do LLM.
    """
    t0 = time.time()

    filters = req.filters.model_dump(exclude_none=True)
    # Usuń puste listy z filtrów
    filters = {k: v for k, v in filters.items() if v}

    docs, tags = svc.search(
        query=req.query,
        search_query=req.search_query,
        filters=filters,
        use_graph=req.use_graph,
        top_k=req.top_k,
    )

    return SearchResponse(
        docs        = _docs_to_models(docs),
        tags        = tags,
        search_time = round(time.time() - t0, 3),
        total       = len(docs),
    )


@app.post("/api/answer/stream")
async def answer_stream(
    req: AnswerRequest,
    llm: LLMService = Depends(get_llm_service),
):
    """
    Streaming odpowiedzi LLM przez Server-Sent Events (SSE).

    Klient odbiera zdarzenia:
      data: {"type": "token", "content": "..."}  — kolejny token
      data: {"type": "done"}                       — koniec
      data: {"type": "error", "message": "..."}   — błąd

    Przykład fetch w TypeScript:
      const resp = await fetch('/api/answer/stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ query, docs, provider, model }),
      });
      const reader = resp.body.getReader();
      // ... czytaj chunks
    """
    context = _build_context_from_docs(req.docs, req.query)

    async def event_generator():
        try:
            for token in llm.stream(req.query, context, req.provider, req.model):
                payload = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            payload = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # wyłącza buforowanie nginx
        },
    )


@app.post("/api/decompose", response_model=DecomposeResponse)
async def decompose(
    req: DecomposeRequest,
    llm: LLMService = Depends(get_llm_service),
):
    """
    Dekompozycja zapytania przez LLM (Reasoning Step).
    Zwraca słowa kluczowe, wskazówki artykułów, enriched query.
    Opcjonalne — wywoływane przez frontend przed wyszukiwaniem dla długich zapytań.
    """
    result = llm.decompose(req.query, req.provider, req.model)
    return DecomposeResponse(**result)


@app.get("/api/tags", response_model=list[str])
async def tags(svc: SearchService = Depends(get_search_service)):
    """Wszystkie unikalne tagi — do autocomplete w filtrach."""
    return svc.get_all_tags()


@app.get("/api/taxonomy")
async def taxonomy(svc: SearchService = Depends(get_search_service)):
    """Opcje filtrów taksonomii (rodzaj decyzji, naruszenie, sektor itd.)"""
    return svc.get_taxonomy()


@app.get("/api/stats")
async def stats(svc: SearchService = Depends(get_search_service)):
    """Statystyki kolekcji — liczba decyzji, artykułów, krawędzi grafu."""
    return svc.get_stats()


@app.get("/api/signature/{signature}", response_model=DocumentModel)
async def get_by_signature(
    signature: str,
    svc: SearchService = Depends(get_search_service),
):
    """Pobiera chunk 0 decyzji UODO po sygnaturze (metadane + sentencja)."""
    doc = svc.fetch_by_signature(signature.upper())
    if not doc:
        raise HTTPException(status_code=404, detail=f"Decyzja {signature} nie znaleziona")
    return _docs_to_models([doc])[0]


class FullDocumentModel(BaseModel):
    """Pełna decyzja UODO — metadane + wszystkie sekcje w kolejności."""
    signature:     str
    title:         str | None = None
    title_full:    str | None = None
    status:        str | None = None
    year:          int | None = None
    source_url:    str | None = None
    keywords:      list[str] = Field(default_factory=list)
    related_acts:          list[str] = Field(default_factory=list)
    related_eu_acts:       list[str] = Field(default_factory=list)
    related_uodo_rulings:  list[str] = Field(default_factory=list)
    related_court_rulings: list[str] = Field(default_factory=list)
    term_decision_type:      list[str] = Field(default_factory=list)
    term_violation_type:     list[str] = Field(default_factory=list)
    term_corrective_measure: list[str] = Field(default_factory=list)
    term_sector:             list[str] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)


@app.get("/api/document/{signature}", response_model=FullDocumentModel)
async def get_full_document(
    signature: str,
    request: Request,
):
    """
    Pobiera pełną decyzję UODO — wszystkie sekcje w kolejności chunk_index.
    Używane przez widok dokumentu w widgecie.
    """
    sig    = signature.upper()
    client = request.app.state.opensearch

    resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"signature": sig}},
                        {"term": {"doc_type":  "uodo_decision"}},
                    ]
                }
            },
            "sort": [{"chunk_index": "asc"}],
            "size": 20,
        },
    )
    hits = resp["hits"]["hits"]
    if not hits:
        raise HTTPException(status_code=404, detail=f"Decyzja {sig} nie znaleziona")

    # Metadane z chunk 0
    meta = hits[0]["_source"]

    sections = [
        {
            "section_title": h["_source"].get("section_title", ""),
            "section_id":    h["_source"].get("section_id",    ""),
            "chunk_index":   h["_source"].get("chunk_index",   0),
            "content_text":  h["_source"].get("content_text",  ""),
        }
        for h in hits
    ]

    return FullDocumentModel(
        signature     = sig,
        title         = meta.get("title"),
        title_full    = meta.get("title_full"),
        status        = meta.get("status"),
        year          = meta.get("year"),
        source_url    = meta.get("source_url"),
        keywords      = meta.get("keywords", []),
        related_acts           = meta.get("related_acts", []),
        related_eu_acts        = meta.get("related_eu_acts", []),
        related_uodo_rulings   = meta.get("related_uodo_rulings", []),
        related_court_rulings  = meta.get("related_court_rulings", []),
        term_decision_type     = meta.get("term_decision_type", []),
        term_violation_type    = meta.get("term_violation_type", []),
        term_corrective_measure= meta.get("term_corrective_measure", []),
        term_sector            = meta.get("term_sector", []),
        sections      = sections,
    )

# ─────────────────────────── SUGGEST ─────────────────────────────

class SuggestResponse(BaseModel):
    tags:       list[str]
    signatures: list[str]


@app.get("/api/suggest", response_model=SuggestResponse)
async def suggest(
    q: str,
    limit: int = 8,
    request: Request = None,
):
    """
    Autouzupełnianie — zwraca tagi i sygnatury pasujące do prefiksu q.
    Minimum 2 znaki. Używane przez pole wyszukiwania w widgecie.
    """
    q = q.strip()
    if len(q) < 2:
        return SuggestResponse(tags=[], signatures=[])

    client   = request.app.state.opensearch
    q_lower  = q.lower()
    half     = max(2, limit // 2)

    # ── Tagi (prefix match na polu keywords) ──
    tag_resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "size": 0,
            "aggs": {
                "matching_tags": {
                    "terms": {
                        "field": "keywords",
                        "size":  limit * 4,          # pobierz więcej, filtruj po stronie serwera
                        "order": {"_count": "desc"},
                        "include": f".*{q_lower}.*", # regex prefix/contains
                    }
                }
            },
        },
    )
    all_tags = [
        b["key"]
        for b in tag_resp.get("aggregations", {})
                         .get("matching_tags", {})
                         .get("buckets", [])
    ]
    # Preferuj tagi zaczynające się od q (prefix) przed contains
    prefix_tags   = [t for t in all_tags if t.lower().startswith(q_lower)]
    contains_tags = [t for t in all_tags if not t.lower().startswith(q_lower)]
    tags = (prefix_tags + contains_tags)[:half]

    # ── Sygnatury (prefix match na polu signature) ──
    sig_resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term":   {"doc_type":    "uodo_decision"}},
                        {"term":   {"chunk_index": 0}},
                        {"prefix": {"signature":   q.upper()}},
                    ]
                }
            },
            "_source": ["signature"],
            "size": half,
            "sort": [{"year": "desc"}, {"_id": "asc"}],
            "collapse": {"field": "signature"},
        },
    )
    signatures = [
        h["_source"]["signature"]
        for h in sig_resp["hits"]["hits"]
        if h["_source"].get("signature")
    ]

    return SuggestResponse(tags=tags, signatures=signatures)

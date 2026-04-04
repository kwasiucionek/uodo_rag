"""
Wyszukiwanie — OpenSearch (kNN + BM25 + hybrid RRF), graf powiązań,
tagi LLM, taksonomia.

Brak zależności od Streamlit — działa zarówno w FastAPI jak i Streamlit.
Zasoby (embedder, graf) cachowane jako singletony modułowe.
Dane (tagi, taksonomia, statystyki) cachowane z TTL przez dekorator _ttl_cache.
"""

from __future__ import annotations

import os
import pickle
import re
import time
from functools import wraps
from typing import Any

import networkx as nx

from config import (
    EMBED_MODEL,
    GRAPH_DEPTH,
    GRAPH_PATH,
    MAX_ACT_DOCS,
    MAX_GDPR_DOCS,
    OPENSEARCH_INDEX,
    QUERY_STOPWORDS,
    TAXONOMY_STATIC,
    TOP_K,
)
from opensearch_client import (
    RRF_PIPELINE_ID,
    build_filter_must,
    get_opensearch,
    hits_to_docs,
    hybrid_body,
    knn_body,
    rrf_available,
)

# Prefiks instrukcji — wymagany przez stella-pl-retrieval-8k dla zapytań
_QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query.\nQuery: "
)


# ─────────────────────────── TTL CACHE ───────────────────────────


def _ttl_cache(seconds: int = 3600):
    """Prosty dekorator cache z TTL — zastępuje @st.cache_data(ttl=...)."""

    def decorator(func):
        _store: dict = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            if key in _store:
                result, expires = _store[key]
                if time.monotonic() < expires:
                    return result
            result = func(*args, **kwargs)
            _store[key] = (result, time.monotonic() + seconds)
            return result

        wrapper.cache_clear = lambda: _store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ─────────────────────────── MODEL EMBEDDINGOWY ──────────────────

# Wstrzykiwany przez FastAPI lifespan (set_embedder).
# Fallback: leniwe ładowanie przy pierwszym wywołaniu.
_injected_embedder = None
_loaded_embedder = None


def set_embedder(embedder) -> None:
    """Wywoływane przez FastAPI lifespan — ustawia embedder globalnie."""
    global _injected_embedder
    _injected_embedder = embedder


def get_embedder():
    global _loaded_embedder

    if _injected_embedder is not None:
        return _injected_embedder

    if _loaded_embedder is not None:
        return _loaded_embedder

    # Leniwe ładowanie (np. gdy uruchamiamy z Streamlit lub skryptów)
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    st_kwargs: dict = {"trust_remote_code": True, "device": device}
    if device == "cpu":
        # Modele z custom kodem (np. stella-pl-retrieval-mini-8k) używają
        # XFormers/Flash-Attention, które wymagają CUDA. Na CPU wymuszamy
        # standardową uwagę PyTorch, żeby uniknąć błędu przy inicjalizacji.
        st_kwargs["model_kwargs"] = {"attn_implementation": "eager"}

    model = SentenceTransformer(EMBED_MODEL, **st_kwargs)
    if device == "cuda":
        try:
            model = model.half()
        except Exception:
            pass
    _loaded_embedder = model
    return _loaded_embedder


def embed_query(text: str) -> list[float]:
    """Embedding zapytania — z prefiksem instrukcji."""
    return (
        get_embedder().encode(_QUERY_PREFIX + text, normalize_embeddings=True).tolist()
    )


def embed_document(text: str) -> list[float]:
    """Embedding dokumentu — bez prefiksu."""
    return get_embedder().encode(text, normalize_embeddings=True).tolist()


def embed(text: str) -> list[float]:
    return embed_query(text)


# ─────────────────────────── GRAF CYTOWAŃ ────────────────────────

_graph_cache: nx.DiGraph | None = None
_graph_loaded: bool = False


def get_graph() -> nx.DiGraph | None:
    global _graph_cache, _graph_loaded

    if _graph_loaded:
        return _graph_cache

    if os.path.exists(GRAPH_PATH):
        with open(GRAPH_PATH, "rb") as f:
            _graph_cache = pickle.load(f)
        _graph_loaded = True
        return _graph_cache

    G = nx.DiGraph()
    client = get_opensearch()
    search_after = None

    while True:
        body: dict = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"doc_type": "uodo_decision"}},
                        {"term": {"chunk_index": 0}},
                    ]
                }
            },
            "_source": [
                "signature",
                "related_uodo_rulings",
                "related_acts",
                "related_eu_acts",
            ],
            "size": 500,
            "sort": [{"_id": "asc"}],
        }
        if search_after:
            body["search_after"] = search_after

        resp = client.search(index=OPENSEARCH_INDEX, body=body)
        hits = resp["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            pay = hit["_source"]
            sig = pay.get("signature", "")
            if not sig:
                continue
            G.add_node(sig, doc_type="uodo_decision")
            for rel in pay.get("related_uodo_rulings", []):
                if not G.has_node(rel):
                    G.add_node(rel, doc_type="uodo_decision")
                G.add_edge(sig, rel, relation="CITES_UODO")
            for act in pay.get("related_acts", []):
                if not G.has_node(act):
                    G.add_node(act, doc_type="act")
                G.add_edge(sig, act, relation="CITES_ACT")
            for eu in pay.get("related_eu_acts", []):
                if not G.has_node(eu):
                    G.add_node(eu, doc_type="eu_act")
                G.add_edge(sig, eu, relation="CITES_EU")

        if len(hits) < 500:
            break
        search_after = hits[-1]["sort"]

    with open(GRAPH_PATH, "wb") as f:
        pickle.dump(G, f)

    _graph_cache = G
    _graph_loaded = True
    return _graph_cache


# ─────────────────────────── GRUPOWANIE CHUNKÓW ──────────────────


def _group_decision_chunks(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Grupuje chunki tej samej decyzji — zachowuje jeden dokument per signature
    z najwyższym score (best matching section).

    Dokumenty nie będące decyzjami (u.o.d.o., RODO) przechodzą bez zmian.
    """
    best: dict[str, dict] = {}
    others: list[dict] = []

    for d in docs:
        if d.get("doc_type") != "uodo_decision":
            others.append(d)
            continue
        sig = d.get("signature", "")
        score = d.get("_score", 0.0)
        if sig not in best or score > best[sig].get("_score", 0.0):
            best[sig] = d

    return list(best.values()) + others


# ─────────────────────────── WYSZUKIWANIE ────────────────────────


def semantic_search(
    query: str,
    top_k: int = TOP_K,
    filters: dict[str, Any] | None = None,
    score_threshold: float = 0.25,
) -> list[dict[str, Any]]:
    client = get_opensearch()
    filter_must = build_filter_must(filters)
    body = knn_body(embed_query(query), top_k, filter_must, score_threshold)
    resp = client.search(index=OPENSEARCH_INDEX, body=body)
    docs = hits_to_docs(resp["hits"]["hits"], source_label="semantic")
    return _group_decision_chunks(docs)


def hybrid_search_os(
    query: str,
    top_k: int = TOP_K,
    filters: dict[str, Any] | None = None,
    score_threshold: float = 0.25,
) -> list[dict[str, Any]]:
    """BM25 + kNN z RRF. Chunki tej samej decyzji grupowane po score."""
    client = get_opensearch()
    filter_must = build_filter_must(filters)
    body = hybrid_body(query, embed_query(query), top_k, filter_must, score_threshold)
    params: dict = {}
    if rrf_available():
        params["search_pipeline"] = RRF_PIPELINE_ID
    resp = client.search(index=OPENSEARCH_INDEX, body=body, params=params)
    docs = hits_to_docs(resp["hits"]["hits"], source_label="hybrid")
    return _group_decision_chunks(docs)


def keyword_exact_search(
    keyword: str,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pobiera WSZYSTKIE dokumenty z danym tagiem."""
    client = get_opensearch()
    filter_must = build_filter_must({**(filters or {}), "keyword": keyword})
    raw_docs: list[dict] = []
    search_after = None

    while True:
        body: dict = {
            "query": {"bool": {"must": filter_must}}
            if filter_must
            else {"match_all": {}},
            "size": 200,
            "sort": [{"_id": "asc"}],
        }
        if search_after:
            body["search_after"] = search_after

        resp = client.search(index=OPENSEARCH_INDEX, body=body)
        hits = resp["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            d = hit["_source"].copy()
            d["_score"] = 1.0
            d["_source"] = "keyword"
            raw_docs.append(d)

        if len(hits) < 200:
            break
        search_after = hits[-1]["sort"]

    return _group_decision_chunks(raw_docs)


def fetch_by_signature(sig: str) -> dict[str, Any] | None:
    """Pobiera chunk 0 (sentencja) decyzji po sygnaturze."""
    client = get_opensearch()
    resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"signature": sig}},
                        {"term": {"doc_type": "uodo_decision"}},
                        {"term": {"chunk_index": 0}},
                    ]
                }
            },
            "size": 1,
        },
    )
    hits = resp["hits"]["hits"]
    if not hits:
        return None
    d = hits[0]["_source"].copy()
    d["_source"] = "graph"
    d["_score"] = 0.0
    return d


# ─────────────────────────── GRAF POWIĄZAŃ ───────────────────────


def graph_expand(
    seed_sigs: list[str],
    depth: int = GRAPH_DEPTH,
) -> list[tuple[str, str, float]]:
    G = get_graph()
    if G is None:
        return []

    visited = set(seed_sigs)
    result: list[tuple[str, str, float]] = []
    frontier = set(seed_sigs)

    for d in range(depth):
        decay = 0.65**d
        new_frontier: set[str] = set()
        for node in frontier:
            if node not in G:
                continue
            for nb in G.successors(node):
                if nb not in visited and G[node][nb].get("relation") == "CITES_UODO":
                    result.append((nb, "cytowana", 0.6 * decay))
                    visited.add(nb)
                    new_frontier.add(nb)
            for nb in G.predecessors(node):
                if nb not in visited and (
                    G[nb][node].get("relation") == "CITES_UODO"
                    and G.nodes.get(nb, {}).get("doc_type") == "uodo_decision"
                ):
                    result.append((nb, "cytuje tę decyzję", 0.5 * decay))
                    visited.add(nb)
                    new_frontier.add(nb)
        frontier = new_frontier
        if not frontier or len(result) >= 20:
            break

    result.sort(key=lambda x: -x[2])
    return result[:15]


# ─────────────────────────── TAGI I TAKSONOMIA ───────────────────


@_ttl_cache(seconds=3600)
def get_all_tags() -> list[str]:
    client = get_opensearch()
    resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "size": 0,
            "aggs": {
                "all_keywords": {
                    "terms": {
                        "field": "keywords",
                        "size": 20000,
                        "order": {"_key": "asc"},
                    }
                }
            },
        },
    )
    buckets = resp.get("aggregations", {}).get("all_keywords", {}).get("buckets", [])
    return [b["key"] for b in buckets]


@_ttl_cache(seconds=3600)
def get_taxonomy_options() -> dict[str, list[str]]:
    result = {k: list(v) for k, v in TAXONOMY_STATIC.items()}
    dynamic_fields = [f for f, v in TAXONOMY_STATIC.items() if not v]
    if not dynamic_fields:
        return result
    try:
        client = get_opensearch()
        resp = client.search(
            index=OPENSEARCH_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"doc_type": "uodo_decision"}},
                            {"term": {"chunk_index": 0}},
                        ]
                    }
                },
                "aggs": {
                    field: {"terms": {"field": field, "size": 500}}
                    for field in dynamic_fields
                },
            },
        )
        for field in dynamic_fields:
            buckets = resp.get("aggregations", {}).get(field, {}).get("buckets", [])
            result[field] = sorted(b["key"] for b in buckets if b["key"])
    except Exception:
        pass
    return result


def extract_tags_with_llm(query: str, available_tags: list[str]) -> list[str]:
    from llm import call_llm_json

    tags_list = "\n".join(f"- {t}" for t in available_tags)
    prompt = (
        f"Masz listę tagów z bazy orzeczeń UODO.\n"
        f"Wybierz tagi NAJBARDZIEJ pasujące do zapytania — maksymalnie 8 tagów z listy.\n"
        f"Jeśli żaden nie pasuje możesz dodać maksymalnie 4 NOWE tagi z prefiksem [NOWY].\n"
        f"Uwzględnij synonimy i formy fleksyjne.\n"
        f'Odpowiedz WYŁĄCZNIE JSON: {{"tags": ["tag1", "tag2", ...]}}\n'
        f"Zapytanie: {query}\n\nDostępne tagi:\n{tags_list}"
    )
    try:
        raw = call_llm_json(prompt)
        lines = raw.get("tags", [])
        tags_lower = {t.lower(): t for t in available_tags}
        existing, new_tags = [], []
        for item in lines:
            line = str(item).strip().lstrip("- ").strip()
            if not line:
                continue
            if line.startswith("[NOWY]"):
                tag = line[6:].strip()
                if tag and len(tag) > 2 and len(new_tags) < 4:
                    new_tags.append(tag)
            elif line.lower() in tags_lower and len(existing) < 8:
                existing.append(tags_lower[line.lower()])
        return existing + new_tags
    except Exception:
        return []


def get_matched_tags(query: str) -> list[str]:
    return extract_tags_with_llm(query, get_all_tags())


# ─────────────────────────── DEDUPLIKACJA ────────────────────────


def doc_key(d: dict[str, Any]) -> str:
    doc_id = d.get("doc_id", "")
    if doc_id:
        return doc_id
    sig = d.get("signature", "")
    dtype = d.get("doc_type", "")
    art = d.get("article_num", "")
    chunk = d.get("chunk_index", 0)
    if dtype == "uodo_decision":
        return f"{sig}:{chunk}"
    if dtype in ("legal_act_article", "gdpr_article", "gdpr_recital"):
        return f"{dtype}:{sig}:{art}:{chunk}"
    return sig or f"{dtype}:{art}"


# ─────────────────────────── HYBRID SEARCH ───────────────────────

_MAX_RESULTS_PER_TAG = 50


def hybrid_search(
    query: str,
    search_query: str | None = None,
    top_k: int = TOP_K,
    filters: dict[str, Any] | None = None,
    use_graph: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Główna funkcja wyszukiwania.

    Decyzje UODO indeksowane na poziomie sekcji:
      - keyword_exact_search i hybrid_search_os zwracają już zgrupowane wyniki
        (jedna decyzja = jeden doc z najlepszą sekcją)
    """
    sem_query = search_query or query
    matched_tags = get_matched_tags(query)

    seen_keys: set[str] = set()
    decisions: list[dict] = []
    act_docs: list[dict] = []
    gdpr_docs: list[dict] = []

    def _add(bucket: list, doc: dict) -> bool:
        key = doc_key(doc)
        if key in seen_keys:
            return False
        seen_keys.add(key)
        bucket.append(doc)
        return True

    filters_base = {k: v for k, v in (filters or {}).items() if k != "keyword"}

    # ═══ DECYZJE UODO ════════════════════════════════════════════

    # 1a. Explicit keyword z UI
    explicit_keyword = (filters or {}).get("keyword", "")
    if explicit_keyword:
        for d in keyword_exact_search(
            explicit_keyword, {**filters_base, "doc_types": ["uodo_decision"]}
        ):
            _add(decisions, d)

    # 1b. Frazy 2-wyrazowe → exact tag match (BEZ LLM)
    words = [
        w.lower()
        for w in re.split(r"\W+", query)
        if w.lower() not in QUERY_STOPWORDS and len(w) > 2
    ]
    two_word_phrases = list(
        dict.fromkeys(f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1))
    )
    all_tags_lower = {t.lower(): t for t in get_all_tags()}
    direct_hits = [all_tags_lower[p] for p in two_word_phrases if p in all_tags_lower]

    for tag in direct_hits:
        results = keyword_exact_search(
            tag, {**filters_base, "doc_types": ["uodo_decision"]}
        )
        if len(results) <= _MAX_RESULTS_PER_TAG:
            for d in results:
                _add(decisions, d)

    # 1c. Tagi LLM (fallback)
    if not decisions and matched_tags:
        for tag in matched_tags:
            results = keyword_exact_search(
                tag, {**filters_base, "doc_types": ["uodo_decision"]}
            )
            if len(results) <= _MAX_RESULTS_PER_TAG:
                for d in results:
                    _add(decisions, d)

    # 1d. Hybrid BM25 + kNN (last resort)
    if len(decisions) < 5:
        for d in hybrid_search_os(
            sem_query,
            top_k=20,
            filters={**filters_base, "doc_types": ["uodo_decision"]},
            score_threshold=0.35,
        ):
            _add(decisions, d)

    decisions.sort(key=lambda d: -d.get("_score", 0))

    # ═══ ARTYKUŁY u.o.d.o. ═══════════════════════════════════════

    if explicit_keyword:
        for d in keyword_exact_search(
            explicit_keyword, {**filters_base, "doc_types": ["legal_act_article"]}
        ):
            if len(act_docs) >= MAX_ACT_DOCS:
                break
            _add(act_docs, d)

    if len(act_docs) < MAX_ACT_DOCS:
        for d in hybrid_search_os(
            sem_query,
            top_k=MAX_ACT_DOCS - len(act_docs),
            filters={**filters_base, "doc_types": ["legal_act_article"]},
            score_threshold=0.15,
        ):
            if len(act_docs) >= MAX_ACT_DOCS:
                break
            _add(act_docs, d)

    # ═══ ARTYKUŁY RODO ═══════════════════════════════════════════

    gdpr_types = ["gdpr_article", "gdpr_recital"]

    if explicit_keyword:
        for d in keyword_exact_search(
            explicit_keyword, {**filters_base, "doc_types": gdpr_types}
        ):
            if len(gdpr_docs) >= MAX_GDPR_DOCS:
                break
            _add(gdpr_docs, d)

    if len(gdpr_docs) < MAX_GDPR_DOCS:
        for d in hybrid_search_os(
            sem_query,
            top_k=MAX_GDPR_DOCS - len(gdpr_docs),
            filters={**filters_base, "doc_types": gdpr_types},
            score_threshold=0.20,
        ):
            if len(gdpr_docs) >= MAX_GDPR_DOCS:
                break
            _add(gdpr_docs, d)

    # ═══ ZŁĄCZ + GRAF ════════════════════════════════════════════

    merged = decisions + act_docs + gdpr_docs

    if not use_graph or not decisions:
        return merged, matched_tags

    seed_sigs = [d.get("signature", "") for d in decisions if d.get("signature")]
    seen_graph = {d.get("signature", "") for d in decisions}

    for sig, rel_type, score in graph_expand(seed_sigs):
        if sig in seen_graph:
            continue
        doc = fetch_by_signature(sig)
        if doc:
            doc["_score"] = score
            doc["_graph_relation"] = rel_type
            decisions.append(doc)
            seen_graph.add(sig)

    return decisions + act_docs + gdpr_docs, matched_tags


# ─────────────────────────── STATYSTYKI ──────────────────────────


@_ttl_cache(seconds=3600)
def get_collection_stats() -> dict[str, Any]:
    client = get_opensearch()

    def _count_decisions() -> int:
        r = client.count(
            index=OPENSEARCH_INDEX,
            body={
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"doc_type": "uodo_decision"}},
                            {"term": {"chunk_index": 0}},
                        ]
                    }
                }
            },
        )
        return r["count"]

    def _count(doc_type: str) -> int:
        r = client.count(
            index=OPENSEARCH_INDEX,
            body={"query": {"term": {"doc_type": doc_type}}},
        )
        return r["count"]

    decisions = _count_decisions()
    act_chunks = _count("legal_act_article")
    G = get_graph()
    graph_stats: dict[str, Any] = {}

    if G:
        uodo = [
            n for n, d in G.nodes(data=True) if d.get("doc_type") == "uodo_decision"
        ]
        most_cited = sorted(
            [(n, G.in_degree(n)) for n in uodo if G.in_degree(n) > 0],
            key=lambda x: -x[1],
        )[:5]
        graph_stats = {"edges": G.number_of_edges(), "most_cited": most_cited}

    return {"decisions": decisions, "act_chunks": act_chunks, **graph_stats}

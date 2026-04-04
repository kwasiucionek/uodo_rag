"""
Klient OpenSearch — połączenie, schemat indeksu, budowanie zapytań.

Obsługuje:
  - kNN (wyszukiwanie semantyczne)
  - BM25 match (wyszukiwanie pełnotekstowe)
  - hybrid (BM25 + kNN) z pipeline RRF
  - term / terms (exact match na polach keyword)
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st
from opensearchpy import OpenSearch

from config import EMBED_DIM, OPENSEARCH_INDEX, OPENSEARCH_URL

logger = logging.getLogger(__name__)

RRF_PIPELINE_ID = "uodo-rrf-pipeline"
_rrf_available = False


# ─────────────────────────── KLIENT ──────────────────────────────


_injected_opensearch = None


def set_opensearch(client) -> None:
    global _injected_opensearch
    _injected_opensearch = client


@st.cache_resource
def get_opensearch() -> OpenSearch:
    if _injected_opensearch is not None:
        return _injected_opensearch
    return OpenSearch(
        hosts=[OPENSEARCH_URL], timeout=30, max_retries=3, retry_on_timeout=True
    )


def _ensure_rrf_pipeline(client: OpenSearch) -> None:
    global _rrf_available
    try:
        client.transport.perform_request("GET", f"/_search/pipeline/{RRF_PIPELINE_ID}")
        _rrf_available = True
        return
    except Exception:
        pass
    try:
        client.transport.perform_request(
            "PUT",
            f"/_search/pipeline/{RRF_PIPELINE_ID}",
            body={
                "description": "Hybrid BM25 + kNN with RRF for UODO RAG",
                "phase_results_processors": [
                    {"score-ranker-processor": {"combination": {"technique": "rrf"}}}
                ],
            },
        )
        _rrf_available = True
        logger.info("Pipeline RRF '%s' utworzony.", RRF_PIPELINE_ID)
    except Exception as e:
        logger.warning("Pipeline RRF niedostępny (%s) — fallback do kNN.", e)
        _rrf_available = False


def rrf_available() -> bool:
    return _rrf_available


# ─────────────────────────── SCHEMAT INDEKSU ─────────────────────


def get_index_body(embed_dim: int = EMBED_DIM) -> dict:
    return {
        "settings": {
            "index.knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                # Wyszukiwanie pełnotekstowe
                "content_text": {"type": "text", "analyzer": "standard"},
                # Embedding kNN
                "embedding": {
                    "type": "knn_vector",
                    "dimension": embed_dim,
                    "method": {
                        "name": "hnsw",
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
                # Filtry keyword
                "keywords": {"type": "keyword"},
                "signature": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "status": {"type": "keyword"},
                "year": {"type": "integer"},
                "term_decision_type": {"type": "keyword"},
                "term_violation_type": {"type": "keyword"},
                "term_legal_basis": {"type": "keyword"},
                "term_corrective_measure": {"type": "keyword"},
                "term_sector": {"type": "keyword"},
                # Metadane (stored, nie filtrowane)
                "doc_id": {"type": "keyword"},
                "article_num": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "chunk_total": {"type": "integer"},
            }
        },
    }


def ensure_index(client: OpenSearch, embed_dim: int = EMBED_DIM) -> None:
    if not client.indices.exists(index=OPENSEARCH_INDEX):
        client.indices.create(
            index=OPENSEARCH_INDEX,
            body=get_index_body(embed_dim),
        )
        logger.info("Indeks '%s' utworzony (dim=%d).", OPENSEARCH_INDEX, embed_dim)
    else:
        logger.info("Indeks '%s' już istnieje.", OPENSEARCH_INDEX)


# ─────────────────────────── BUDOWANIE FILTRÓW ───────────────────


def build_filter_must(filters: dict[str, Any] | None) -> list[dict]:
    """Zamienia słownik filtrów na listę klauzul must[] dla bool query."""
    must: list[dict] = []
    if not filters:
        return must
    if filters.get("status"):
        must.append({"term": {"status": filters["status"]}})
    if filters.get("keyword"):
        must.append({"term": {"keywords": filters["keyword"]}})
    if filters.get("doc_types"):
        must.append({"terms": {"doc_type": filters["doc_types"]}})
    if filters.get("year_from") or filters.get("year_to"):
        must.append(
            {
                "range": {
                    "year": {
                        "gte": filters.get("year_from", 2000),
                        "lte": filters.get("year_to", 2030),
                    }
                }
            }
        )
    for field in (
        "term_decision_type",
        "term_violation_type",
        "term_legal_basis",
        "term_corrective_measure",
        "term_sector",
    ):
        vals = filters.get(field, [])
        if vals:
            must.append({"terms": {field: vals}})
    return must


# ─────────────────────────── BUDOWANIE ZAPYTAŃ ───────────────────


def knn_body(
    vector: list[float],
    k: int,
    filter_must: list[dict] | None = None,
    min_score: float = 0.0,
) -> dict:
    knn_clause: dict = {"vector": vector, "k": k}
    if filter_must:
        knn_clause["filter"] = {"bool": {"must": filter_must}}
    body: dict = {
        "query": {"knn": {"embedding": knn_clause}},
        "size": k,
    }
    if min_score > 0:
        body["min_score"] = min_score
    return body


def bm25_body(
    text: str,
    filter_must: list[dict] | None = None,
    size: int = 20,
) -> dict:
    if filter_must:
        query: dict = {
            "bool": {
                "must": [{"match": {"content_text": text}}],
                "filter": filter_must,
            }
        }
    else:
        query = {"match": {"content_text": text}}
    return {"query": query, "size": size}


def hybrid_body(
    text: str,
    vector: list[float],
    k: int,
    filter_must: list[dict] | None = None,
    min_score: float = 0.0,
) -> dict:
    """
    Hybrid BM25 + kNN z pipeline RRF.
    Fallback do czystego kNN gdy RRF niedostępny.
    """
    if not rrf_available():
        return knn_body(vector, k, filter_must, min_score)

    queries: list[dict] = [
        {"match": {"content_text": {"query": text}}},
        {"knn": {"embedding": {"vector": vector, "k": k}}},
    ]
    body: dict = {
        "query": {"hybrid": {"queries": queries}},
        "size": k,
    }
    if filter_must:
        body["post_filter"] = {"bool": {"must": filter_must}}
    if min_score > 0:
        body["min_score"] = min_score
    return body


def hits_to_docs(
    hits: list[dict],
    source_label: str = "semantic",
    default_score: float | None = None,
) -> list[dict[str, Any]]:
    docs = []
    for hit in hits:
        d: dict = hit["_source"].copy()
        d["_score"] = (
            default_score if default_score is not None else hit.get("_score", 0.0)
        )
        d["_source"] = source_label
        docs.append(d)
    return docs

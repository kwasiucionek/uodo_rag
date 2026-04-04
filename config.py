"""
Konfiguracja aplikacji UODO RAG — stałe i zmienne środowiskowe.
"""

import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=_env_path if _env_path.exists() else None)
except ImportError:
    pass

# ── OpenSearch ────────────────────────────────────────────────────
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "uodo_decisions")
GRAPH_PATH = os.getenv("UODO_GRAPH_PATH", "./uodo_graph.pkl")

# ── Model embeddingowy ────────────────────────────────────────────
# Dostępne modele (oba: dim=1024, kontekst 8192 tokenów, prefiks dla zapytań):
#
#   sdadas/stella-pl-retrieval-8k      — NDCG@10=62.69, 1.5B params, wymaga GPU (~6 GB VRAM)
#   sdadas/stella-pl-retrieval-mini-8k — NDCG@10=61.29,  435M params, działa na CPU i GPU
#
# UWAGA: model mini używa custom kodu opartego na stella_en_400M_v5, który domyślnie
# próbuje użyć XFormers/Flash-Attention (wymagają CUDA). Na CPU automatycznie
# wymuszamy attn_implementation="eager" (standardowa uwaga PyTorch) — patrz
# load_embedder() w tools/opensearch_indexer.py oraz get_embedder() w search.py.
#
# Prefiks instrukcji wymagany przez oba modele dla zapytań (nie dla dokumentów):
#   QUERY_PREFIX = "Instruct: Given a web search query, ...\nQuery: "
EMBED_MODEL = os.getenv("EMBED_MODEL", "sdadas/stella-pl-retrieval-mini-8k")
EMBED_DIM = 1024

# ── LLM ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

PROVIDERS = ["Ollama", "Groq"]
DEFAULT_PROVIDER = "Ollama"
DEFAULT_OLLAMA_MODEL = "mistral-large-3:675b-cloud"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

# ── Wyszukiwanie ─────────────────────────────────────────────────
TOP_K = 8
GRAPH_DEPTH = 2
MAX_ACT_DOCS = 10
MAX_GDPR_DOCS = 10

# ── URL-e zewnętrzne ─────────────────────────────────────────────
UODO_PORTAL_BASE = "https://orzeczenia.uodo.gov.pl/document"
ISAP_ACT_URL = "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20190001781"
GDPR_URL = "https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:32016R0679"

# ── Regex: sygnatura UODO wpisana bezpośrednio jako query ─────────
RE_QUERY_SIG = re.compile(r"^\s*([A-Z]{2,6}\.\d{3,5}\.\d+\.\d{4})\s*$", re.IGNORECASE)

# ── Stopwords do ekstrakcji fraz z zapytania ──────────────────────
QUERY_STOPWORDS = {
    "jakie",
    "są",
    "w",
    "o",
    "i",
    "z",
    "do",
    "na",
    "co",
    "ile",
    "jak",
    "czy",
    "przez",
    "dla",
    "po",
    "przy",
    "od",
    "ze",
    "to",
    "a",
    "że",
    "się",
    "nie",
    "być",
    "który",
    "które",
    "która",
}

# ── Taksonomia portalu UODO ───────────────────────────────────────
TAXONOMY_STATIC: dict[str, list[str]] = {
    "term_decision_type": ["nakaz", "odmowa", "umorzenie", "upomnienie", "inne"],
    "term_sector": [
        "BIP",
        "DODO",
        "Finanse",
        "Marketing",
        "Mieszkalnictwo",
        "Monitoring",
        "Pozostałe",
        "Szkolnictwo",
        "Telekomunikacja",
        "Ubezpieczenia",
        "Zatrudnienie",
        "Zdrowie",
    ],
    "term_corrective_measure": [
        "ostrzeżenie",
        "upomnienie",
        "nakaz spełnienia żądania",
        "dostosowanie",
        "poinformowanie",
        "ograniczenie przetwarzania",
        "sprostowanie/usunięcie/ograniczenie",
        "cofnięcie certyfikacji",
        "administracyjna kara pieniężna",
        "państwo trzecie",
    ],
    "term_violation_type": [],  # wypełniane dynamicznie z OpenSearch
    "term_legal_basis": [],  # j.w.
}

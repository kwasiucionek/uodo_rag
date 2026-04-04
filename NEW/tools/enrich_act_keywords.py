#!/usr/bin/env python3
"""
enrich_act_keywords.py — generuje keywords dla artykułów u.o.d.o. i RODO przez LLM
i aktualizuje dokumenty bezpośrednio w OpenSearch (bez przeindeksowania).

Uruchomienie:
  python tools/enrich_act_keywords.py --provider ollama --model qwen3:14b
  python tools/enrich_act_keywords.py --provider groq   --model llama-3.3-70b-versatile
  python tools/enrich_act_keywords.py --dry-run          # tylko wypisz, nie zapisuj

Opcje:
  --opensearch  URL OpenSearch (domyślnie http://localhost:9200)
  --index       Nazwa indeksu (domyślnie uodo_decisions)
  --provider    ollama lub groq
  --model       Nazwa modelu
  --api-key     Klucz API (lub z .env)
  --doc-types   Typy do wzbogacenia (domyślnie: legal_act_article gdpr_article gdpr_recital)
  --dry-run     Tylko wypisz, nie zapisuj
  --delay       Opóźnienie między zapytaniami w sekundach (domyślnie 0.5)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

OPENSEARCH_URL   = os.getenv("OPENSEARCH_URL",   "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "uodo_decisions")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY",     "")
OLLAMA_URL       = os.getenv("OLLAMA_URL",        "http://localhost:11434")
OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")


def get_existing_tags(client, index: str) -> List[str]:
    """Pobiera wszystkie unikalne tagi z decyzji UODO przez agregację."""
    resp = client.search(
        index=index,
        body={
            "size": 0,
            "query": {"term": {"doc_type": "uodo_decision"}},
            "aggs": {
                "all_keywords": {
                    "terms": {"field": "keywords", "size": 20000}
                }
            },
        },
    )
    buckets = resp.get("aggregations", {}).get("all_keywords", {}).get("buckets", [])
    return sorted(b["key"] for b in buckets if b["key"])


def call_llm(prompt: str, provider: str, model: str, api_key: str) -> str:
    if provider == "groq":
        from groq import Groq
        client = Groq(api_key=api_key or GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=200,
            stream=False,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""

    # Ollama
    import requests
    headers = {}
    if OLLAMA_CLOUD_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_CLOUD_API_KEY}"
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            headers=headers,
            json={
                "model":  model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        print(f"  ⚠️ Błąd Ollama: {e}")
        return ""


def generate_keywords(
    article_num: str,
    content: str,
    doc_type: str,
    existing_tags: List[str],
    provider: str,
    model: str,
    api_key: str,
) -> List[str]:
    label_map = {
        "legal_act_article": f"Art. {article_num} u.o.d.o. (ustawa o ochronie danych osobowych)",
        "gdpr_article":      f"Art. {article_num} RODO (rozporządzenie UE 2016/679)",
        "gdpr_recital":      f"Motyw {article_num} RODO (preambuła)",
    }
    label = label_map.get(doc_type, f"Art. {article_num}")

    tags_sample = "\n".join(f"- {t}" for t in existing_tags[:80])
    prompt = (
        f"Jesteś ekspertem prawa ochrony danych osobowych.\n"
        f"Poniżej jest treść: {label}\n\n"
        f"Wygeneruj 6–10 słów kluczowych opisujących ten przepis.\n"
        f"Wybieraj z listy poniżej (dokładna pisownia). Nowe tylko jeśli żaden nie pasuje.\n"
        f"Odpowiedz TYLKO listą tagów, jeden na linię, bez komentarzy.\n\n"
        f"Treść:\n{content[:800]}\n\n"
        f"Dostępne tagi:\n{tags_sample}"
    )

    raw = call_llm(prompt, provider, model, api_key)
    keywords = []
    for line in raw.strip().splitlines():
        tag = line.strip().lstrip("- •*").strip()
        if tag and 2 < len(tag) < 80:
            keywords.append(tag)
    return keywords[:8]


def enrich_documents(
    opensearch_url: str,
    index: str,
    provider: str,
    model: str,
    api_key: str,
    doc_types: List[str],
    dry_run: bool,
    delay: float,
) -> None:
    from opensearchpy import OpenSearch

    client = OpenSearch(hosts=[opensearch_url], timeout=60)

    print("Pobieranie istniejących tagów z decyzji UODO...")
    existing_tags = get_existing_tags(client, index)
    print(f"Znaleziono {len(existing_tags)} unikalnych tagów")

    # Pobierz artykuły bez keywords (search_after paginacja)
    print(f"\nPobieranie dokumentów typów: {doc_types}...")
    docs_to_enrich = []
    search_after   = None

    while True:
        body: dict = {
            "query": {"terms": {"doc_type": doc_types}},
            "size":  200,
            "sort":  [{"_id": "asc"}],
            "_source": True,
        }
        if search_after:
            body["search_after"] = search_after

        resp = client.search(index=index, body=body)
        hits = resp["hits"]["hits"]
        if not hits:
            break

        for hit in hits:
            pay = hit["_source"]
            if pay.get("keywords"):  # już wzbogacony
                continue
            docs_to_enrich.append((hit["_id"], pay))

        if len(hits) < 200:
            break
        search_after = hits[-1]["sort"]

    total = len(docs_to_enrich)
    print(f"Dokumentów do wzbogacenia: {total}")
    if total == 0:
        print("Wszystkie dokumenty mają już keywords.")
        return

    ok, errors = 0, 0
    for i, (doc_id, payload) in enumerate(docs_to_enrich, 1):
        art_num  = payload.get("article_num", "?")
        dtype    = payload.get("doc_type", "")
        content  = payload.get("content_text", "")

        print(f"[{i}/{total}] {dtype} — {art_num} ... ", end="", flush=True)

        try:
            keywords = generate_keywords(
                str(art_num), content, dtype, existing_tags, provider, model, api_key
            )
        except Exception as e:
            print(f"BŁĄD LLM: {e}")
            errors += 1
            continue

        if not keywords:
            print("brak tagów")
            continue

        print(keywords)

        if not dry_run:
            try:
                client.update(
                    index=index,
                    id=doc_id,
                    body={"doc": {"keywords": keywords}},
                )
                ok += 1
            except Exception as e:
                print(f"  BŁĄD zapisu: {e}")
                errors += 1
        else:
            ok += 1

        if delay > 0:
            time.sleep(delay)

    print(f"\nGotowe! Wzbogacono: {ok}, błędy: {errors}")
    if dry_run:
        print("(dry-run — nic nie zapisano)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generuje keywords dla artykułów u.o.d.o. i RODO"
    )
    parser.add_argument("--opensearch", default=OPENSEARCH_URL)
    parser.add_argument("--index",      default=OPENSEARCH_INDEX)
    parser.add_argument("--provider",   default="ollama", choices=["ollama", "groq"])
    parser.add_argument("--model",      default="qwen3:14b")
    parser.add_argument("--api-key",    default="")
    parser.add_argument(
        "--doc-types", nargs="+",
        default=["legal_act_article", "gdpr_article", "gdpr_recital"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    enrich_documents(
        opensearch_url=args.opensearch,
        index=args.index,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        doc_types=args.doc_types,
        dry_run=args.dry_run,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
eval.py — Automatyczna ewaluacja systemu UODO RAG.

Binarny leaderboard: każdy test zwraca 0 lub 1.

Uruchomienie:
    python tools/eval.py                  # pełna ewaluacja
    python tools/eval.py --question 3     # tylko pytanie nr 3
    python tools/eval.py --verbose        # z pełnymi odpowiedziami
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "uodo_decisions")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sdadas/stella-pl-retrieval-mini-8k")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Prefiks zapytania dla stella
_QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query.\nQuery: "
)

# ─────────────────────────── ZŁOTE PYTANIA ───────────────────────

GOLDEN_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "GQ-001",
        "question": "Jakie kary może nałożyć Prezes UODO?",
        "description": "Odpowiedź powinna wspomnieć o karach administracyjnych",
        "checks": [
            lambda a: any(
                w in a.lower() for w in ["kara", "administracyjna", "pieniężna"]
            ),
            lambda a: any(w in a.lower() for w in ["dkn", "uodo", "prezes"]),
            lambda a: "art" in a.lower() or "artykuł" in a.lower(),
        ],
        "check_names": [
            "Wspomina o karze administracyjnej",
            "Cytuje sygnaturę lub organ",
            "Powołuje się na artykuł",
        ],
    },
    {
        "id": "GQ-002",
        "question": "Kiedy wymagane jest zgłoszenie naruszenia danych do UODO?",
        "description": "Odpowiedź powinna zawierać termin 72h i Art. 33 RODO",
        "checks": [
            lambda a: "72" in a,
            lambda a: "art" in a.lower() and "33" in a,
            lambda a: any(w in a.lower() for w in ["naruszenie", "zgłoszenie"]),
        ],
        "check_names": [
            "Podaje termin 72 godzin",
            "Cytuje Art. 33 RODO",
            "Używa pojęcia naruszenie/zgłoszenie",
        ],
    },
    {
        "id": "GQ-003",
        "question": "Co to jest podstawa prawna przetwarzania danych osobowych?",
        "description": "Odpowiedź powinna wymienić podstawy z Art. 6 RODO",
        "checks": [
            lambda a: "art" in a.lower() and "6" in a,
            lambda a: any(
                w in a.lower() for w in ["zgoda", "umowa", "obowiązek", "interes"]
            ),
            lambda a: "rodo" in a.lower() or "2016/679" in a,
        ],
        "check_names": [
            "Cytuje Art. 6 RODO",
            "Wymienia co najmniej jedną podstawę",
            "Odwołuje się do RODO",
        ],
    },
    {
        "id": "GQ-004",
        "question": "Jakie obowiązki ma administrator danych wobec osoby, której dane dotyczą?",
        "description": "Odpowiedź powinna wymienić obowiązek informacyjny",
        "checks": [
            lambda a: any(
                w in a.lower() for w in ["informacyjny", "art. 13", "art. 14"]
            ),
            lambda a: any(w in a.lower() for w in ["administrator", "podmiot"]),
            lambda a: "art" in a.lower(),
        ],
        "check_names": [
            "Wspomina o obowiązku informacyjnym lub Art. 13/14",
            "Wymienia administratora",
            "Powołuje się na artykuł",
        ],
    },
    {
        "id": "GQ-005",
        "question": "Czym jest inspektor ochrony danych i kiedy trzeba go wyznaczyć?",
        "description": "Odpowiedź powinna wyjaśnić rolę IOD",
        "checks": [
            lambda a: any(w in a.lower() for w in ["inspektor", "iod", "dpo"]),
            lambda a: any(w in a.lower() for w in ["wyznaczenie", "obowiązek", "musi"]),
            lambda a: "art" in a.lower() and any(n in a for n in ["37", "38", "39"]),
        ],
        "check_names": [
            "Wyjaśnia pojęcie IOD/DPO",
            "Opisuje obowiązek wyznaczenia",
            "Cytuje Art. 37/38/39 RODO",
        ],
    },
    {
        "id": "GQ-006",
        "question": "Jakie prawa przysługują osobie, której dane są przetwarzane?",
        "description": "Odpowiedź powinna wymienić prawa dostępu, sprostowania, usunięcia",
        "checks": [
            lambda a: any(w in a.lower() for w in ["dostęp", "wgląd"]),
            lambda a: any(w in a.lower() for w in ["usunięcie", "zapomnienie"]),
            lambda a: any(w in a.lower() for w in ["sprostowanie", "poprawienie"]),
        ],
        "check_names": [
            "Wymienia prawo dostępu",
            "Wymienia prawo do usunięcia",
            "Wymienia prawo do sprostowania",
        ],
    },
    {
        "id": "GQ-007",
        "question": "Co to jest umowa powierzenia przetwarzania danych?",
        "description": "Odpowiedź powinna wyjaśnić umowę powierzenia i Art. 28 RODO",
        "checks": [
            lambda a: any(
                w in a.lower()
                for w in ["powierzenie", "procesor", "podmiot przetwarzający"]
            ),
            lambda a: "art" in a.lower() and "28" in a,
            lambda a: any(w in a.lower() for w in ["umowa", "kontrakt"]),
        ],
        "check_names": [
            "Wyjaśnia pojęcie powierzenia/procesora",
            "Cytuje Art. 28 RODO",
            "Wspomina o umowie",
        ],
    },
    {
        "id": "GQ-008",
        "question": "Jakie dane uznaje się za szczególne kategorie danych osobowych?",
        "description": "Odpowiedź powinna wymienić przykłady danych wrażliwych z Art. 9 RODO",
        "checks": [
            lambda a: any(
                w in a.lower() for w in ["szczególne", "wrażliwe", "art. 9", "art 9"]
            ),
            lambda a: any(
                w in a.lower()
                for w in ["zdrowie", "genetyczne", "rasowe", "biometryczne"]
            ),
            lambda a: "rodo" in a.lower() or "art" in a.lower(),
        ],
        "check_names": [
            "Używa pojęcia szczególne kategorie lub Art. 9",
            "Wymienia co najmniej jeden przykład",
            "Odwołuje się do RODO",
        ],
    },
    {
        "id": "GQ-009",
        "question": "Kiedy można przekazywać dane osobowe do krajów trzecich?",
        "description": "Odpowiedź powinna opisać mechanizmy transferu (rozdział V RODO)",
        "checks": [
            lambda a: any(
                w in a.lower() for w in ["kraj trzeci", "transfer", "przekazanie"]
            ),
            lambda a: any(
                w in a.lower()
                for w in ["odpowiedni stopień", "standardowe klauzule", "bcr"]
            ),
            lambda a: "art" in a.lower() or "rozdział v" in a.lower(),
        ],
        "check_names": [
            "Wspomina o przekazaniu do krajów trzecich",
            "Wymienia mechanizm transferu",
            "Powołuje się na artykuł lub rozdział V",
        ],
    },
    {
        "id": "GQ-010",
        "question": "Co to jest minimalizacja danych i zasada ograniczenia celu?",
        "description": "Odpowiedź powinna opisać zasady z Art. 5 RODO",
        "checks": [
            lambda a: "minimalizacja" in a.lower() or "minimalizację" in a.lower(),
            lambda a: any(w in a.lower() for w in ["cel", "ograniczenie celu"]),
            lambda a: "art" in a.lower() and "5" in a,
        ],
        "check_names": [
            "Wyjaśnia zasadę minimalizacji",
            "Opisuje ograniczenie celu",
            "Cytuje Art. 5 RODO",
        ],
    },
]


# ─────────────────────────── SEARCH + LLM ────────────────────────

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        st_kwargs: dict = {"trust_remote_code": True, "device": device}
        if device == "cpu":
            # Modele z custom kodem (np. stella-pl-retrieval-mini-8k) używają
            # XFormers/Flash-Attention wymagających CUDA. Na CPU wymuszamy
            # standardową uwagę PyTorch, żeby uniknąć błędu przy inicjalizacji.
            st_kwargs["model_kwargs"] = {"attn_implementation": "eager"}

        _embedder = SentenceTransformer(EMBED_MODEL, **st_kwargs)
    return _embedder


def semantic_search(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    from opensearchpy import OpenSearch

    embedder = get_embedder()
    vec = embedder.encode(_QUERY_PREFIX + query, normalize_embeddings=True).tolist()
    client = OpenSearch(hosts=[OPENSEARCH_URL])

    resp = client.search(
        index=OPENSEARCH_INDEX,
        body={
            "query": {
                "knn": {
                    "embedding": {
                        "vector": vec,
                        "k": top_k,
                        "filter": {
                            "bool": {
                                "must": [
                                    {
                                        "terms": {
                                            "doc_type": [
                                                "uodo_decision",
                                                "legal_act_article",
                                                "gdpr_article",
                                                "gdpr_recital",
                                            ]
                                        }
                                    }
                                ]
                            }
                        },
                    }
                }
            },
            "size": top_k,
        },
    )

    docs = []
    for hit in resp["hits"]["hits"]:
        d = hit["_source"].copy()
        d["_score"] = hit["_score"]
        docs.append(d)
    return docs


def build_simple_context(
    docs: list[dict[str, Any]], query: str, max_chars: int = 10000
) -> str:
    parts = [f"Pytanie: {query}\n\nDokumenty:\n"]
    chars = len(parts[0])
    for i, doc in enumerate(docs, 1):
        dtype = doc.get("doc_type", "")
        text = doc.get("content_text", "")[:600]
        if dtype == "uodo_decision":
            sig = doc.get("signature", "?")
            block = f"[{i}] DECYZJA {sig}\n{text}\n"
        elif dtype == "legal_act_article":
            art = doc.get("article_num", "?")
            block = f"[{i}] Art. {art} u.o.d.o.\n{text}\n"
        else:
            art = doc.get("article_num", "?")
            block = f"[{i}] Art. {art} RODO\n{text}\n"
        if chars + len(block) > max_chars:
            break
        parts.append(block)
        chars += len(block)
    return "\n---\n".join(parts)


def call_llm(query: str, context: str) -> str:
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)
    system = (
        "Jesteś ekspertem prawa ochrony danych osobowych. "
        "Odpowiadaj WYŁĄCZNIE na podstawie podanych dokumentów. "
        "Cytuj sygnatury decyzji i numery artykułów. "
        "Odpowiadaj po polsku."
    )
    resp = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Pytanie: {query}\n\nDokumenty:\n{context}"},
        ],
        max_tokens=1024,
        temperature=0.0,
    )
    return resp.choices[0].message.content or ""


# ─────────────────────────── RUNNER ──────────────────────────────


def run_single(gq: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    print(f"\n{'=' * 60}")
    print(f"  {gq['id']}: {gq['question']}")
    print(f"{'=' * 60}")

    t0 = time.time()
    try:
        docs = semantic_search(gq["question"])
        context = build_simple_context(docs, gq["question"])
        answer = call_llm(gq["question"], context)
    except Exception as e:
        print(f"  ❌ BŁĄD: {e}")
        return {
            "id": gq["id"],
            "question": gq["question"],
            "error": str(e),
            "checks": [],
            "passed": 0,
            "total": len(gq["checks"]),
        }

    elapsed = time.time() - t0

    if verbose:
        print(f"\n  ODPOWIEDŹ:\n  {answer[:500]}{'...' if len(answer) > 500 else ''}\n")

    check_results = []
    for name, check_fn in zip(gq["check_names"], gq["checks"]):
        try:
            passed = bool(check_fn(answer))
        except Exception:
            passed = False
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name}")
        check_results.append({"name": name, "passed": passed})

    total = len(gq["checks"])
    passed_count = sum(1 for c in check_results if c["passed"])
    print(f"\n  Wynik: {passed_count}/{total} ({elapsed:.1f}s)")

    return {
        "id": gq["id"],
        "question": gq["question"],
        "checks": check_results,
        "passed": passed_count,
        "total": total,
        "elapsed_s": round(elapsed, 1),
    }


def run_all(question_idx: int | None = None, verbose: bool = False) -> None:
    questions = GOLDEN_QUESTIONS
    if question_idx is not None:
        idx = question_idx - 1
        if not (0 <= idx < len(questions)):
            print(f"Nieprawidłowy numer pytania: {question_idx} (1–{len(questions)})")
            sys.exit(1)
        questions = [questions[idx]]

    print(f"\n{'#' * 60}")
    print(f"  UODO RAG — Ewaluacja ({len(questions)} pytań)")
    print(f"  Model: {DEFAULT_MODEL}  |  Embedder: {EMBED_MODEL}")
    print(f"  OpenSearch: {OPENSEARCH_URL}/{OPENSEARCH_INDEX}")
    print(f"{'#' * 60}")

    all_results = []
    for gq in questions:
        result = run_single(gq, verbose=verbose)
        all_results.append(result)

    total_checks = sum(r["total"] for r in all_results)
    total_passed = sum(r["passed"] for r in all_results)
    total_q = len(all_results)
    perfect = sum(1 for r in all_results if r["passed"] == r["total"])

    print(f"\n{'#' * 60}")
    print(f"  PODSUMOWANIE")
    print(f"{'#' * 60}")
    print(f"  Pytania:     {perfect}/{total_q} w pełni zdanych")
    print(f"  Sprawdzenia: {total_passed}/{total_checks} zdanych")
    pct = total_passed / total_checks * 100 if total_checks else 0
    print(f"  Wynik:       {pct:.1f}%")

    print(f"\n  {'ID':<10} {'Zdanych':<10} Wynik")
    print(f"  {'-' * 40}")
    for r in all_results:
        bar = "█" * r["passed"] + "░" * (r["total"] - r["passed"])
        icon = "✅" if r["passed"] == r["total"] else ("⚠️" if r["passed"] > 0 else "❌")
        print(f"  {r['id']:<10} {r['passed']}/{r['total']:<8} {icon} {bar}")

    output_path = "eval_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "model": DEFAULT_MODEL,
                "embedder": EMBED_MODEL,
                "summary": {
                    "questions_perfect": perfect,
                    "questions_total": total_q,
                    "checks_passed": total_passed,
                    "checks_total": total_checks,
                    "score_pct": round(pct, 1),
                },
                "results": all_results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n  Wyniki zapisane: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UODO RAG — Ewaluacja")
    parser.add_argument("--question", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not GROQ_API_KEY:
        print("❌ Brak GROQ_API_KEY — ustaw w .env")
        sys.exit(1)

    run_all(question_idx=args.question, verbose=args.verbose)

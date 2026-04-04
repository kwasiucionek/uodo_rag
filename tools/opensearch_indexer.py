#!/usr/bin/env python3
"""
opensearch_indexer.py — indeksuje wszystkie typy dokumentów w OpenSearch.

Decyzje UODO są indeksowane na poziomie sekcji (xType="sect"):
  - Każda sekcja = osobny dokument z własnym embeddingiem
  - Wszystkie sekcje tej samej decyzji mają te same metadane
    (keywords, status, terms, refs) ale inny content_text i section_title
  - chunk_index / chunk_total pozwalają odtworzyć kolejność sekcji

Fallback: jeśli decyzja nie ma pola 'sections', cały content_text = 1 chunk.

Użycie:
  python tools/opensearch_indexer.py --mode decisions --jsonl tools/uodo_decisions_enriched.jsonl
  python tools/opensearch_indexer.py --mode act       --md tools/D20191781L.md
  python tools/opensearch_indexer.py --mode rodo      --md tools/rodo_2016_679_pl.md
  python tools/opensearch_indexer.py --mode all \\
      --jsonl tools/uodo_decisions_enriched.jsonl \\
      --md-act tools/D20191781L.md \\
      --md-rodo tools/rodo_2016_679_pl.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
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
EMBED_DIM = 1024
BATCH_SIZE = 32
EMBED_MAX_CHARS = 5500


# ─────────────────────────── HELPERS ─────────────────────────────


def sig_to_id(prefix: str, key: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(f"{prefix}:{key}".encode()).digest()))


def get_client(url: str):
    from opensearchpy import OpenSearch

    return OpenSearch(hosts=[url], timeout=60)


def ensure_index(client, index: str) -> None:
    from opensearch_client import get_index_body

    if not client.indices.exists(index=index):
        client.indices.create(index=index, body=get_index_body(EMBED_DIM))
        print(f"Indeks '{index}' utworzony (dim={EMBED_DIM}).")
    else:
        print(f"Indeks '{index}' już istnieje.")


def load_embedder(model_name: str):
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Ładowanie modelu: {model_name} (device={device})")

    # Na CPU modele z custom kodem (np. stella_en_400M_v5 / mini) używają
    # XFormers/Flash-Attention, które wymagają CUDA. Wymuszamy standardową
    # implementację uwagi PyTorch przez attn_implementation="eager".
    model_kwargs: dict = {}
    if device == "cpu":
        model_kwargs["attn_implementation"] = "eager"

    return SentenceTransformer(
        model_name,
        trust_remote_code=True,
        device=device,
        model_kwargs=model_kwargs or None,
    )


def embed_batch(
    texts: list[str],
    embedder,
    batch_size: int = BATCH_SIZE,
) -> list[list[float]]:
    """Dokumenty indeksowane BEZ prefiksu instrukcji (prefiks tylko dla zapytań)."""
    vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_vecs = embedder.encode(
            batch, normalize_embeddings=True, show_progress_bar=False
        )
        vecs.extend(batch_vecs.tolist())
        print(f"  Embeddingi: {min(i + batch_size, len(texts))}/{len(texts)}", end="\r")
    print()
    return vecs


def delete_by_type(client, index: str, doc_type: str) -> None:
    client.delete_by_query(
        index=index,
        body={"query": {"term": {"doc_type": doc_type}}},
        params={"refresh": "true"},
    )
    print(f"Usunięto dokumenty doc_type='{doc_type}'.")


def bulk_upsert(
    client,
    index: str,
    docs: list[dict],
    vecs: list[list[float]],
) -> tuple[int, int]:
    from opensearchpy.helpers import bulk

    actions = []
    for doc, vec in zip(docs, vecs):
        doc_id = doc.pop("_id", None) or str(uuid.uuid4())
        actions.append(
            {
                "_index": index,
                "_id": doc_id,
                "_source": {**doc, "embedding": vec},
            }
        )

    ok, errors = bulk(client, actions, raise_on_error=False)
    return ok, len(errors)


def get_indexed_doc_ids(client, index: str) -> set[str]:
    """
    Zwraca doc_id już zaindeksowanych chunków decyzji UODO.
    Format doc_id: 'uodo:{signature}:chunk{N}'
    """
    ids = set()
    search_after = None
    while True:
        body: dict = {
            "query": {"term": {"doc_type": "uodo_decision"}},
            "_source": ["doc_id"],
            "size": 1000,
            "sort": [{"_id": "asc"}],
        }
        if search_after:
            body["search_after"] = search_after
        resp = client.search(index=index, body=body)
        hits = resp["hits"]["hits"]
        if not hits:
            break
        for h in hits:
            ids.add(h["_source"].get("doc_id", ""))
        if len(hits) < 1000:
            break
        search_after = hits[-1]["sort"]
    return ids


# ─────────────────────────── DECYZJE UODO ────────────────────────


def _decision_base_payload(doc: dict) -> dict:
    """
    Metadane wspólne dla wszystkich chunków tej samej decyzji.
    Każdy chunk ma te same filtry, tagi, referencje.
    """
    refs = doc.get("refs_from_content", {})
    kw_raw = doc.get("keywords", "")
    kw_list = doc.get("keywords_list", []) or [
        k.strip() for k in kw_raw.split(",") if k.strip()
    ]
    subject = " | ".join(
        e.get("name", "") or e.get("title", "")
        for e in doc.get("entities", [])
        if e.get("function") in ("other", "author")
        and (e.get("name") or e.get("title"))
    )
    return {
        "doc_type": "uodo_decision",
        "signature": doc.get("signature", ""),
        "title": doc.get("title", ""),
        "title_full": doc.get("title_full", "") or doc.get("title", ""),
        "status": doc.get("status", ""),
        "year": doc.get("year", 0),
        "source_url": doc.get("url", ""),
        "subject": subject,
        "keywords": kw_list,
        "keywords_text": kw_raw,
        "related_acts": refs.get("acts", [])[:50],
        "related_eu_acts": refs.get("eu_acts", [])[:20],
        "related_uodo_rulings": refs.get("uodo_rulings", [])[:30],
        "related_court_rulings": refs.get("court_rulings", [])[:20],
        "term_decision_type": doc.get("term_decision_type", []),
        "term_violation_type": doc.get("term_violation_type", []),
        "term_legal_basis": doc.get("term_legal_basis", []),
        "term_corrective_measure": doc.get("term_corrective_measure", []),
        "term_sector": doc.get("term_sector", []),
        "refs_full": doc.get("refs_full", [])[:100],
    }


def _build_section_embed_text(
    doc: dict,
    section: dict,
    chunk_index: int,
    chunk_total: int,
) -> str:
    """
    Tekst do embeddingu sekcji.
    Kontekst decyzji (sygnatura, tytuł, słowa kluczowe) na początku
    zwiększa trafność wyszukiwania semantycznego.
    """
    sig = doc.get("signature", "")
    title_full = doc.get("title_full", "") or doc.get("title", "")
    status = doc.get("status", "")
    keywords = doc.get("keywords", "")
    section_title = section.get("section_title", "")
    section_text = section.get("text", "")[:EMBED_MAX_CHARS]

    header = f"{sig} {title_full} {status}\nSłowa kluczowe: {keywords}\n"
    if section_title:
        header += f"Sekcja: {section_title}\n"
    return f"{header}\n{section_text}"


def build_decision_sections(doc: dict) -> list[tuple[dict, str]]:
    """
    Zwraca listę (payload, embed_text) dla każdego chunku decyzji.
    """
    sig = doc.get("signature", "")
    base = _decision_base_payload(doc)
    raw_secs = doc.get("sections", [])

    # Fallback dla starych JSONL bez pola 'sections'
    if not raw_secs:
        content = doc.get("content_text", "")[:50000]
        if not content:
            return []
        raw_secs = [{"section_title": "Treść", "section_id": "0", "text": content}]

    chunk_total = len(raw_secs)
    result = []

    for ci, section in enumerate(raw_secs):
        doc_id = f"uodo:{sig}:chunk{ci}"
        payload = {
            "_id": sig_to_id("uodo_chunk", doc_id),
            "doc_id": doc_id,
            "chunk_index": ci,
            "chunk_total": chunk_total,
            "section_title": section.get("section_title", ""),
            "section_id": section.get("section_id", ""),
            "content_text": section.get("text", "")[:50000],
            **base,
        }
        embed_text = _build_section_embed_text(doc, section, ci, chunk_total)
        result.append((payload, embed_text))

    return result


def index_decisions(
    jsonl_path: str,
    client,
    index: str,
    embedder,
    rebuild: bool = False,
    batch_size: int = BATCH_SIZE,
) -> None:
    docs_raw = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    docs_raw.append(json.loads(line))
                except Exception:
                    pass
    print(f"Wczytano {len(docs_raw)} decyzji z {jsonl_path}")

    if rebuild:
        delete_by_type(client, index, "uodo_decision")
        done_ids: set[str] = set()
    else:
        done_ids = get_indexed_doc_ids(client, index)
        print(f"Już zaindeksowane chunki: {len(done_ids)}")

    # Zbierz chunki do zaindeksowania
    to_index: list[tuple[dict, str]] = []
    for doc in docs_raw:
        sig = doc.get("signature", "")
        if not sig:
            continue
        for payload, embed_text in build_decision_sections(doc):
            if payload["doc_id"] not in done_ids:
                to_index.append((payload, embed_text))

    print(
        f"Do zaindeksowania: {len(to_index)} chunków "
        f"(z {len(docs_raw)} decyzji, avg {len(to_index) / max(len(docs_raw), 1):.1f} chunka/decyzja)"
    )

    if not to_index:
        print("Gotowe!")
        return

    payloads = [p for p, _ in to_index]
    texts = [t for _, t in to_index]
    vecs = embed_batch(texts, embedder, batch_size)
    ok, err = bulk_upsert(client, index, payloads, vecs)
    print(f"Zaindeksowano: {ok} chunków, błędy: {err}")


# ─────────────────────────── USTAWA u.o.d.o. ─────────────────────

ACT_SIGNATURE = "Dz.U. 2019 poz. 1781"
ACT_TITLE = "Ustawa z dnia 10 maja 2018 r. o ochronie danych osobowych"
ACT_MAX = 108
ACT_CHUNK_MAX = 3000
ACT_OVERLAP = 300


def _chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for para in re.split(r"(\n(?=\d+\)|§|\-\s|[a-z]\)))", text):
        if len(current) + len(para) <= max_chars:
            current += para
        else:
            if current.strip():
                chunks.append(current.strip())
            current = (current[-overlap:] if len(current) > overlap else "") + para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def parse_act_articles(md_path: str) -> list[dict]:
    with open(md_path, encoding="utf-8") as f:
        lines = f.readlines()

    start = 0
    for i, line in enumerate(lines):
        if re.match(r"^Art\. 1\. 1\. Ustawę stosuje się", line):
            start = i
            break

    content = "".join(lines[start:])
    content = re.sub(r"---\s*\n## Strona \d+\s*\n", "\n", content)

    articles = []
    for m in re.finditer(
        r"^Art\. (\d+)\.(.*?)(?=^Art\. \d+\.|\Z)", content, re.MULTILINE | re.DOTALL
    ):
        num = int(m.group(1))
        if num > ACT_MAX:
            continue
        articles.append(
            {"article_num": num, "text": f"Art. {num}.{m.group(2)}".strip()}
        )

    print(f"Sparsowano {len(articles)} artykułów u.o.d.o. (Art. 1–{ACT_MAX})")
    return articles


def index_act(
    md_path: str,
    client,
    index: str,
    embedder,
    rebuild: bool = False,
    batch_size: int = BATCH_SIZE,
) -> None:
    if rebuild:
        delete_by_type(client, index, "legal_act_article")

    articles = parse_act_articles(md_path)
    payloads, texts = [], []

    for art in articles:
        chunks = _chunk_text(art["text"], ACT_CHUNK_MAX, ACT_OVERLAP)
        for ci, chunk in enumerate(chunks):
            doc_id = f"uodo_act:{ACT_SIGNATURE}:art{art['article_num']}:chunk{ci}"
            payload = {
                "_id": sig_to_id("uodo_act", doc_id),
                "doc_id": doc_id,
                "doc_type": "legal_act_article",
                "signature": ACT_SIGNATURE,
                "article_num": str(art["article_num"]),
                "chunk_index": ci,
                "chunk_total": len(chunks),
                "content_text": chunk,
                "year": 2019,
                "status": "obowiązujący",
                "keywords": [],
                "related_eu_acts": ["EU 2016/679"],
            }
            embed_text = (
                f"{ACT_SIGNATURE} u.o.d.o. {ACT_TITLE}\n"
                f"Art. {art['article_num']}"
                + (f" (część {ci + 1}/{len(chunks)})" if len(chunks) > 1 else "")
                + f"\n\n{chunk}"
            )
            payloads.append(payload)
            texts.append(embed_text)

    print(f"Artykuły u.o.d.o.: {len(payloads)} chunków")
    vecs = embed_batch(texts, embedder, batch_size)
    ok, err = bulk_upsert(client, index, payloads, vecs)
    print(f"Zaindeksowano: {ok}, błędy: {err}")


# ─────────────────────────── RODO ────────────────────────────────

RODO_CHUNK_MAX = 1200
RODO_OVERLAP = 100


def parse_rodo_md(text: str) -> list[dict]:
    lines = text.splitlines()
    docs = []

    recital_re = re.compile(r"^- \((\d{1,3})\)\s+(.*)")
    recitals: dict[str, str] = {}
    current_recital = None
    for line in lines:
        m = recital_re.match(line)
        if m:
            current_recital = m.group(1)
            recitals[current_recital] = m.group(2).strip()
        elif current_recital:
            if re.match(r"^#{1,6}\s+ROZDZIAŁ", line):
                current_recital = None
            elif line.strip() and not re.match(r"^#{1,6}\s+|^> ", line):
                recitals[current_recital] += " " + line.lstrip("- ").strip()

    for num, content in recitals.items():
        content = content.strip()
        if len(content) < 20:
            continue
        docs.append(
            {
                "doc_id": f"gdpr_recital:{num}",
                "doc_type": "gdpr_recital",
                "article_num": f"motyw {num}",
                "chunk_index": 0,
                "chunk_total": 1,
                "content_text": f"Motyw {num} RODO:\n{content}",
                "keywords": [],
            }
        )

    i = 0
    while i < len(lines):
        m_art = re.match(r"^#{1,6}\s+Artykuł\s+(\d+)\s*$", lines[i])
        if not m_art:
            i += 1
            continue
        art_num = m_art.group(1)
        body_lines = []
        j = i + 1
        while j < len(lines):
            nl = lines[j]
            if re.match(r"^#{1,6}\s+(Artykuł\s+\d+|ROZDZIAŁ)\s*", nl):
                break
            body_lines.append(nl)
            j += 1
        body = "\n".join(body_lines).strip()
        body = re.sub(r"\n+> \([\w⁰-⁹]+\).*$", "", body, flags=re.MULTILINE).strip()
        full = f"Artykuł {art_num} RODO\n\n{body}"
        chunks = _chunk_text(full, RODO_CHUNK_MAX, RODO_OVERLAP)
        for ci, chunk in enumerate(chunks):
            docs.append(
                {
                    "doc_id": f"gdpr_article:{art_num}:chunk{ci}",
                    "doc_type": "gdpr_article",
                    "article_num": art_num,
                    "chunk_index": ci,
                    "chunk_total": len(chunks),
                    "content_text": chunk,
                    "keywords": [],
                }
            )
        i = j

    arts = sum(1 for d in docs if d["doc_type"] == "gdpr_article")
    recits = sum(1 for d in docs if d["doc_type"] == "gdpr_recital")
    print(f"RODO: {arts} chunków artykułów, {recits} motywów")
    return docs


def index_rodo(
    md_path: str,
    client,
    index: str,
    embedder,
    rebuild: bool = False,
    batch_size: int = BATCH_SIZE,
) -> None:
    if rebuild:
        for dtype in ("gdpr_article", "gdpr_recital"):
            delete_by_type(client, index, dtype)

    text = Path(md_path).read_text(encoding="utf-8")
    docs = parse_rodo_md(text)
    payloads = []
    texts = []
    for doc in docs:
        payload = {**doc, "_id": sig_to_id("gdpr", doc["doc_id"])}
        payloads.append(payload)
        texts.append(doc["content_text"])

    vecs = embed_batch(texts, embedder, batch_size)
    ok, err = bulk_upsert(client, index, payloads, vecs)
    print(f"Zaindeksowano: {ok}, błędy: {err}")


# ─────────────────────────── MAIN ────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Indeksuje dokumenty UODO RAG w OpenSearch (sekcje XML)"
    )
    parser.add_argument(
        "--mode", choices=["decisions", "act", "rodo", "all"], required=True
    )
    parser.add_argument("--jsonl", default="tools/uodo_decisions_enriched.jsonl")
    parser.add_argument("--md-act", default="tools/D20191781L.md")
    parser.add_argument("--md-rodo", default="tools/rodo_2016_679_pl.md")
    parser.add_argument("--opensearch", default=OPENSEARCH_URL)
    parser.add_argument("--index", default=OPENSEARCH_INDEX)
    parser.add_argument("--model", default=EMBED_MODEL)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    client = get_client(args.opensearch)
    embedder = load_embedder(args.model)

    ensure_index(client, args.index)

    if args.mode in ("decisions", "all"):
        print("\n=== Decyzje UODO (granularność: sekcja) ===")
        index_decisions(
            args.jsonl,
            client,
            args.index,
            embedder,
            rebuild=args.rebuild,
            batch_size=args.batch_size,
        )

    if args.mode in ("act", "all"):
        print("\n=== Ustawa u.o.d.o. ===")
        index_act(
            args.md_act,
            client,
            args.index,
            embedder,
            rebuild=args.rebuild,
            batch_size=args.batch_size,
        )

    if args.mode in ("rodo", "all"):
        print("\n=== RODO ===")
        index_rodo(
            args.md_rodo,
            client,
            args.index,
            embedder,
            rebuild=args.rebuild,
            batch_size=args.batch_size,
        )

    print("\n✅ Wszystko gotowe!")
    info = client.cat.count(index=args.index, params={"format": "json"})
    print(f"Dokumentów w indeksie: {info[0]['count']}")


if __name__ == "__main__":
    main()

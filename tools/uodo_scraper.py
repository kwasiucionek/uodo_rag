#!/usr/bin/env python3
"""
UODO API Scraper — pobiera orzeczenia UODO przez REST API portalu.

Treść dokumentu pobierana jako XML (000_pl.xml).
Referencje wyciągane z atrybutów <xLexLink xRef="...">.
Dokument dzielony na sekcje (xType="sect") dla granularnego indeksowania.

Użycie:
  python uodo_scraper.py --test
  python uodo_scraper.py --output uodo_decisions.jsonl
  python uodo_scraper.py --output uodo_decisions.jsonl --date-from 2024-01-01
"""

import argparse
import json
import os
import re
import time
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPBasicAuth

# ─────────────────────────── CONFIG ──────────────────────────────

API_BASE      = "https://orzeczenia.uodo.gov.pl/api"
DEFAULT_DELAY = 0.3
BATCH_SIZE    = 100
MAX_RETRIES   = 3
TIMEOUT       = 30

SEARCH_FIELDS = "id,refid,refname,keywords,title_pl,date_announcement,date_publication"


# ─────────────────────────── URN KATEGORYZACJA ───────────────────

_URN_CATEGORIES = [
    ("urn:ndoc:pro:pl:",        "act",          "legislation"),
    ("urn:ndoc:pro:eu:",        "eu_act",        "legislation"),
    ("urn:ndoc:gov:pl:uodo:",   "uodo_ruling",   "ruling"),
    ("urn:ndoc:court:pl:sa:",   "court_ruling",  "ruling"),
    ("urn:ndoc:court:pl:sp:",   "court_ruling",  "ruling"),
    ("urn:ndoc:court:pl:sn:",   "court_ruling",  "ruling"),
    ("urn:ndoc:court:pl:tk:",   "court_ruling",  "ruling"),
    ("urn:ndoc:court:eu:tsue:", "eu_ruling",     "ruling"),
    ("urn:ndoc:gov:eu:edpb:",   "edpb",          "ruling"),
]


def urn_to_category(urn: str) -> str:
    for prefix, category, _ in _URN_CATEGORIES:
        if urn.startswith(prefix):
            return category
    return "other"


def urn_to_signature(urn: str, display_text: str = "") -> str:
    m = re.search(r"durp:(\d{4}):(\d+)", urn)
    if m:
        return f"Dz.U. {m.group(1)} poz. {m.group(2)}"
    m = re.search(r"ojol:(\d{4}):(\d+)", urn)
    if m:
        return f"EU {m.group(1)}/{m.group(2)}"
    m = re.search(r"uodo:(\d{4}):([\w]+)$", urn)
    if m:
        year  = m.group(1)
        code  = m.group(2).upper().replace("_", ".")
        parts = [p for p in code.split(".") if p != year]
        if len(parts) >= 3:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.{year}"
        return f"{code}.{year}"
    if display_text.strip():
        return display_text.strip()
    return urn.split(":")[-1].replace("_", " ").upper()


# ─────────────────────────── HTTP ────────────────────────────────

def make_session(user: str = None, password: str = None) -> requests.Session:
    s = requests.Session()
    if user and password:
        s.auth = HTTPBasicAuth(user, password)
    s.headers["Accept"] = "application/json"
    return s


def get(
    session: requests.Session,
    url: str,
    retries: int = MAX_RETRIES,
    accept: str = None,
) -> Optional[requests.Response]:
    headers = {"Accept": accept} if accept else {}
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=TIMEOUT, headers=headers)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            if r.status_code == 401:
                print("  ❌ HTTP 401 — wymagana autoryzacja")
                return None
            print(f"  ⚠️ HTTP {r.status_code} (próba {attempt + 1})")
        except Exception as e:
            print(f"  ⚠️ Błąd połączenia: {e} (próba {attempt + 1})")
        if attempt < retries - 1:
            time.sleep(2)
    return None


# ─────────────────────────── PARSOWANIE XML ──────────────────────

def _iter_text(element: ET.Element) -> str:
    """Rekurencyjnie wyciąga czysty tekst z elementu XML."""
    parts = []
    if element.text and element.text.strip():
        parts.append(element.text.strip())

    for child in element:
        child_tag  = child.tag.lower()
        child_text = _iter_text(child)

        if child_tag in ("xunit", "xblock"):
            if child_text:
                parts.append(child_text)
                parts.append("")
        elif child_tag == "xtext":
            if child_text:
                parts.append(child_text)
        elif child_tag in ("xtitle", "xname"):
            if child_text and child_text.strip() not in (" ", ""):
                parts.append(f"\n{child_text}\n")
        else:
            if child_text:
                parts.append(child_text)

        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())

    return " ".join(p for p in parts if p.strip())


def _extract_sections(root: ET.Element) -> list:
    """
    Wyciąga sekcje z XML decyzji UODO jako listę chunków.

    Hierarchia chunkowania:
      1. B1 (bran bez tytułu) → zawsze osobny chunk "Sentencja"
      2. Bezpośrednie passy w B2 (przed chpt) → chunk "Stan faktyczny"
      3. Każdy sect (xType="sect") → osobny chunk z tytułem sekcji
      4. Fallback gdy brak sects → każdy bran jako osobny chunk

    Każdy chunk: { section_title, section_id, text }
    """
    xblock = root.find("xBlock")
    if xblock is None:
        return []

    sections = []

    for bran in xblock:
        if bran.get("xType") != "bran":
            continue

        bran_title_el = bran.find("xTitle")
        bran_title    = (bran_title_el.text or "").strip() if bran_title_el is not None else ""
        bran_bookmark = bran.get("xBookmark", "")

        # Sekcje (sect) zagnieżdżone w tym branie
        all_sects = [e for e in bran.iter() if e.get("xType") == "sect"]

        if all_sects:
            # Bezpośrednie passy w tym branie (przed rozdziałem chpt)
            direct_passes = [
                c for c in bran
                if c.get("xType") in ("pass", "none")
            ]
            if direct_passes:
                text = "\n\n".join(
                    _iter_text(p).strip()
                    for p in direct_passes
                    if _iter_text(p).strip()
                )
                if text:
                    intro_title = (
                        f"{bran_title}: Stan faktyczny" if bran_title else "Stan faktyczny"
                    )
                    sections.append({
                        "section_title": intro_title,
                        "section_id":    f"{bran_bookmark}:intro",
                        "text":          text,
                    })

            # Każda sekcja jako osobny chunk
            for sect in all_sects:
                sect_title_el = sect.find("xTitle")
                sect_title    = (
                    (sect_title_el.text or "").strip()
                    if sect_title_el is not None else ""
                )
                full_title = (
                    f"{bran_title}: {sect_title}".strip(": ")
                    if bran_title else sect_title
                )
                text = _iter_text(sect).strip()
                if text:
                    sections.append({
                        "section_title": full_title,
                        "section_id":    sect.get("xBookmark", ""),
                        "text":          text,
                    })

        else:
            # Brak sekcji — cały bran jako jeden chunk
            text = _iter_text(bran).strip()
            if text:
                title = bran_title or ("Sentencja" if not sections else "Treść")
                sections.append({
                    "section_title": title,
                    "section_id":    bran_bookmark,
                    "text":          text,
                })

    return sections


def parse_xml_content(xml_bytes: bytes) -> dict:
    """
    Parsuje XML treści decyzji UODO.

    Zwraca:
      content_text — pełny tekst (sekcje sklejone — do budowy grafu)
      sections     — lista chunków: [{section_title, section_id, text}]
      refs         — słownik referencji {category: [signatures]}
      refs_full    — lista pełnych obiektów referencji
    """
    result = {
        "content_text": "",
        "sections":     [],
        "refs": {
            "acts": [], "eu_acts": [], "uodo_rulings": [],
            "court_rulings": [], "eu_rulings": [], "edpb": [],
        },
        "refs_full": [],
    }

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  ⚠️ Błąd parsowania XML: {e}")
        return result

    sections = _extract_sections(root)
    result["sections"]     = sections
    result["content_text"] = "\n\n".join(s["text"] for s in sections).strip()

    seen_sigs: set = set()
    cat_map = {
        "act":          "acts",
        "eu_act":       "eu_acts",
        "uodo_ruling":  "uodo_rulings",
        "court_ruling": "court_rulings",
        "eu_ruling":    "eu_rulings",
        "edpb":         "edpb",
    }

    for link in root.iter("xLexLink"):
        urn      = link.get("xRef", "").strip()
        if not urn:
            continue
        display   = (link.text or "").strip()
        category  = urn_to_category(urn)
        signature = urn_to_signature(urn, display)

        if not signature or signature in seen_sigs:
            continue
        seen_sigs.add(signature)

        result["refs_full"].append({
            "urn": urn, "signature": signature,
            "category": category, "display": display,
        })
        bucket = cat_map.get(category)
        if bucket:
            result["refs"][bucket].append(signature)

    return result


# ─────────────────────────── SEARCH ──────────────────────────────

def fetch_document_list(
    session: requests.Session,
    date_from: str = None,
    date_to: str = None,
) -> list:
    date_from = date_from or ""
    date_to   = date_to   or ""
    timespan  = f"{date_from},{date_to}"

    all_docs = []
    offset   = 0

    print(f"🔍 Pobieranie listy dokumentów UODO (zakres: '{timespan}')...")

    while True:
        url = (
            f"{API_BASE}/documents/search/PublicDocument/{timespan}"
            f"/publicator_subtype:eq:uodo"
            f"?from={offset}&count={BATCH_SIZE}&order=-id&fields={SEARCH_FIELDS}"
        )
        r = get(session, url)
        if not r:
            print(f"  ❌ Błąd pobierania przy offset={offset}")
            break

        batch = r.json()
        if not batch:
            break

        all_docs.extend(batch)
        offset += len(batch)
        print(f"  📋 {offset} dokumentów...")

        if len(batch) < BATCH_SIZE:
            break

    print(f"✅ Łącznie: {len(all_docs)} dokumentów")
    return all_docs


# ─────────────────────────── HELPERS META ────────────────────────

def multilang_str(field) -> str:
    if isinstance(field, dict):
        return field.get("pl") or field.get("en") or ""
    return str(field) if field else ""


def parse_dates(data) -> dict:
    result = {"date_issued": "", "date_published": "", "date_effect": ""}
    items  = data if isinstance(data, list) else (data or {}).get("dates", [])
    for d in (items if isinstance(items, list) else []):
        if not isinstance(d, dict):
            continue
        use = d.get("use", "")
        val = d.get("date", "")
        if not val:
            continue
        if use == "announcement" and not result["date_issued"]:
            result["date_issued"]    = val
        elif use == "publication" and not result["date_published"]:
            result["date_published"] = val
        elif use == "effect" and not result["date_effect"]:
            result["date_effect"]    = val
    return result


_PUB_STATUS_MAP = {
    "final": "prawomocna", "nonfinal": "nieprawomocna",
    "published": "prawomocna", "archived": "prawomocna",
}
_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}
_RE_DATE = re.compile(
    r"(?:z\s+dnia\s+|dnia\s+)(\d{1,2})\s+"
    r"(stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|"
    r"wrze\u015bnia|pa\u017adziernika|listopada|grudnia)"
    r"\s+(20[12]\d)\s+r\."
)


def extract_date_from_text(content: str) -> str:
    header_end = content.find("Na podstawie")
    header     = content[:header_end] if header_end > 0 else content[:500]
    m          = _RE_DATE.search(header)
    if m:
        month = _MONTHS.get(m.group(2), 0)
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
    return ""


def parse_meta(data: dict) -> dict:
    result = {
        "name": "", "title_full": "", "keywords": "", "keywords_list": [],
        "entities": [], "kind": "", "legal_status": "", "pub_workflow_status": "",
        "date_issued": "", "date_published": "",
        "term_decision_type": [], "term_violation_type": [], "term_legal_basis": [],
        "term_corrective_measure": [], "term_sector": [],
        "refs": {
            "acts": [], "eu_acts": [], "uodo_rulings": [],
            "court_rulings": [], "refs_full": [],
        },
    }
    if not data:
        return result

    result["name"]         = multilang_str(data.get("name", {}))
    result["title_full"]   = multilang_str(data.get("title", {}))
    result["legal_status"] = data.get("status", "")

    dates = parse_dates(data.get("dates", []))
    result["date_issued"]    = dates["date_issued"]
    result["date_published"] = dates["date_published"]

    kw_names = []
    for term in (data.get("terms", []) or []):
        if not isinstance(term, dict):
            continue
        name_pl = multilang_str(term.get("name", {}))
        label   = term.get("label", "")
        if name_pl:
            kw_names.append(name_pl)
        if label:
            mapping = {
                "1": "term_decision_type", "2": "term_violation_type",
                "3": "term_legal_basis",   "4": "term_corrective_measure",
                "9": "term_sector",
            }
            field = mapping.get(label.split(".")[0])
            if field:
                result[field].append(name_pl)

    result["keywords_list"] = kw_names
    result["keywords"]      = ", ".join(kw_names)

    for ent in (data.get("entities", []) or []):
        if isinstance(ent, dict):
            result["entities"].append({
                "title":    multilang_str(ent.get("title", {})),
                "name":     multilang_str(ent.get("name", {})),
                "function": ent.get("function", "other"),
            })

    result["kind"] = data.get("kind", "")
    pub = data.get("publication", {})
    result["pub_workflow_status"] = pub.get("status", "") if isinstance(pub, dict) else ""

    cat_map = {
        "act": "acts", "eu_act": "eu_acts",
        "uodo_ruling": "uodo_rulings", "court_ruling": "court_rulings",
    }
    for ref in (data.get("refs", []) or []):
        if not isinstance(ref, dict):
            continue
        urn  = ref.get("refid", "")
        name = ref.get("name", "") or ""
        if not urn:
            continue
        cat = urn_to_category(urn)
        sig = urn_to_signature(urn, name)
        if not sig:
            continue
        result["refs"]["refs_full"].append({"urn": urn, "signature": sig, "category": cat})
        bucket = cat_map.get(cat)
        if bucket and sig not in result["refs"][bucket]:
            result["refs"][bucket].append(sig)

    return result


def extract_legal_status(keywords: str, pub_status: str) -> str:
    if pub_status in _PUB_STATUS_MAP:
        return _PUB_STATUS_MAP[pub_status]
    return "prawomocna" if "prawomocna" in keywords.lower() else "nieprawomocna"


def refid_to_signature(refid: str) -> str:
    return urn_to_signature(refid)


def _merge_refs(xml_refs: dict, meta_refs: dict) -> dict:
    merged = {
        "acts": list(xml_refs.get("acts", [])),
        "eu_acts": list(xml_refs.get("eu_acts", [])),
        "uodo_rulings": list(xml_refs.get("uodo_rulings", [])),
        "court_rulings": list(xml_refs.get("court_rulings", [])),
        "eu_rulings": list(xml_refs.get("eu_rulings", [])),
        "edpb": list(xml_refs.get("edpb", [])),
        "refs_full": list(xml_refs.get("refs_full", [])),
    }
    seen_sigs = {e["signature"] for e in merged["refs_full"]}
    cat_map   = {
        "act": "acts", "eu_act": "eu_acts",
        "uodo_ruling": "uodo_rulings", "court_ruling": "court_rulings",
    }
    for entry in meta_refs.get("refs_full", []):
        sig = entry.get("signature", "")
        if sig and sig not in seen_sigs:
            seen_sigs.add(sig)
            merged["refs_full"].append(entry)
            bucket = cat_map.get(entry.get("category", ""))
            if bucket and sig not in merged[bucket]:
                merged[bucket].append(sig)
    return merged


# ─────────────────────────── POBIERANIE DOKUMENTU ────────────────

def fetch_decision(
    session: requests.Session,
    doc_id: str,
    doc_fields: dict,
    delay: float = DEFAULT_DELAY,
) -> dict:
    refid = doc_fields.get("refid", "")
    if not refid:
        return {"_error": "brak_refid", "doc_id": doc_id}

    sig = refid_to_signature(refid)

    doc = {
        "doc_id": doc_id, "refid": refid, "signature": sig,
        "url": f"https://orzeczenia.uodo.gov.pl/document/{refid}/content",
        "source_collection": "UODO",
        "title": "", "title_full": "", "keywords": "", "keywords_list": [],
        "status": "", "pub_workflow_status": "", "kind": "",
        "date_issued": "", "date_published": "", "date_effect": "",
        "year": 0, "entities": [],
        "content_text": "",   # pełny tekst (sklejone sekcje)
        "sections":     [],   # granularne chunki do indeksowania
        "refs_from_content": {
            "acts": [], "eu_acts": [], "uodo_rulings": [],
            "court_rulings": [], "eu_rulings": [], "edpb": [],
        },
        "refs_full": [],
        "related_legislation": [], "related_rulings": [],
        "term_decision_type": [], "term_violation_type": [],
        "term_legal_basis": [], "term_corrective_measure": [], "term_sector": [],
    }

    year_m      = re.search(r"\b(20\d{2})\b", sig)
    doc["year"] = int(year_m.group(1)) if year_m else 0

    kw_raw         = doc_fields.get("keywords", "")
    doc["keywords"] = ", ".join(kw_raw) if isinstance(kw_raw, list) else str(kw_raw or "")
    doc["title"]    = doc_fields.get("title_pl", "")

    # ── 1. Treść XML ─────────────────────────────────────────────
    xml_url    = f"{API_BASE}/documents/events/{doc_id}/000_pl.xml"
    r          = get(session, xml_url, accept="application/xml")
    time.sleep(delay)

    xml_parsed: dict = {}
    if r:
        print(f"  ✅ XML: {len(r.content)} bajtów")
        xml_parsed          = parse_xml_content(r.content)
        doc["content_text"] = xml_parsed.get("content_text", "")
        doc["sections"]     = xml_parsed.get("sections", [])
        print(f"  ✅ Sekcje: {len(doc['sections'])} chunków "
              f"({', '.join(s['section_title'][:30] for s in doc['sections'])})")
    else:
        # Fallback do body.txt
        txt_url = f"{API_BASE}/documents/public/items/{refid}:0/body.txt"
        r_txt   = get(session, txt_url, accept="text/plain")
        time.sleep(delay)
        if r_txt:
            doc["content_text"] = r_txt.text
            doc["sections"]     = [{
                "section_title": "Treść",
                "section_id":    "0",
                "text":          r_txt.text,
            }]
            print(f"  ✅ TXT fallback: {len(r_txt.text)} znaków")
        else:
            print("  ⚠️ Brak treści")

    # ── 2. Metadane (meta.json) ───────────────────────────────────
    r = get(session, f"{API_BASE}/documents/public/items/{refid}/meta.json")
    time.sleep(delay)

    meta_parsed: dict = {}
    if r:
        meta_parsed = parse_meta(r.json())
        if not doc["title"] and meta_parsed["name"]:
            doc["title"] = meta_parsed["name"]
        doc["title_full"]          = meta_parsed["title_full"] or doc["title"]
        doc["entities"]            = meta_parsed["entities"]
        doc["kind"]                = meta_parsed["kind"]
        doc["pub_workflow_status"] = meta_parsed["pub_workflow_status"]
        for field in (
            "term_decision_type", "term_violation_type", "term_legal_basis",
            "term_corrective_measure", "term_sector",
        ):
            doc[field] = meta_parsed[field]

        if meta_parsed["keywords"]:
            doc["keywords"]      = meta_parsed["keywords"]
            doc["keywords_list"] = meta_parsed["keywords_list"]
        else:
            doc["keywords_list"] = [k.strip() for k in doc["keywords"].split(",") if k.strip()]

        doc["status"] = (
            meta_parsed["legal_status"] or
            extract_legal_status(doc["keywords"], doc["pub_workflow_status"])
        )
        if meta_parsed["date_issued"]:
            doc["date_issued"]    = meta_parsed["date_issued"]
        if meta_parsed["date_published"]:
            doc["date_published"] = meta_parsed["date_published"]

        print(
            f"  ✅ meta: keywords={len(doc['keywords_list'])}, "
            f"kind={doc['kind']}, status={doc['status']}, issued={doc['date_issued']}"
        )

    # ── 3. Daty (dates.json) ──────────────────────────────────────
    r = get(session, f"{API_BASE}/documents/public/items/{refid}/dates.json")
    time.sleep(delay)
    if r:
        dates = parse_dates(r.json())
        if dates["date_issued"]:    doc["date_issued"]    = dates["date_issued"]
        if dates["date_published"]: doc["date_published"] = dates["date_published"]
        if dates["date_effect"]:    doc["date_effect"]    = dates["date_effect"]

    if not doc["date_issued"] and doc["content_text"]:
        doc["date_issued"] = extract_date_from_text(doc["content_text"])
    if doc["date_issued"]:
        doc["year"] = int(doc["date_issued"][:4])
        print(f"  ✅ data: {doc['date_issued']}")
    else:
        print("  ⚠️ brak daty")

    # ── 4. Łączenie referencji ────────────────────────────────────
    merged = _merge_refs(
        xml_parsed.get("refs", {}),
        meta_parsed.get("refs", {}) if meta_parsed else {},
    )

    doc["refs_from_content"] = {k: merged[k] for k in (
        "acts", "eu_acts", "uodo_rulings", "court_rulings", "eu_rulings", "edpb"
    )}
    doc["refs_full"] = merged["refs_full"]
    doc["related_legislation"] = (
        [{"type": "act",    "signature": s} for s in merged["acts"]] +
        [{"type": "eu_act", "signature": s} for s in merged["eu_acts"]]
    )
    doc["related_rulings"] = (
        [{"type": "uodo_ruling",  "signature": s} for s in merged["uodo_rulings"]] +
        [{"type": "court_ruling", "signature": s} for s in merged["court_rulings"]] +
        [{"type": "eu_ruling",    "signature": s} for s in merged["eu_rulings"]]
    )

    total_refs = sum(len(v) for v in doc["refs_from_content"].values())
    print(
        f"  ✅ refs: acts={len(merged['acts'])}, eu={len(merged['eu_acts'])}, "
        f"uodo={len(merged['uodo_rulings'])}, courts={len(merged['court_rulings'])}, "
        f"eu_rulings={len(merged['eu_rulings'])} | łącznie={total_refs}"
    )

    return doc


# ─────────────────────────── GŁÓWNA PĘTLA ────────────────────────

def scrape_all(
    output_path: str,
    user: str = None,
    password: str = None,
    delay: float = DEFAULT_DELAY,
    resume: bool = True,
    date_from: str = None,
    date_to: str = None,
    limit: int = None,
) -> None:
    session = make_session(user, password)

    done: set = set()
    if resume and os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    done.add(d.get("doc_id", ""))
                    done.add(d.get("refid", ""))
                except Exception:
                    pass
        print(f"🔄 Resume: {len(done) // 2} już pobranych")

    all_docs  = fetch_document_list(session, date_from, date_to)
    if limit:
        all_docs = all_docs[:limit]

    to_scrape = [d for d in all_docs if d.get("id", "") not in done]
    print(f"📝 Do pobrania: {len(to_scrape)}")
    if not to_scrape:
        print("✅ Wszystko gotowe!")
        return

    errors = 0
    with open(output_path, "a", encoding="utf-8") as out_f:
        for i, doc_fields in enumerate(to_scrape, 1):
            doc_id = doc_fields.get("id", "")
            refid  = doc_fields.get("refid", "")
            sig    = refid_to_signature(refid) if refid else doc_id
            print(f"\n[{i}/{len(to_scrape)}] 🔍 {sig}")

            doc = fetch_decision(session, doc_id, doc_fields, delay=delay)
            if doc.get("_error"):
                print(f"  ❌ {doc['_error']}")
                errors += 1
                continue

            out_f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            out_f.flush()

            if i % 50 == 0:
                print(f"\n📊 {i}/{len(to_scrape)} ({i/len(to_scrape)*100:.1f}%), błędy: {errors}")

    print(f"\n✅ Gotowe! błędy: {errors}/{len(to_scrape)}")


# ─────────────────────────── CLI ─────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UODO API Scraper (XML + sekcje)")
    parser.add_argument("--output",    default="uodo_decisions.jsonl")
    parser.add_argument("--user",      default=None)
    parser.add_argument("--password",  default=None)
    parser.add_argument("--delay",     type=float, default=DEFAULT_DELAY)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--date-from", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--date-to",   default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--test",      action="store_true",
                        help="Pobierz 3 dokumenty testowe")
    args = parser.parse_args()

    if args.test:
        out = "uodo_test.jsonl"
        if os.path.exists(out):
            os.remove(out)
        scrape_all(out, args.user, args.password,
                   delay=args.delay, resume=False, limit=3)

        print("\n=== WYNIKI TESTU ===")
        with open(out) as f:
            for line in f:
                d    = json.loads(line)
                refs = d.get("refs_from_content", {})
                print(f"\n{'='*60}")
                print(f"Sygnatura:  {d['signature']}")
                print(f"Status:     {d.get('status', '')}")
                print(f"Data:       {d.get('date_issued', '')}")
                print(f"Sekcje ({len(d.get('sections', []))}):")
                for s in d.get("sections", []):
                    print(f"  [{s['section_id']}] '{s['section_title']}' — {len(s['text'])} znaków")
                print(f"Acts:       {refs.get('acts', [])[:3]}")
                print(f"EU acts:    {refs.get('eu_acts', [])[:3]}")
                print(f"UODO refs:  {refs.get('uodo_rulings', [])[:3]}")
                print(f"EU rulings: {refs.get('eu_rulings', [])[:3]}")
    else:
        scrape_all(
            args.output, args.user, args.password,
            delay=args.delay, resume=not args.no_resume,
            date_from=args.date_from, date_to=args.date_to,
        )

import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
// ─────────────────────────── LINKI DO REFERENCJI ─────────────────
/**
 * Generuje URL na podstawie URN (z ref-publicators.json portalu).
 *
 * urn:ndoc:court:pl:sa:  → NSA (Centralna Baza Orzeczeń SA)
 * urn:ndoc:court:pl:sp:  → MS Portal Orzeczeń Sądów Powszechnych
 * urn:ndoc:court:pl:sn:  → Sąd Najwyższy
 * urn:ndoc:court:pl:tk:  → ISAP (Trybunał Konstytucyjny)
 * urn:ndoc:court:eu:tsue → TSUE Curia
 * urn:ndoc:gov:pl:uodo:  → widget (/?doc=SIG)
 * urn:ndoc:pro:pl:       → ISAP
 * urn:ndoc:pro:eu:       → EUR-Lex
 * urn:ndoc:gov:eu:edpb:  → EDPB
 */
function urnToUrl(urn, signature) {
    // NSA — Centralna Baza Orzeczeń Sądów Administracyjnych
    if (urn.startsWith('urn:ndoc:court:pl:sa:')) {
        return `https://orzeczenia.nsa.gov.pl/cbo/find?cboPhrases=${encodeURIComponent(signature)}`;
    }
    // Sądy powszechne — Portal MS z własnym enkodowaniem sygnatury
    if (urn.startsWith('urn:ndoc:court:pl:sp:')) {
        const encoded = signature.split('').map((c) => {
            if (c === ' ')
                return '$0020';
            if (c === '/')
                return '$002f';
            return c;
        }).join('');
        return `https://orzeczenia.ms.gov.pl/search/advanced/$N/${encoded}/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/1`;
    }
    // Sąd Najwyższy
    if (urn.startsWith('urn:ndoc:court:pl:sn:')) {
        return `https://www.sn.pl/sites/orzecznictwo/Orzeczenia3/${encodeURIComponent(signature)}.pdf`;
    }
    // TSUE → Curia
    if (urn.startsWith('urn:ndoc:court:eu:tsue:')) {
        return `https://curia.europa.eu/juris/liste.jsf?num=${encodeURIComponent(signature)}`;
    }
    // EDPB
    if (urn.startsWith('urn:ndoc:gov:eu:edpb:')) {
        return 'https://edpb.europa.eu/our-work-tools/our-documents_pl';
    }
    // Decyzje UODO → widget
    if (urn.startsWith('urn:ndoc:gov:pl:uodo:')) {
        return `/?doc=${encodeURIComponent(signature)}`;
    }
    // ISAP (akty PL i TK)
    if (urn.startsWith('urn:ndoc:pro:pl:') || urn.startsWith('urn:ndoc:court:pl:tk:')) {
        const m = signature.match(/Dz\.U\.\s*(\d{4})\s*poz\.\s*(\d+)/);
        if (m) {
            return `https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU${m[1]}${m[2].padStart(7, '0')}`;
        }
        // fallback — szukaj po tytule
        const durp = urn.match(/durp:(\d{4}):(\d+)/);
        if (durp) {
            return `https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU${durp[1]}${durp[2].padStart(7, '0')}`;
        }
        return null;
    }
    // EUR-Lex (akty UE i TSUE przez CELEX)
    if (urn.startsWith('urn:ndoc:pro:eu:')) {
        const m = signature.match(/EU\s+(\d{4})\/(\d+)/);
        if (m) {
            return `https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:3${m[1]}R${m[2].padStart(4, '0')}`;
        }
        return null;
    }
    return null;
}
// ─────────────────────────── HELPERS ─────────────────────────────
function statusClass(status) {
    if (!status)
        return 'status-unknown';
    const s = status.toLowerCase();
    if (s.includes('prawomocna') && !s.includes('nie'))
        return 'status-final';
    if (s.includes('nieprawomocna'))
        return 'status-nonfinal';
    if (s.includes('uchylona'))
        return 'status-repealed';
    return 'status-unknown';
}
// ─────────────────────────── SEKCJA REFERENCJI ───────────────────
const CATEGORY_LABELS = {
    act: 'Akty prawne (PL)',
    eu_act: 'Akty prawne (UE)',
    uodo_ruling: 'Decyzje UODO',
    court_ruling: 'Orzeczenia sądów',
    eu_ruling: 'Orzeczenia TSUE',
    edpb: 'Wytyczne EROD',
};
const CATEGORY_ORDER = ['uodo_ruling', 'act', 'eu_act', 'court_ruling', 'eu_ruling', 'edpb'];
function RefsSection({ refs }) {
    if (!refs.length)
        return null;
    // Grupowanie po kategorii
    const groups = {};
    for (const ref of refs) {
        const cat = ref.category || 'other';
        if (!groups[cat])
            groups[cat] = [];
        groups[cat].push(ref);
    }
    const orderedCats = [
        ...CATEGORY_ORDER.filter((c) => groups[c]),
        ...Object.keys(groups).filter((c) => !CATEGORY_ORDER.includes(c)),
    ];
    return (_jsxs("aside", { className: "doc-view-refs", children: [_jsx("h3", { className: "doc-view-refs-title", children: "Powo\u0142ane dokumenty" }), orderedCats.map((cat) => (_jsxs("div", { className: "doc-view-refs-group", children: [_jsx("h4", { children: CATEGORY_LABELS[cat] ?? cat }), _jsx("ul", { children: groups[cat].map((entry) => {
                            const url = urnToUrl(entry.urn, entry.signature);
                            const label = entry.display || entry.signature;
                            return (_jsx("li", { children: url ? (_jsxs("a", { href: url, target: "_blank", rel: "noopener noreferrer", className: "doc-ref-link", title: `Otwórz: ${label}`, children: [label, _jsx("span", { className: "doc-ref-arrow", children: "\u2197" })] })) : (_jsx("span", { children: label })) }, entry.urn));
                        }) })] }, cat)))] }));
}
// ─────────────────────────── NAWIGACJA SEKCJI ────────────────────
function SectionNav({ sections, active, onSelect, }) {
    if (sections.length <= 1)
        return null;
    return (_jsx("nav", { className: "doc-view-nav", "aria-label": "Sekcje dokumentu", children: sections.map((s, i) => (_jsxs("button", { className: `doc-view-nav-item ${active === i ? 'doc-view-nav-item--active' : ''}`, onClick: () => onSelect(i), title: s.section_title || `Sekcja ${i + 1}`, children: [_jsx("span", { className: "doc-view-nav-num", children: i + 1 }), _jsx("span", { className: "doc-view-nav-label", children: s.section_title || `Sekcja ${i + 1}` })] }, i))) }));
}
// ─────────────────────────── GŁÓWNY KOMPONENT ────────────────────
export function DocumentView({ signature, onBack }) {
    const [doc, setDoc] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [active, setActive] = useState(0);
    useEffect(() => {
        setLoading(true);
        setError(null);
        setActive(0);
        fetch(`${API_URL}/api/document?signature=${encodeURIComponent(signature)}`)
            .then((r) => {
            if (!r.ok)
                throw new Error(`HTTP ${r.status}`);
            return r.json();
        })
            .then((data) => {
            setDoc(data);
            setLoading(false);
        })
            .catch((e) => {
            setError(String(e));
            setLoading(false);
        });
    }, [signature]);
    // Nawigacja klawiaturą ← →
    useEffect(() => {
        if (!doc)
            return;
        const handler = (e) => {
            if (e.key === 'ArrowRight')
                setActive((a) => Math.min(a + 1, doc.sections.length - 1));
            if (e.key === 'ArrowLeft')
                setActive((a) => Math.max(a - 1, 0));
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [doc]);
    if (loading)
        return (_jsxs("div", { className: "uodo-rag-widget", children: [_jsx("div", { className: "rag-skeleton", style: { height: 60, marginBottom: 8 } }), _jsx("div", { className: "rag-skeleton", style: { height: 300 } })] }));
    if (error || !doc)
        return (_jsxs("div", { className: "uodo-rag-widget", children: [_jsxs("div", { className: "rag-error", children: ["Nie uda\u0142o si\u0119 wczyta\u0107 dokumentu: ", error] }), _jsx("button", { className: "doc-view-back", onClick: onBack, children: "\u2190 Wr\u00F3\u0107 do wynik\u00F3w" })] }));
    const hasRefs = doc.refs_full?.length > 0;
    const section = doc.sections[active];
    const isFirst = active === 0;
    const isLast = active === doc.sections.length - 1;
    const totalSecs = doc.sections.length;
    return (_jsxs("div", { className: "uodo-rag-widget", children: [_jsx("button", { className: "doc-view-back", onClick: onBack, children: "\u2190 Wr\u00F3\u0107 do wynik\u00F3w" }), _jsxs("div", { className: "doc-view-header", children: [_jsxs("div", { className: "doc-view-header-top", children: [_jsx("h1", { className: "doc-view-signature", children: doc.signature }), _jsxs("div", { className: "doc-view-header-meta", children: [doc.status && (_jsx("span", { className: `status-badge ${statusClass(doc.status)}`, children: doc.status })), doc.year && _jsx("span", { className: "doc-view-year", children: doc.year })] })] }), doc.title_full && _jsx("p", { className: "doc-view-title", children: doc.title_full }), doc.keywords.length > 0 && (_jsx("div", { className: "ui-result-tags", style: { marginTop: '0.75rem' }, children: doc.keywords.map((kw, i) => (_jsx("span", { className: "ui-result-tag", children: kw }, `${kw}-${i}`))) })), doc.source_url && (_jsx("a", { href: doc.source_url, target: "_blank", rel: "noopener noreferrer", className: "doc-view-portal-link", children: "Otw\u00F3rz na portalu orzeczenia.uodo.gov.pl \u2192" }))] }), _jsxs("div", { className: "doc-view-body", children: [_jsx(SectionNav, { sections: doc.sections, active: active, onSelect: setActive }), _jsx("div", { className: "doc-view-content", children: section && (_jsxs(_Fragment, { children: [_jsxs("div", { className: "doc-view-section-header", children: [_jsx("h2", { className: "doc-view-section-title", children: section.section_title || `Sekcja ${active + 1}` }), totalSecs > 1 && (_jsxs("span", { className: "doc-view-section-counter", children: [active + 1, " / ", totalSecs] }))] }), _jsx("div", { className: "doc-view-section-text", children: _jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], children: section.content_text }) }), totalSecs > 1 && (_jsxs("div", { className: "doc-view-section-nav-btns", children: [_jsx("button", { className: "doc-view-nav-prev", onClick: () => setActive((a) => a - 1), disabled: isFirst, children: "\u2190 Poprzednia sekcja" }), _jsx("button", { className: "doc-view-nav-next", onClick: () => setActive((a) => a + 1), disabled: isLast, children: "Nast\u0119pna sekcja \u2192" })] }))] })) }), hasRefs && _jsx(RefsSection, { refs: doc.refs_full })] })] }));
}

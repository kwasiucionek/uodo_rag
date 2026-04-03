import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useSearch } from './hooks/useSearch';
import { FiltersPanel } from './FiltersPanel';
import { SearchInput } from './SearchInput';
const PER_PAGE = 10;
// ─────────────────────────── STATUS HELPERS ──────────────────────
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
function statusLabel(status) {
    if (!status)
        return '';
    const s = status.toLowerCase();
    if (s.includes('prawomocna') && !s.includes('nie'))
        return 'prawomocna';
    if (s.includes('nieprawomocna'))
        return 'nieprawomocna';
    if (s.includes('uchylona'))
        return 'uchylona';
    return status;
}
// ─────────────────────────── KARTA DECYZJI ───────────────────────
function DocumentCard({ doc, onClick, }) {
    const handleClick = () => {
        if (onClick) {
            onClick(doc);
        }
        else if (doc.signature) {
            window.open(`/?doc=${encodeURIComponent(doc.signature)}`, '_blank', 'noopener');
        }
    };
    return (_jsxs("article", { className: "doc-list-item", onClick: handleClick, role: "button", tabIndex: 0, onKeyDown: (e) => e.key === 'Enter' && handleClick(), "aria-label": `Otwórz decyzję ${doc.signature}`, children: [_jsxs("header", { children: [_jsx("span", { className: "doc-signature", children: doc.signature }), _jsxs("div", { className: "doc-meta", children: [doc.graph_relation && (_jsx("span", { className: "doc-graph-rel", children: doc.graph_relation })), doc.status && (_jsx("span", { className: `status-badge ${statusClass(doc.status)}`, children: statusLabel(doc.status) })), doc.year && _jsx("time", { dateTime: String(doc.year), children: _jsx("small", { children: doc.year }) })] })] }), _jsxs("main", { children: [doc.title_full && _jsx("h2", { children: doc.title_full }), doc.section_title && (_jsxs("span", { className: "doc-section", children: ["Sekcja: ", doc.section_title] })), doc.content_text && (_jsxs("p", { className: "doc-excerpt", children: [doc.content_text.slice(0, 280), "\u2026"] }))] }), doc.keywords.length > 0 && (_jsx("footer", { children: _jsx("div", { className: "ui-result-tags", children: doc.keywords.slice(0, 6).map((kw, i) => (_jsx("span", { className: "ui-result-tag", children: kw }, `${kw}-${i}`))) }) }))] }));
}
// ─────────────────────────── KARTA ARTYKUŁU ──────────────────────
const ACT_URL = 'https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20190001781';
const RODO_URL = 'https://eur-lex.europa.eu/legal-content/PL/TXT/HTML/?uri=CELEX:32016R0679';
function ArticleCard({ doc }) {
    const [expanded, setExpanded] = useState(false);
    const isAct = doc.doc_type === 'legal_act_article';
    const isRecital = doc.doc_type === 'gdpr_recital';
    const sourceUrl = isAct ? ACT_URL : RODO_URL;
    const label = isAct
        ? `Art. ${doc.article_num} u.o.d.o.`
        : isRecital
            ? `Motyw ${doc.article_num} RODO`
            : `Art. ${doc.article_num} RODO`;
    const sourceName = isAct
        ? 'Ustawa o ochronie danych osobowych (ISAP)'
        : 'RODO — EUR-Lex';
    return (_jsxs("article", { className: "doc-list-item doc-list-item--article", children: [_jsxs("header", { children: [_jsx("span", { className: "doc-signature", children: label }), _jsx("a", { href: sourceUrl, target: "_blank", rel: "noopener noreferrer", className: "doc-source-link", onClick: (e) => e.stopPropagation(), title: `Otwórz ${sourceName}`, children: "\u0179r\u00F3d\u0142o \u2192" })] }), _jsx("main", { children: expanded ? (_jsx("div", { className: "doc-article-text", children: _jsx(ReactMarkdown, { children: doc.content_text ?? '' }) })) : (_jsxs("p", { className: "doc-excerpt", children: [(doc.content_text ?? '').slice(0, 300), "\u2026"] })) }), _jsx("footer", { style: { borderTop: 'none', paddingTop: 0 }, children: _jsx("button", { className: "doc-expand-btn", onClick: () => setExpanded((v) => !v), children: expanded ? '▲ Zwiń' : '▼ Pokaż pełny tekst' }) })] }));
}
// ─────────────────────────── ZAKŁADKI ────────────────────────────
function Tabs({ active, onChange, counts, }) {
    const tabs = [
        { id: 'decisions', label: 'Decyzje UODO' },
        { id: 'act', label: 'Ustawa u.o.d.o.' },
        { id: 'rodo', label: 'RODO' },
    ];
    return (_jsx("div", { className: "rag-tabs", role: "tablist", children: tabs.map((t) => (_jsxs("button", { role: "tab", "aria-selected": active === t.id, className: `rag-tab ${active === t.id ? 'rag-tab--active' : ''}`, onClick: () => onChange(t.id), children: [t.label, counts[t.id] > 0 && (_jsx("span", { className: "rag-tab-count", children: counts[t.id] }))] }, t.id))) }));
}
// ─────────────────────────── PAGINACJA ───────────────────────────
function Pagination({ page, totalPages, onPage, }) {
    if (totalPages <= 1)
        return null;
    const pages = [];
    const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
    if (totalPages <= 7) {
        pages.push(...range(1, totalPages));
    }
    else {
        pages.push(1);
        if (page > 3)
            pages.push('…');
        pages.push(...range(Math.max(2, page - 1), Math.min(totalPages - 1, page + 1)));
        if (page < totalPages - 2)
            pages.push('…');
        pages.push(totalPages);
    }
    return (_jsxs("nav", { className: "rag-pagination", "aria-label": "Paginacja wynik\u00F3w", children: [_jsx("button", { className: "rag-page-btn", onClick: () => onPage(page - 1), disabled: page === 1, children: "\u2039" }), pages.map((p, i) => p === '…' ? (_jsx("span", { className: "rag-page-ellipsis", children: "\u2026" }, `e-${i}`)) : (_jsx("button", { className: `rag-page-btn ${p === page ? 'rag-page-btn--active' : ''}`, onClick: () => onPage(p), "aria-current": p === page ? 'page' : undefined, children: p }, p))), _jsx("button", { className: "rag-page-btn", onClick: () => onPage(page + 1), disabled: page === totalPages, children: "\u203A" })] }));
}
// ─────────────────────────── AKTYWNE FILTRY ──────────────────────
function ActiveFilters({ filters, onRemove, }) {
    const items = [];
    if (filters.status)
        items.push({ key: 'status', label: `Status: ${filters.status}` });
    if (filters.year_from)
        items.push({ key: 'year_from', label: `Od: ${filters.year_from}` });
    if (filters.year_to)
        items.push({ key: 'year_to', label: `Do: ${filters.year_to}` });
    const listKeys = [
        'term_decision_type', 'term_sector',
        'term_corrective_measure', 'term_violation_type',
    ];
    for (const key of listKeys) {
        for (const v of filters[key] ?? []) {
            items.push({ key, label: v, value: v });
        }
    }
    if (!items.length)
        return null;
    return (_jsx("div", { className: "rag-active-filters", children: items.map((item, i) => (_jsxs("span", { className: "rag-active-filter-tag", children: [item.label, _jsx("button", { onClick: () => onRemove(item.key, item.value), children: "\u00D7" })] }, i))) }));
}
// ─────────────────────────── GŁÓWNY KOMPONENT ────────────────────
export function UodoRagWidget({ provider = 'Ollama', model = 'mistral-large-3:675b-cloud', useLLM = true, onDocumentClick, }) {
    const [query, setQuery] = useState('');
    const [filters, setFilters] = useState({});
    const [pending, setPending] = useState({});
    const [tab, setTab] = useState('decisions');
    const [page, setPage] = useState(1);
    const { allDocs, tags, answer, searchTime, total, loadingDocs, loadingAnswer, error, search, stopStream, } = useSearch({ provider, model, useLLM });
    // ── Podział wyników na typy ──
    const decisions = allDocs.filter((d) => d.doc_type === 'uodo_decision');
    const actDocs = allDocs.filter((d) => d.doc_type === 'legal_act_article');
    const gdprDocs = allDocs.filter((d) => d.doc_type === 'gdpr_article' || d.doc_type === 'gdpr_recital');
    const counts = {
        decisions: decisions.length,
        act: actDocs.length,
        rodo: gdprDocs.length,
    };
    // ── Paginacja decyzji ──
    const totalPages = Math.max(1, Math.ceil(decisions.length / PER_PAGE));
    const safePage = Math.min(Math.max(1, page), totalPages);
    const pagedDocs = decisions.slice((safePage - 1) * PER_PAGE, safePage * PER_PAGE);
    const hasResults = allDocs.length > 0 || loadingDocs;
    const handleSearch = (overrideFilters, overrideQuery) => {
        const q = overrideQuery ?? query;
        if (!q.trim())
            return;
        const f = overrideFilters ?? filters;
        setFilters(f);
        setPage(1);
        search(q, f);
    };
    const handleTabChange = (t) => {
        setTab(t);
        setPage(1);
    };
    const handleFiltersApply = () => {
        setFilters(pending);
        setPage(1);
        search(query, pending);
    };
    const handleFiltersReset = () => {
        setPending({});
        setFilters({});
        setPage(1);
        if (query.trim())
            search(query, {});
    };
    const removeFilter = (key, value) => {
        let next;
        if (value) {
            const current = filters[key] ?? [];
            next = { ...filters, [key]: current.filter((v) => v !== value) };
            if (!next[key].length)
                delete next[key];
        }
        else {
            next = { ...filters };
            delete next[key];
        }
        setFilters(next);
        setPending(next);
        setPage(1);
        if (query.trim())
            search(query, next);
    };
    return (_jsxs("div", { className: "uodo-rag-widget", children: [_jsxs("div", { className: "rag-search-card", children: [_jsx("h2", { children: "Wyszukiwarka decyzji UODO z AI" }), _jsxs("div", { className: "rag-search-bar", children: [_jsx(SearchInput, { value: query, onChange: setQuery, onSearch: (q) => handleSearch(undefined, q), disabled: loadingDocs }), _jsx("button", { onClick: () => handleSearch(), disabled: loadingDocs || !query.trim(), className: "rag-search-btn", children: loadingDocs ? 'Szukam…' : 'Szukaj' })] })] }), error && _jsx("div", { className: "rag-error", role: "alert", children: error }), (answer || loadingAnswer) && (_jsxs("div", { className: "rag-answer", children: [_jsxs("div", { className: "rag-answer-header", children: [_jsx("span", { children: "Odpowied\u017A AI" }), loadingAnswer && (_jsx("button", { onClick: stopStream, className: "rag-stop-btn", children: "Zatrzymaj" }))] }), _jsxs("div", { className: "rag-answer-body", children: [_jsx(ReactMarkdown, { children: answer }), loadingAnswer && _jsx("span", { className: "rag-cursor", children: "\u258B" })] })] })), _jsx(ActiveFilters, { filters: filters, onRemove: removeFilter }), total > 0 && !loadingDocs && (_jsxs("p", { className: "rag-stats", children: [total, " dokument\u00F3w \u00B7 ", searchTime.toFixed(2), "s", tags.length > 0 && _jsxs(_Fragment, { children: [" \u00B7 tagi: ", tags.slice(0, 4).join(', ')] })] })), hasResults && (_jsxs("div", { className: "rag-layout", children: [_jsx(FiltersPanel, { filters: pending, onChange: setPending, onApply: handleFiltersApply, onReset: handleFiltersReset, disabled: loadingDocs }), _jsxs("div", { className: "rag-results", children: [_jsx(Tabs, { active: tab, onChange: handleTabChange, counts: counts }), loadingDocs && (_jsxs(_Fragment, { children: [_jsx("div", { className: "rag-skeleton" }), _jsx("div", { className: "rag-skeleton" }), _jsx("div", { className: "rag-skeleton" })] })), !loadingDocs && tab === 'decisions' && (_jsxs(_Fragment, { children: [pagedDocs.length === 0 && (_jsx("div", { className: "rag-no-results", children: "Brak decyzji dla tego zapytania." })), pagedDocs.map((doc, i) => (_jsx(DocumentCard, { doc: doc, onClick: onDocumentClick }, doc.doc_id ?? `${doc.signature}-${i}`))), _jsx(Pagination, { page: safePage, totalPages: decisions.length > PER_PAGE ? totalPages : 0, onPage: setPage })] })), !loadingDocs && tab === 'act' && (_jsxs(_Fragment, { children: [actDocs.length === 0 && (_jsx("div", { className: "rag-no-results", children: "Brak artyku\u0142\u00F3w u.o.d.o. dla tego zapytania." })), actDocs.map((doc, i) => (_jsx(ArticleCard, { doc: doc }, doc.doc_id ?? `act-${i}`)))] })), !loadingDocs && tab === 'rodo' && (_jsxs(_Fragment, { children: [gdprDocs.length === 0 && (_jsx("div", { className: "rag-no-results", children: "Brak artyku\u0142\u00F3w RODO dla tego zapytania." })), gdprDocs.map((doc, i) => (_jsx(ArticleCard, { doc: doc }, doc.doc_id ?? `gdpr-${i}`)))] }))] })] }))] }));
}

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Document, Filters } from './api'
import { useSearch } from './hooks/useSearch'
import { FiltersPanel } from './FiltersPanel'
import { SearchInput } from './SearchInput'

// ─────────────────────────── TYPY ────────────────────────────────

export interface UodoRagWidgetProps {
  apiUrl?:   string
  provider?: string
  model?:    string
  useLLM?:   boolean
  onDocumentClick?: (doc: Document) => void
}

type TabId = 'decisions' | 'act' | 'rodo'

const PER_PAGE = 10

// ─────────────────────────── STATUS HELPERS ──────────────────────

function statusClass(status?: string): string {
  if (!status) return 'status-unknown'
  const s = status.toLowerCase()
  if (s.includes('prawomocna') && !s.includes('nie')) return 'status-final'
  if (s.includes('nieprawomocna'))                     return 'status-nonfinal'
  if (s.includes('uchylona'))                          return 'status-repealed'
  return 'status-unknown'
}

function statusLabel(status?: string): string {
  if (!status) return ''
  const s = status.toLowerCase()
  if (s.includes('prawomocna') && !s.includes('nie')) return 'prawomocna'
  if (s.includes('nieprawomocna'))                     return 'nieprawomocna'
  if (s.includes('uchylona'))                          return 'uchylona'
  return status
}

// ─────────────────────────── KARTA DECYZJI ───────────────────────

function DocumentCard({
  doc,
  onClick,
}: {
  doc:      Document
  onClick?: (doc: Document) => void
}) {
  const handleClick = () => {
    if (onClick) {
      onClick(doc)
    } else if (doc.signature) {
      window.open(`/?doc=${encodeURIComponent(doc.signature)}`, '_blank', 'noopener')
    }
  }

  return (
    <article
      className="doc-list-item"
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick()}
      aria-label={`Otwórz decyzję ${doc.signature}`}
    >
      <header>
        <span className="doc-signature">{doc.signature}</span>
        <div className="doc-meta">
          {doc.graph_relation && (
            <span className="doc-graph-rel">{doc.graph_relation}</span>
          )}
          {doc.status && (
            <span className={`status-badge ${statusClass(doc.status)}`}>
              {statusLabel(doc.status)}
            </span>
          )}
          {doc.year && <time dateTime={String(doc.year)}><small>{doc.year}</small></time>}
        </div>
      </header>
      <main>
        {doc.title_full && <h2>{doc.title_full}</h2>}
        {doc.section_title && (
          <span className="doc-section">Sekcja: {doc.section_title}</span>
        )}
        {doc.content_text && (
          <p className="doc-excerpt">{doc.content_text.slice(0, 280)}…</p>
        )}
      </main>
      {doc.keywords.length > 0 && (
        <footer>
          <div className="ui-result-tags">
            {doc.keywords.slice(0, 6).map((kw, i) => (
              <span key={`${kw}-${i}`} className="ui-result-tag">{kw}</span>
            ))}
          </div>
        </footer>
      )}
    </article>
  )
}

// ─────────────────────────── KARTA ARTYKUŁU ──────────────────────

const ACT_URL  = 'https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20190001781'
const RODO_URL = 'https://eur-lex.europa.eu/legal-content/PL/TXT/HTML/?uri=CELEX:32016R0679'

function ArticleCard({ doc }: { doc: Document }) {
  const [expanded, setExpanded] = useState(false)

  const isAct      = doc.doc_type === 'legal_act_article'
  const isRecital  = doc.doc_type === 'gdpr_recital'
  const sourceUrl  = isAct ? ACT_URL : RODO_URL

  const label = isAct
    ? `Art. ${doc.article_num} u.o.d.o.`
    : isRecital
      ? `Motyw ${doc.article_num} RODO`
      : `Art. ${doc.article_num} RODO`

  const sourceName = isAct
    ? 'Ustawa o ochronie danych osobowych (ISAP)'
    : 'RODO — EUR-Lex'

  return (
    <article className="doc-list-item doc-list-item--article">
      <header>
        <span className="doc-signature">{label}</span>
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="doc-source-link"
          onClick={(e) => e.stopPropagation()}
          title={`Otwórz ${sourceName}`}
        >
          Źródło →
        </a>
      </header>

      <main>
        {expanded ? (
          <div className="doc-article-text">
            <ReactMarkdown>{doc.content_text ?? ''}</ReactMarkdown>
          </div>
        ) : (
          <p className="doc-excerpt">{(doc.content_text ?? '').slice(0, 300)}…</p>
        )}
      </main>

      <footer style={{ borderTop: 'none', paddingTop: 0 }}>
        <button
          className="doc-expand-btn"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? '▲ Zwiń' : '▼ Pokaż pełny tekst'}
        </button>
      </footer>
    </article>
  )
}

// ─────────────────────────── ZAKŁADKI ────────────────────────────

function Tabs({
  active,
  onChange,
  counts,
}: {
  active:   TabId
  onChange: (t: TabId) => void
  counts:   Record<TabId, number>
}) {
  const tabs: { id: TabId; label: string }[] = [
    { id: 'decisions', label: 'Decyzje UODO' },
    { id: 'act',       label: 'Ustawa u.o.d.o.' },
    { id: 'rodo',      label: 'RODO' },
  ]

  return (
    <div className="rag-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          className={`rag-tab ${active === t.id ? 'rag-tab--active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {counts[t.id] > 0 && (
            <span className="rag-tab-count">{counts[t.id]}</span>
          )}
        </button>
      ))}
    </div>
  )
}

// ─────────────────────────── PAGINACJA ───────────────────────────

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page:       number
  totalPages: number
  onPage:     (p: number) => void
}) {
  if (totalPages <= 1) return null

  const pages: (number | '…')[] = []
  const range = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, i) => from + i)

  if (totalPages <= 7) {
    pages.push(...range(1, totalPages))
  } else {
    pages.push(1)
    if (page > 3) pages.push('…')
    pages.push(...range(Math.max(2, page - 1), Math.min(totalPages - 1, page + 1)))
    if (page < totalPages - 2) pages.push('…')
    pages.push(totalPages)
  }

  return (
    <nav className="rag-pagination" aria-label="Paginacja wyników">
      <button
        className="rag-page-btn"
        onClick={() => onPage(page - 1)}
        disabled={page === 1}
      >‹</button>

      {pages.map((p, i) =>
        p === '…' ? (
          <span key={`e-${i}`} className="rag-page-ellipsis">…</span>
        ) : (
          <button
            key={p}
            className={`rag-page-btn ${p === page ? 'rag-page-btn--active' : ''}`}
            onClick={() => onPage(p as number)}
            aria-current={p === page ? 'page' : undefined}
          >{p}</button>
        )
      )}

      <button
        className="rag-page-btn"
        onClick={() => onPage(page + 1)}
        disabled={page === totalPages}
      >›</button>
    </nav>
  )
}

// ─────────────────────────── AKTYWNE FILTRY ──────────────────────

function ActiveFilters({
  filters,
  onRemove,
}: {
  filters:  Filters
  onRemove: (key: keyof Filters, value?: string) => void
}) {
  const items: { key: keyof Filters; label: string; value?: string }[] = []

  if (filters.status)    items.push({ key: 'status',    label: `Status: ${filters.status}` })
  if (filters.year_from) items.push({ key: 'year_from', label: `Od: ${filters.year_from}` })
  if (filters.year_to)   items.push({ key: 'year_to',   label: `Do: ${filters.year_to}` })

  const listKeys: (keyof Filters)[] = [
    'term_decision_type', 'term_sector',
    'term_corrective_measure', 'term_violation_type',
  ]
  for (const key of listKeys) {
    for (const v of (filters[key] as string[] | undefined) ?? []) {
      items.push({ key, label: v, value: v })
    }
  }

  if (!items.length) return null

  return (
    <div className="rag-active-filters">
      {items.map((item, i) => (
        <span key={i} className="rag-active-filter-tag">
          {item.label}
          <button onClick={() => onRemove(item.key, item.value)}>×</button>
        </span>
      ))}
    </div>
  )
}

// ─────────────────────────── GŁÓWNY KOMPONENT ────────────────────

export function UodoRagWidget({
  provider = 'Ollama',
  model    = 'mistral-large-3:675b-cloud',
  useLLM   = true,
  onDocumentClick,
}: UodoRagWidgetProps) {
  const [query,   setQuery]   = useState('')
  const [filters, setFilters] = useState<Filters>({})
  const [pending, setPending] = useState<Filters>({})
  const [tab,     setTab]     = useState<TabId>('decisions')
  const [page,    setPage]    = useState(1)

  const {
    allDocs, tags, answer, searchTime, total,
    loadingDocs, loadingAnswer, error,
    search, stopStream,
  } = useSearch({ provider, model, useLLM })

  // ── Podział wyników na typy ──
  const decisions = allDocs.filter((d) => d.doc_type === 'uodo_decision')
  const actDocs   = allDocs.filter((d) => d.doc_type === 'legal_act_article')
  const gdprDocs  = allDocs.filter((d) => d.doc_type === 'gdpr_article' || d.doc_type === 'gdpr_recital')

  const counts: Record<TabId, number> = {
    decisions: decisions.length,
    act:       actDocs.length,
    rodo:      gdprDocs.length,
  }

  // ── Paginacja decyzji ──
  const totalPages  = Math.max(1, Math.ceil(decisions.length / PER_PAGE))
  const safePage    = Math.min(Math.max(1, page), totalPages)
  const pagedDocs   = decisions.slice((safePage - 1) * PER_PAGE, safePage * PER_PAGE)

  const hasResults = allDocs.length > 0 || loadingDocs

  const handleSearch = (overrideFilters?: Filters, overrideQuery?: string) => {
    const q = overrideQuery ?? query
    if (!q.trim()) return
    const f = overrideFilters ?? filters
    setFilters(f)
    setPage(1)
    search(q, f)
  }

  const handleTabChange = (t: TabId) => {
    setTab(t)
    setPage(1)
  }

  const handleFiltersApply = () => {
    setFilters(pending)
    setPage(1)
    search(query, pending)
  }

  const handleFiltersReset = () => {
    setPending({})
    setFilters({})
    setPage(1)
    if (query.trim()) search(query, {})
  }

  const removeFilter = (key: keyof Filters, value?: string) => {
    let next: Filters
    if (value) {
      const current = (filters[key] as string[] | undefined) ?? []
      next = { ...filters, [key]: current.filter((v) => v !== value) }
      if (!(next[key] as string[]).length) delete next[key]
    } else {
      next = { ...filters }
      delete next[key]
    }
    setFilters(next)
    setPending(next)
    setPage(1)
    if (query.trim()) search(query, next)
  }

  return (
    <div className="uodo-rag-widget">

      {/* ── Pole wyszukiwania ── */}
      <div className="rag-search-card">
        <h2>Wyszukiwarka decyzji UODO z AI</h2>
        <div className="rag-search-bar">
          <SearchInput
            value={query}
            onChange={setQuery}
            onSearch={(q) => handleSearch(undefined, q)}
            disabled={loadingDocs}
          />
          <button
            onClick={() => handleSearch()}
            disabled={loadingDocs || !query.trim()}
            className="rag-search-btn"
          >
            {loadingDocs ? 'Szukam…' : 'Szukaj'}
          </button>
        </div>
      </div>

      {/* ── Błąd ── */}
      {error && <div className="rag-error" role="alert">{error}</div>}

      {/* ── Odpowiedź AI ── */}
      {(answer || loadingAnswer) && (
        <div className="rag-answer">
          <div className="rag-answer-header">
            <span>Odpowiedź AI</span>
            {loadingAnswer && (
              <button onClick={stopStream} className="rag-stop-btn">Zatrzymaj</button>
            )}
          </div>
          <div className="rag-answer-body">
            <ReactMarkdown>{answer}</ReactMarkdown>
            {loadingAnswer && <span className="rag-cursor">▋</span>}
          </div>
        </div>
      )}

      {/* ── Aktywne filtry ── */}
      <ActiveFilters filters={filters} onRemove={removeFilter} />

      {/* ── Statystyki ── */}
      {total > 0 && !loadingDocs && (
        <p className="rag-stats">
          {total} dokumentów · {searchTime.toFixed(2)}s
          {tags.length > 0 && <> · tagi: {tags.slice(0, 4).join(', ')}</>}
        </p>
      )}

      {/* ── Główny layout ── */}
      {hasResults && (
        <div className="rag-layout">

          {/* ── Sidebar z filtrami ── */}
          <FiltersPanel
            filters={pending}
            onChange={setPending}
            onApply={handleFiltersApply}
            onReset={handleFiltersReset}
            disabled={loadingDocs}
          />

          {/* ── Wyniki z zakładkami ── */}
          <div className="rag-results">

            {/* Zakładki */}
            <Tabs active={tab} onChange={handleTabChange} counts={counts} />

            {/* Loading skeleton */}
            {loadingDocs && (
              <>
                <div className="rag-skeleton" />
                <div className="rag-skeleton" />
                <div className="rag-skeleton" />
              </>
            )}

            {/* ── Zakładka: Decyzje ── */}
            {!loadingDocs && tab === 'decisions' && (
              <>
                {pagedDocs.length === 0 && (
                  <div className="rag-no-results">Brak decyzji dla tego zapytania.</div>
                )}
                {pagedDocs.map((doc, i) => (
                  <DocumentCard
                    key={doc.doc_id ?? `${doc.signature}-${i}`}
                    doc={doc}
                    onClick={onDocumentClick}
                  />
                ))}
                <Pagination
                  page={safePage}
                  totalPages={decisions.length > PER_PAGE ? totalPages : 0}
                  onPage={setPage}
                />
              </>
            )}

            {/* ── Zakładka: Ustawa u.o.d.o. ── */}
            {!loadingDocs && tab === 'act' && (
              <>
                {actDocs.length === 0 && (
                  <div className="rag-no-results">Brak artykułów u.o.d.o. dla tego zapytania.</div>
                )}
                {actDocs.map((doc, i) => (
                  <ArticleCard key={doc.doc_id ?? `act-${i}`} doc={doc} />
                ))}
              </>
            )}

            {/* ── Zakładka: RODO ── */}
            {!loadingDocs && tab === 'rodo' && (
              <>
                {gdprDocs.length === 0 && (
                  <div className="rag-no-results">Brak artykułów RODO dla tego zapytania.</div>
                )}
                {gdprDocs.map((doc, i) => (
                  <ArticleCard key={doc.doc_id ?? `gdpr-${i}`} doc={doc} />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

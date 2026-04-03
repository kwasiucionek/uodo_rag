import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ─────────────────────────── TYPY ────────────────────────────────

interface Section {
  section_title: string
  section_id:    string
  chunk_index:   number
  content_text:  string
}

interface RefEntry {
  urn:       string
  signature: string
  category:  string
  display?:  string
}

interface FullDocument {
  signature:               string
  title?:                  string
  title_full?:             string
  status?:                 string
  year?:                   number
  source_url?:             string
  keywords:                string[]
  related_acts:            string[]
  related_eu_acts:         string[]
  related_uodo_rulings:    string[]
  related_court_rulings:   string[]
  term_decision_type:      string[]
  term_violation_type:     string[]
  term_corrective_measure: string[]
  term_sector:             string[]
  refs_full:               RefEntry[]
  sections:                Section[]
}

interface DocumentViewProps {
  signature: string
  onBack:    () => void
}

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
function urnToUrl(urn: string, signature: string): string | null {
  // NSA — Centralna Baza Orzeczeń Sądów Administracyjnych
  if (urn.startsWith('urn:ndoc:court:pl:sa:')) {
    return `https://orzeczenia.nsa.gov.pl/cbo/find?cboPhrases=${encodeURIComponent(signature)}`
  }

  // Sądy powszechne — Portal MS z własnym enkodowaniem sygnatury
  if (urn.startsWith('urn:ndoc:court:pl:sp:')) {
    const encoded = signature.split('').map((c) => {
      if (c === ' ') return '$0020'
      if (c === '/') return '$002f'
      return c
    }).join('')
    return `https://orzeczenia.ms.gov.pl/search/advanced/$N/${encoded}/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/$N/1`
  }

  // Sąd Najwyższy
  if (urn.startsWith('urn:ndoc:court:pl:sn:')) {
    return `https://www.sn.pl/sites/orzecznictwo/Orzeczenia3/${encodeURIComponent(signature)}.pdf`
  }

  // TSUE → Curia
  if (urn.startsWith('urn:ndoc:court:eu:tsue:')) {
    return `https://curia.europa.eu/juris/liste.jsf?num=${encodeURIComponent(signature)}`
  }

  // EDPB
  if (urn.startsWith('urn:ndoc:gov:eu:edpb:')) {
    return 'https://edpb.europa.eu/our-work-tools/our-documents_pl'
  }

  // Decyzje UODO → widget
  if (urn.startsWith('urn:ndoc:gov:pl:uodo:')) {
    return `/?doc=${encodeURIComponent(signature)}`
  }

  // ISAP (akty PL i TK)
  if (urn.startsWith('urn:ndoc:pro:pl:') || urn.startsWith('urn:ndoc:court:pl:tk:')) {
    const m = signature.match(/Dz\.U\.\s*(\d{4})\s*poz\.\s*(\d+)/)
    if (m) {
      return `https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU${m[1]}${m[2].padStart(7, '0')}`
    }
    // fallback — szukaj po tytule
    const durp = urn.match(/durp:(\d{4}):(\d+)/)
    if (durp) {
      return `https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU${durp[1]}${durp[2].padStart(7, '0')}`
    }
    return null
  }

  // EUR-Lex (akty UE i TSUE przez CELEX)
  if (urn.startsWith('urn:ndoc:pro:eu:')) {
    const m = signature.match(/EU\s+(\d{4})\/(\d+)/)
    if (m) {
      return `https://eur-lex.europa.eu/legal-content/PL/TXT/?uri=CELEX:3${m[1]}R${m[2].padStart(4, '0')}`
    }
    return null
  }

  return null
}

// ─────────────────────────── HELPERS ─────────────────────────────

function statusClass(status?: string): string {
  if (!status) return 'status-unknown'
  const s = status.toLowerCase()
  if (s.includes('prawomocna') && !s.includes('nie')) return 'status-final'
  if (s.includes('nieprawomocna'))                     return 'status-nonfinal'
  if (s.includes('uchylona'))                          return 'status-repealed'
  return 'status-unknown'
}

// ─────────────────────────── SEKCJA REFERENCJI ───────────────────

const CATEGORY_LABELS: Record<string, string> = {
  act:          'Akty prawne (PL)',
  eu_act:       'Akty prawne (UE)',
  uodo_ruling:  'Decyzje UODO',
  court_ruling: 'Orzeczenia sądów',
  eu_ruling:    'Orzeczenia TSUE',
  edpb:         'Wytyczne EROD',
}

const CATEGORY_ORDER = ['uodo_ruling', 'act', 'eu_act', 'court_ruling', 'eu_ruling', 'edpb']

function RefsSection({ refs }: { refs: RefEntry[] }) {
  if (!refs.length) return null

  // Grupowanie po kategorii
  const groups: Record<string, RefEntry[]> = {}
  for (const ref of refs) {
    const cat = ref.category || 'other'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(ref)
  }

  const orderedCats = [
    ...CATEGORY_ORDER.filter((c) => groups[c]),
    ...Object.keys(groups).filter((c) => !CATEGORY_ORDER.includes(c)),
  ]

  return (
    <aside className="doc-view-refs">
      <h3 className="doc-view-refs-title">Powołane dokumenty</h3>
      {orderedCats.map((cat) => (
        <div key={cat} className="doc-view-refs-group">
          <h4>{CATEGORY_LABELS[cat] ?? cat}</h4>
          <ul>
            {groups[cat].map((entry) => {
              const url   = urnToUrl(entry.urn, entry.signature)
              const label = entry.display || entry.signature
              return (
                <li key={entry.urn}>
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="doc-ref-link"
                      title={`Otwórz: ${label}`}
                    >
                      {label}
                      <span className="doc-ref-arrow">↗</span>
                    </a>
                  ) : (
                    <span>{label}</span>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </aside>
  )
}

// ─────────────────────────── NAWIGACJA SEKCJI ────────────────────

function SectionNav({
  sections,
  active,
  onSelect,
}: {
  sections: Section[]
  active:   number
  onSelect: (i: number) => void
}) {
  if (sections.length <= 1) return null
  return (
    <nav className="doc-view-nav" aria-label="Sekcje dokumentu">
      {sections.map((s, i) => (
        <button
          key={i}
          className={`doc-view-nav-item ${active === i ? 'doc-view-nav-item--active' : ''}`}
          onClick={() => onSelect(i)}
          title={s.section_title || `Sekcja ${i + 1}`}
        >
          <span className="doc-view-nav-num">{i + 1}</span>
          <span className="doc-view-nav-label">
            {s.section_title || `Sekcja ${i + 1}`}
          </span>
        </button>
      ))}
    </nav>
  )
}

// ─────────────────────────── GŁÓWNY KOMPONENT ────────────────────

export function DocumentView({ signature, onBack }: DocumentViewProps) {
  const [doc,     setDoc]     = useState<FullDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [active,  setActive]  = useState(0)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setActive(0)
    fetch(`${API_URL}/api/document?signature=${encodeURIComponent(signature)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: FullDocument) => {
        setDoc(data)
        setLoading(false)
      })
      .catch((e) => {
        setError(String(e))
        setLoading(false)
      })
  }, [signature])

  // Nawigacja klawiaturą ← →
  useEffect(() => {
    if (!doc) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') setActive((a) => Math.min(a + 1, doc.sections.length - 1))
      if (e.key === 'ArrowLeft')  setActive((a) => Math.max(a - 1, 0))
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [doc])

  if (loading) return (
    <div className="uodo-rag-widget">
      <div className="rag-skeleton" style={{ height: 60, marginBottom: 8 }} />
      <div className="rag-skeleton" style={{ height: 300 }} />
    </div>
  )

  if (error || !doc) return (
    <div className="uodo-rag-widget">
      <div className="rag-error">Nie udało się wczytać dokumentu: {error}</div>
      <button className="doc-view-back" onClick={onBack}>← Wróć do wyników</button>
    </div>
  )

  const hasRefs = doc.refs_full?.length > 0

  const section    = doc.sections[active]
  const isFirst    = active === 0
  const isLast     = active === doc.sections.length - 1
  const totalSecs  = doc.sections.length

  return (
    <div className="uodo-rag-widget">

      {/* ── Przycisk powrotu ── */}
      <button className="doc-view-back" onClick={onBack}>
        ← Wróć do wyników
      </button>

      {/* ── Nagłówek ── */}
      <div className="doc-view-header">
        <div className="doc-view-header-top">
          <h1 className="doc-view-signature">{doc.signature}</h1>
          <div className="doc-view-header-meta">
            {doc.status && (
              <span className={`status-badge ${statusClass(doc.status)}`}>
                {doc.status}
              </span>
            )}
            {doc.year && <span className="doc-view-year">{doc.year}</span>}
          </div>
        </div>

        {doc.title_full && <p className="doc-view-title">{doc.title_full}</p>}

        {doc.keywords.length > 0 && (
          <div className="ui-result-tags" style={{ marginTop: '0.75rem' }}>
            {doc.keywords.map((kw, i) => (
              <span key={`${kw}-${i}`} className="ui-result-tag">{kw}</span>
            ))}
          </div>
        )}

        {doc.source_url && (
          <a
            href={doc.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="doc-view-portal-link"
          >
            Otwórz na portalu orzeczenia.uodo.gov.pl →
          </a>
        )}
      </div>

      {/* ── Body: nawigacja + treść + referencje ── */}
      <div className="doc-view-body">

        {/* ── Nawigacja sekcji ── */}
        <SectionNav
          sections={doc.sections}
          active={active}
          onSelect={setActive}
        />

        {/* ── Treść sekcji ── */}
        <div className="doc-view-content">
          {section && (
            <>
              {/* Nagłówek sekcji z licznikiem */}
              <div className="doc-view-section-header">
                <h2 className="doc-view-section-title">
                  {section.section_title || `Sekcja ${active + 1}`}
                </h2>
                {totalSecs > 1 && (
                  <span className="doc-view-section-counter">
                    {active + 1} / {totalSecs}
                  </span>
                )}
              </div>

              {/* Treść */}
              <div className="doc-view-section-text">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {section.content_text}
                </ReactMarkdown>
              </div>

              {/* Poprzednia / Następna */}
              {totalSecs > 1 && (
                <div className="doc-view-section-nav-btns">
                  <button
                    className="doc-view-nav-prev"
                    onClick={() => setActive((a) => a - 1)}
                    disabled={isFirst}
                  >
                    ← Poprzednia sekcja
                  </button>
                  <button
                    className="doc-view-nav-next"
                    onClick={() => setActive((a) => a + 1)}
                    disabled={isLast}
                  >
                    Następna sekcja →
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── Referencje ── */}
        {hasRefs && <RefsSection refs={doc.refs_full} />}
      </div>
    </div>
  )
}

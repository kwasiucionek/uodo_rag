import { useEffect, useRef, useState } from 'react'
import { useSuggest } from './hooks/useSuggest'

interface SearchInputProps {
  value:       string
  onChange:    (v: string) => void
  onSearch:    (q: string) => void
  disabled?:   boolean
  placeholder?: string
}

/**
 * Pole wyszukiwania z autouzupełnianiem.
 *
 * - Dropdown pojawia się po wpisaniu ≥2 znaków
 * - Dwie sekcje: Tagi i Sygnatury
 * - Nawigacja klawiaturą: ↑↓ wybiera, Enter zatwierdza, Escape zamyka
 * - Kliknięcie poza dropdownem zamyka go
 */
export function SearchInput({
  value,
  onChange,
  onSearch,
  disabled   = false,
  placeholder = 'Wpisz treść, sygnaturę lub temat...',
}: SearchInputProps) {
  const [open,    setOpen]    = useState(false)
  const [active,  setActive]  = useState(-1)   // indeks aktywnej pozycji

  const { results, total } = useSuggest(value)

  const inputRef    = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Płaska lista wszystkich pozycji (tagi + sygnatury)
  const allItems: { label: string; type: 'tag' | 'signature' }[] = [
    ...results.tags.map((t)       => ({ label: t, type: 'tag'       as const })),
    ...results.signatures.map((s) => ({ label: s, type: 'signature' as const })),
  ]

  // Otwórz dropdown gdy są wyniki
  useEffect(() => {
    setActive(-1)
    setOpen(total > 0 && value.trim().length >= 2)
  }, [total, value])

  // Zamknij po kliknięciu poza
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        !inputRef.current?.contains(e.target as Node) &&
        !dropdownRef.current?.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selectItem = (label: string) => {
    onChange(label)
    setOpen(false)
    onSearch(label)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) {
      if (e.key === 'Enter') onSearch(value)
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, allItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (active >= 0 && allItems[active]) {
        selectItem(allItems[active].label)
      } else {
        setOpen(false)
        onSearch(value)
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
      setActive(-1)
    }
  }

  return (
    <div className="rag-suggest-wrapper">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => total > 0 && setOpen(true)}
        placeholder={placeholder}
        className="rag-search-input"
        disabled={disabled}
        aria-label="Wyszukaj decyzje UODO"
        aria-autocomplete="list"
        aria-expanded={open}
        autoComplete="off"
      />

      {open && (
        <div
          ref={dropdownRef}
          className="rag-suggest-dropdown"
          role="listbox"
        >
          {/* ── Tagi ── */}
          {results.tags.length > 0 && (
            <div className="rag-suggest-group">
              <div className="rag-suggest-group-label">Tagi</div>
              {results.tags.map((tag, i) => {
                const idx = i
                return (
                  <div
                    key={tag}
                    role="option"
                    aria-selected={active === idx}
                    className={`rag-suggest-item rag-suggest-item--tag ${active === idx ? 'rag-suggest-item--active' : ''}`}
                    onMouseDown={(e) => { e.preventDefault(); selectItem(tag) }}
                    onMouseEnter={() => setActive(idx)}
                  >
                    <span className="rag-suggest-icon">🏷</span>
                    <span className="rag-suggest-label">{tag}</span>
                  </div>
                )
              })}
            </div>
          )}

          {/* ── Sygnatury ── */}
          {results.signatures.length > 0 && (
            <div className="rag-suggest-group">
              <div className="rag-suggest-group-label">Sygnatury</div>
              {results.signatures.map((sig, i) => {
                const idx = results.tags.length + i
                return (
                  <div
                    key={sig}
                    role="option"
                    aria-selected={active === idx}
                    className={`rag-suggest-item rag-suggest-item--sig ${active === idx ? 'rag-suggest-item--active' : ''}`}
                    onMouseDown={(e) => { e.preventDefault(); selectItem(sig) }}
                    onMouseEnter={() => setActive(idx)}
                  >
                    <span className="rag-suggest-icon">📄</span>
                    <span className="rag-suggest-label">{sig}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

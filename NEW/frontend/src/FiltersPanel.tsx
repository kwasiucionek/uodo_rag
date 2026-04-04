import { useEffect, useState } from 'react'
import { api, Filters, Taxonomy } from './api'

interface FiltersPanelProps {
  filters:   Filters
  onChange:  (filters: Filters) => void
  onApply:   () => void
  onReset:   () => void
  disabled?: boolean
}

const STATUS_OPTIONS = [
  { value: '',               label: 'Wszystkie' },
  { value: 'prawomocna',     label: 'Prawomocna' },
  { value: 'nieprawomocna',  label: 'Nieprawomocna' },
]

const CURRENT_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: CURRENT_YEAR - 2018 + 1 }, (_, i) => CURRENT_YEAR - i)

export function FiltersPanel({
  filters,
  onChange,
  onApply,
  onReset,
  disabled = false,
}: FiltersPanelProps) {
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [open,     setOpen]     = useState<Record<string, boolean>>({
    status:   true,
    year:     true,
    decision: false,
    sector:   false,
    remedy:   false,
    violation: false,
  })

  useEffect(() => {
    api.taxonomy().then(setTaxonomy).catch(() => {})
  }, [])

  const set = (key: keyof Filters, value: unknown) => {
    onChange({ ...filters, [key]: value || undefined })
  }

  const toggleList = (key: keyof Filters, value: string) => {
    const current = (filters[key] as string[] | undefined) ?? []
    const next    = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value]
    onChange({ ...filters, [key]: next.length ? next : undefined })
  }

  const isChecked = (key: keyof Filters, value: string) =>
    ((filters[key] as string[] | undefined) ?? []).includes(value)

  const hasFilters = Object.values(filters).some((v) =>
    Array.isArray(v) ? v.length > 0 : !!v
  )

  const toggle = (key: string) =>
    setOpen((s) => ({ ...s, [key]: !s[key] }))

  return (
    <aside className="rag-sidebar">
      <div className="rag-sidebar-header">
        <span className="rag-sidebar-title">Filtry</span>
        {hasFilters && (
          <button className="rag-filter-reset" onClick={onReset} disabled={disabled}>
            Wyczyść
          </button>
        )}
      </div>

      {/* ── Status ── */}
      <FilterGroup
        label="Status"
        open={open.status}
        onToggle={() => toggle('status')}
      >
        {STATUS_OPTIONS.map((opt) => (
          <label key={opt.value} className="rag-filter-radio">
            <input
              type="radio"
              name="status"
              value={opt.value}
              checked={(filters.status ?? '') === opt.value}
              onChange={() => set('status', opt.value)}
              disabled={disabled}
            />
            <span>{opt.label}</span>
          </label>
        ))}
      </FilterGroup>

      {/* ── Rok ── */}
      <FilterGroup
        label="Rok wydania"
        open={open.year}
        onToggle={() => toggle('year')}
      >
        <div className="rag-filter-year-row">
          <select
            className="rag-filter-select"
            value={filters.year_from ?? ''}
            onChange={(e) => set('year_from', e.target.value ? Number(e.target.value) : undefined)}
            disabled={disabled}
          >
            <option value="">Od roku</option>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <select
            className="rag-filter-select"
            value={filters.year_to ?? ''}
            onChange={(e) => set('year_to', e.target.value ? Number(e.target.value) : undefined)}
            disabled={disabled}
          >
            <option value="">Do roku</option>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      </FilterGroup>

      {/* ── Rodzaj decyzji ── */}
      {taxonomy?.term_decision_type?.length ? (
        <FilterGroup
          label="Rodzaj decyzji"
          open={open.decision}
          onToggle={() => toggle('decision')}
        >
          {taxonomy.term_decision_type.map((v) => (
            <CheckItem
              key={v}
              label={v}
              checked={isChecked('term_decision_type', v)}
              onChange={() => toggleList('term_decision_type', v)}
              disabled={disabled}
            />
          ))}
        </FilterGroup>
      ) : null}

      {/* ── Sektor ── */}
      {taxonomy?.term_sector?.length ? (
        <FilterGroup
          label="Sektor"
          open={open.sector}
          onToggle={() => toggle('sector')}
        >
          {taxonomy.term_sector.map((v) => (
            <CheckItem
              key={v}
              label={v}
              checked={isChecked('term_sector', v)}
              onChange={() => toggleList('term_sector', v)}
              disabled={disabled}
            />
          ))}
        </FilterGroup>
      ) : null}

      {/* ── Środek naprawczy ── */}
      {taxonomy?.term_corrective_measure?.length ? (
        <FilterGroup
          label="Środek naprawczy"
          open={open.remedy}
          onToggle={() => toggle('remedy')}
        >
          {taxonomy.term_corrective_measure.map((v) => (
            <CheckItem
              key={v}
              label={v}
              checked={isChecked('term_corrective_measure', v)}
              onChange={() => toggleList('term_corrective_measure', v)}
              disabled={disabled}
            />
          ))}
        </FilterGroup>
      ) : null}

      {/* ── Rodzaj naruszenia ── */}
      {taxonomy?.term_violation_type?.length ? (
        <FilterGroup
          label="Rodzaj naruszenia"
          open={open.violation}
          onToggle={() => toggle('violation')}
        >
          {taxonomy.term_violation_type.map((v) => (
            <CheckItem
              key={v}
              label={v}
              checked={isChecked('term_violation_type', v)}
              onChange={() => toggleList('term_violation_type', v)}
              disabled={disabled}
            />
          ))}
        </FilterGroup>
      ) : null}

      {/* ── Przycisk szukaj ── */}
      <button
        className="rag-filter-apply"
        onClick={onApply}
        disabled={disabled}
      >
        {disabled ? 'Szukam…' : 'Zastosuj filtry'}
      </button>
    </aside>
  )
}

// ─────────────────────────── HELPERS ────────────────────────────

function FilterGroup({
  label,
  open,
  onToggle,
  children,
}: {
  label:    string
  open:     boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="rag-filter-group">
      <button className="rag-filter-group-header" onClick={onToggle}>
        <span>{label}</span>
        <span className="rag-filter-chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="rag-filter-group-body">{children}</div>}
    </div>
  )
}

function CheckItem({
  label,
  checked,
  onChange,
  disabled,
}: {
  label:    string
  checked:  boolean
  onChange: () => void
  disabled: boolean
}) {
  return (
    <label className="rag-filter-check">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span>{label}</span>
    </label>
  )
}

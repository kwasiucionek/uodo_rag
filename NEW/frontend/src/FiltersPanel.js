import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from './api';
const STATUS_OPTIONS = [
    { value: '', label: 'Wszystkie' },
    { value: 'prawomocna', label: 'Prawomocna' },
    { value: 'nieprawomocna', label: 'Nieprawomocna' },
];
const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: CURRENT_YEAR - 2018 + 1 }, (_, i) => CURRENT_YEAR - i);
export function FiltersPanel({ filters, onChange, onApply, onReset, disabled = false, }) {
    const [taxonomy, setTaxonomy] = useState(null);
    const [open, setOpen] = useState({
        status: true,
        year: true,
        decision: false,
        sector: false,
        remedy: false,
        violation: false,
    });
    useEffect(() => {
        api.taxonomy().then(setTaxonomy).catch(() => { });
    }, []);
    const set = (key, value) => {
        onChange({ ...filters, [key]: value || undefined });
    };
    const toggleList = (key, value) => {
        const current = filters[key] ?? [];
        const next = current.includes(value)
            ? current.filter((v) => v !== value)
            : [...current, value];
        onChange({ ...filters, [key]: next.length ? next : undefined });
    };
    const isChecked = (key, value) => (filters[key] ?? []).includes(value);
    const hasFilters = Object.values(filters).some((v) => Array.isArray(v) ? v.length > 0 : !!v);
    const toggle = (key) => setOpen((s) => ({ ...s, [key]: !s[key] }));
    return (_jsxs("aside", { className: "rag-sidebar", children: [_jsxs("div", { className: "rag-sidebar-header", children: [_jsx("span", { className: "rag-sidebar-title", children: "Filtry" }), hasFilters && (_jsx("button", { className: "rag-filter-reset", onClick: onReset, disabled: disabled, children: "Wyczy\u015B\u0107" }))] }), _jsx(FilterGroup, { label: "Status", open: open.status, onToggle: () => toggle('status'), children: STATUS_OPTIONS.map((opt) => (_jsxs("label", { className: "rag-filter-radio", children: [_jsx("input", { type: "radio", name: "status", value: opt.value, checked: (filters.status ?? '') === opt.value, onChange: () => set('status', opt.value), disabled: disabled }), _jsx("span", { children: opt.label })] }, opt.value))) }), _jsx(FilterGroup, { label: "Rok wydania", open: open.year, onToggle: () => toggle('year'), children: _jsxs("div", { className: "rag-filter-year-row", children: [_jsxs("select", { className: "rag-filter-select", value: filters.year_from ?? '', onChange: (e) => set('year_from', e.target.value ? Number(e.target.value) : undefined), disabled: disabled, children: [_jsx("option", { value: "", children: "Od roku" }), YEARS.map((y) => _jsx("option", { value: y, children: y }, y))] }), _jsxs("select", { className: "rag-filter-select", value: filters.year_to ?? '', onChange: (e) => set('year_to', e.target.value ? Number(e.target.value) : undefined), disabled: disabled, children: [_jsx("option", { value: "", children: "Do roku" }), YEARS.map((y) => _jsx("option", { value: y, children: y }, y))] })] }) }), taxonomy?.term_decision_type?.length ? (_jsx(FilterGroup, { label: "Rodzaj decyzji", open: open.decision, onToggle: () => toggle('decision'), children: taxonomy.term_decision_type.map((v) => (_jsx(CheckItem, { label: v, checked: isChecked('term_decision_type', v), onChange: () => toggleList('term_decision_type', v), disabled: disabled }, v))) })) : null, taxonomy?.term_sector?.length ? (_jsx(FilterGroup, { label: "Sektor", open: open.sector, onToggle: () => toggle('sector'), children: taxonomy.term_sector.map((v) => (_jsx(CheckItem, { label: v, checked: isChecked('term_sector', v), onChange: () => toggleList('term_sector', v), disabled: disabled }, v))) })) : null, taxonomy?.term_corrective_measure?.length ? (_jsx(FilterGroup, { label: "\u015Arodek naprawczy", open: open.remedy, onToggle: () => toggle('remedy'), children: taxonomy.term_corrective_measure.map((v) => (_jsx(CheckItem, { label: v, checked: isChecked('term_corrective_measure', v), onChange: () => toggleList('term_corrective_measure', v), disabled: disabled }, v))) })) : null, taxonomy?.term_violation_type?.length ? (_jsx(FilterGroup, { label: "Rodzaj naruszenia", open: open.violation, onToggle: () => toggle('violation'), children: taxonomy.term_violation_type.map((v) => (_jsx(CheckItem, { label: v, checked: isChecked('term_violation_type', v), onChange: () => toggleList('term_violation_type', v), disabled: disabled }, v))) })) : null, _jsx("button", { className: "rag-filter-apply", onClick: onApply, disabled: disabled, children: disabled ? 'Szukam…' : 'Zastosuj filtry' })] }));
}
// ─────────────────────────── HELPERS ────────────────────────────
function FilterGroup({ label, open, onToggle, children, }) {
    return (_jsxs("div", { className: "rag-filter-group", children: [_jsxs("button", { className: "rag-filter-group-header", onClick: onToggle, children: [_jsx("span", { children: label }), _jsx("span", { className: "rag-filter-chevron", children: open ? '▲' : '▼' })] }), open && _jsx("div", { className: "rag-filter-group-body", children: children })] }));
}
function CheckItem({ label, checked, onChange, disabled, }) {
    return (_jsxs("label", { className: "rag-filter-check", children: [_jsx("input", { type: "checkbox", checked: checked, onChange: onChange, disabled: disabled }), _jsx("span", { children: label })] }));
}

import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import { useSuggest } from './hooks/useSuggest';
/**
 * Pole wyszukiwania z autouzupełnianiem.
 *
 * - Dropdown pojawia się po wpisaniu ≥2 znaków
 * - Dwie sekcje: Tagi i Sygnatury
 * - Nawigacja klawiaturą: ↑↓ wybiera, Enter zatwierdza, Escape zamyka
 * - Kliknięcie poza dropdownem zamyka go
 */
export function SearchInput({ value, onChange, onSearch, disabled = false, placeholder = 'Wpisz treść, sygnaturę lub temat...', }) {
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(-1); // indeks aktywnej pozycji
    const { results, total } = useSuggest(value);
    const inputRef = useRef(null);
    const dropdownRef = useRef(null);
    // Płaska lista wszystkich pozycji (tagi + sygnatury)
    const allItems = [
        ...results.tags.map((t) => ({ label: t, type: 'tag' })),
        ...results.signatures.map((s) => ({ label: s.signature, type: 'signature', item: s })),
    ];
    // Otwórz dropdown gdy są wyniki
    useEffect(() => {
        setActive(-1);
        setOpen(total > 0 && value.trim().length >= 2);
    }, [total, value]);
    // Zamknij po kliknięciu poza
    useEffect(() => {
        const handler = (e) => {
            if (!inputRef.current?.contains(e.target) &&
                !dropdownRef.current?.contains(e.target)) {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);
    const selectItem = (label) => {
        onChange(label);
        setOpen(false);
        onSearch(label);
    };
    const handleKeyDown = (e) => {
        if (!open) {
            if (e.key === 'Enter')
                onSearch(value);
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, allItems.length - 1));
        }
        else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, -1));
        }
        else if (e.key === 'Enter') {
            e.preventDefault();
            if (active >= 0 && allItems[active]) {
                selectItem(allItems[active].label);
            }
            else {
                setOpen(false);
                onSearch(value);
            }
        }
        else if (e.key === 'Escape') {
            setOpen(false);
            setActive(-1);
        }
    };
    return (_jsxs("div", { className: "rag-suggest-wrapper", children: [_jsx("input", { ref: inputRef, type: "text", value: value, onChange: (e) => onChange(e.target.value), onKeyDown: handleKeyDown, onFocus: () => total > 0 && setOpen(true), placeholder: placeholder, className: "rag-search-input", disabled: disabled, "aria-label": "Wyszukaj decyzje UODO", "aria-autocomplete": "list", "aria-expanded": open, autoComplete: "off" }), open && (_jsxs("div", { ref: dropdownRef, className: "rag-suggest-dropdown", role: "listbox", children: [results.tags.length > 0 && (_jsxs("div", { className: "rag-suggest-group", children: [_jsx("div", { className: "rag-suggest-group-label", children: "Tagi" }), results.tags.map((tag, i) => {
                                const idx = i;
                                return (_jsxs("div", { role: "option", "aria-selected": active === idx, className: `rag-suggest-item rag-suggest-item--tag ${active === idx ? 'rag-suggest-item--active' : ''}`, onMouseDown: (e) => { e.preventDefault(); selectItem(tag); }, onMouseEnter: () => setActive(idx), children: [_jsx("span", { className: "rag-suggest-icon", children: "\uD83C\uDFF7" }), _jsx("span", { className: "rag-suggest-label", children: tag })] }, tag));
                            })] })), results.signatures.length > 0 && (_jsxs("div", { className: "rag-suggest-group", children: [_jsx("div", { className: "rag-suggest-group-label", children: "Decyzje" }), results.signatures.map((item, i) => {
                                const idx = results.tags.length + i;
                                return (_jsxs("div", { role: "option", "aria-selected": active === idx, className: `rag-suggest-item rag-suggest-item--sig ${active === idx ? 'rag-suggest-item--active' : ''}`, onMouseDown: (e) => { e.preventDefault(); selectItem(item.signature); }, onMouseEnter: () => setActive(idx), children: [_jsx("span", { className: "rag-suggest-icon", children: "\uD83D\uDCC4" }), _jsxs("div", { className: "rag-suggest-sig-body", children: [_jsxs("div", { className: "rag-suggest-sig-top", children: [_jsx("span", { className: "rag-suggest-sig", children: item.signature }), item.year && _jsx("span", { className: "rag-suggest-year", children: item.year })] }), item.title && _jsx("span", { className: "rag-suggest-title", children: item.title })] })] }, item.signature));
                            })] }))] }))] }));
}

import { useEffect, useRef, useState } from "react";
const API_URL = import.meta.env.VITE_API_URL || "";
const EMPTY = { tags: [], signatures: [] };
export function useSuggest(query, delay = 300) {
    const [results, setResults] = useState(EMPTY);
    const [loading, setLoading] = useState(false);
    const timerRef = useRef(null);
    const abortRef = useRef(null);
    useEffect(() => {
        if (query.trim().length < 2) {
            setResults(EMPTY);
            setLoading(false);
            return;
        }
        // Debounce
        if (timerRef.current)
            clearTimeout(timerRef.current);
        timerRef.current = setTimeout(async () => {
            // Anuluj poprzednie żądanie
            abortRef.current?.abort();
            abortRef.current = new AbortController();
            setLoading(true);
            try {
                const resp = await fetch(`${API_URL}/api/suggest?q=${encodeURIComponent(query.trim())}&limit=8`, { signal: abortRef.current.signal });
                if (!resp.ok)
                    throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                setResults(data);
            }
            catch (e) {
                if (e.name !== "AbortError")
                    setResults(EMPTY);
            }
            finally {
                setLoading(false);
            }
        }, delay);
        return () => {
            if (timerRef.current)
                clearTimeout(timerRef.current);
        };
    }, [query, delay]);
    const clear = () => setResults(EMPTY);
    const total = results.tags.length + results.signatures.length;
    return { results, loading, total, clear };
}

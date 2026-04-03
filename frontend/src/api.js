/**
 * Klient API — typy i funkcje odpowiadające endpointom FastAPI.
 * Używany zarówno w trybie standalone jak i widget.
 */
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
// ─────────────────────────── FUNKCJE API ─────────────────────────
async function post(path, body) {
    const resp = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`API error ${resp.status}: ${err}`);
    }
    return resp.json();
}
async function get(path) {
    const resp = await fetch(`${API_URL}${path}`);
    if (!resp.ok)
        throw new Error(`API error ${resp.status}`);
    return resp.json();
}
export const api = {
    /** Wyszukiwanie hybrydowe — zwraca dokumenty i tagi */
    search(req) {
        return post('/api/search', req);
    },
    /**
     * Streaming odpowiedzi LLM przez SSE.
     * Zwraca funkcję cleanup do przerwania streamu.
     *
     * Przykład:
     *   const stop = api.streamAnswer(
     *     { query, docs, provider: 'ollama', model: '...' },
     *     (token) => setAnswer(a => a + token),
     *     () => setLoading(false),
     *   )
     *   return stop  // cleanup w useEffect
     */
    streamAnswer(req, onToken, onDone, onError) {
        const controller = new AbortController();
        fetch(`${API_URL}/api/answer/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(req),
            signal: controller.signal,
        })
            .then(async (resp) => {
            if (!resp.body)
                throw new Error('No body');
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done)
                    break;
                buffer += decoder.decode(value, { stream: true });
                // SSE: każde zdarzenie zakończone \n\n
                const events = buffer.split('\n\n');
                buffer = events.pop() ?? '';
                for (const event of events) {
                    const line = event.replace(/^data: /, '').trim();
                    if (!line)
                        continue;
                    try {
                        const parsed = JSON.parse(line);
                        if (parsed.type === 'token')
                            onToken(parsed.content);
                        else if (parsed.type === 'done')
                            onDone();
                        else if (parsed.type === 'error')
                            onError?.(parsed.message);
                    }
                    catch {
                        // ignoruj niepoprawne linie
                    }
                }
            }
        })
            .catch((err) => {
            if (err.name !== 'AbortError')
                onError?.(String(err));
        });
        return () => controller.abort();
    },
    /** Dekompozycja zapytania przez LLM (Reasoning Step) */
    decompose(query, provider, model) {
        return post('/api/decompose', { query, provider, model });
    },
    /** Wszystkie tagi — do autocomplete */
    tags() {
        return get('/api/tags');
    },
    /** Opcje filtrów taksonomii */
    taxonomy() {
        return get('/api/taxonomy');
    },
    /** Statystyki kolekcji */
    stats() {
        return get('/api/stats');
    },
    /** Pojedyncza decyzja po sygnaturze */
    bySignature(sig) {
        return get(`/api/signature/${encodeURIComponent(sig)}`);
    },
};

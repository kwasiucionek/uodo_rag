/**
 * Klient API — typy i funkcje odpowiadające endpointom FastAPI.
 * Używany zarówno w trybie standalone jak i widget.
 */

const API_URL = import.meta.env.VITE_API_URL || "";

// ─────────────────────────── TYPY ────────────────────────────────

export interface Filters {
    status?: string;
    keyword?: string;
    doc_types?: string[];
    year_from?: number;
    year_to?: number;
    term_decision_type?: string[];
    term_violation_type?: string[];
    term_legal_basis?: string[];
    term_corrective_measure?: string[];
    term_sector?: string[];
}

export interface SearchRequest {
    query: string;
    search_query?: string;
    filters?: Filters;
    use_graph?: boolean;
    top_k?: number;
}

export interface Document {
    doc_id?: string;
    doc_type: string;
    signature?: string;
    title?: string;
    title_full?: string;
    status?: string;
    year?: number;
    content_text?: string;
    section_title?: string;
    chunk_index?: number;
    chunk_total?: number;
    article_num?: string;
    keywords: string[];
    source_url?: string;
    score: number;
    source?: string;
    graph_relation?: string;
}

export interface SearchResponse {
    docs: Document[];
    tags: string[];
    search_time: number;
    total: number;
}

export interface DecomposeResponse {
    query_type: string;
    search_keywords: string[];
    gdpr_articles_hint: string[];
    uodo_act_articles_hint: string[];
    year_from_hint?: number;
    year_to_hint?: number;
    enriched_query: string;
    reasoning: string;
}

export interface Taxonomy {
    term_decision_type: string[];
    term_violation_type: string[];
    term_legal_basis: string[];
    term_corrective_measure: string[];
    term_sector: string[];
}

export type SSEEvent =
    | { type: "token"; content: string }
    | { type: "done" }
    | { type: "error"; message: string };

// ─────────────────────────── FUNKCJE API ─────────────────────────

async function post<T>(path: string, body: unknown): Promise<T> {
    const resp = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`API error ${resp.status}: ${err}`);
    }
    return resp.json();
}

async function get<T>(path: string): Promise<T> {
    const resp = await fetch(`${API_URL}${path}`);
    if (!resp.ok) throw new Error(`API error ${resp.status}`);
    return resp.json();
}

export const api = {
    /** Wyszukiwanie hybrydowe — zwraca dokumenty i tagi */
    search(req: SearchRequest): Promise<SearchResponse> {
        return post("/api/search", req);
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
    streamAnswer(
        req: {
            query: string;
            docs: Document[];
            provider: string;
            model: string;
        },
        onToken: (token: string) => void,
        onDone: () => void,
        onError?: (msg: string) => void,
    ): () => void {
        const controller = new AbortController();

        fetch(`${API_URL}/api/answer/stream`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(req),
            signal: controller.signal,
        })
            .then(async (resp) => {
                if (!resp.body) throw new Error("No body");
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });

                    // SSE: każde zdarzenie zakończone \n\n
                    const events = buffer.split("\n\n");
                    buffer = events.pop() ?? "";

                    for (const event of events) {
                        const line = event.replace(/^data: /, "").trim();
                        if (!line) continue;
                        try {
                            const parsed: SSEEvent = JSON.parse(line);
                            if (parsed.type === "token")
                                onToken(parsed.content);
                            else if (parsed.type === "done") onDone();
                            else if (parsed.type === "error")
                                onError?.(parsed.message);
                        } catch {
                            // ignoruj niepoprawne linie
                        }
                    }
                }
            })
            .catch((err) => {
                if (err.name !== "AbortError") onError?.(String(err));
            });

        return () => controller.abort();
    },

    /** Dekompozycja zapytania przez LLM (Reasoning Step) */
    decompose(
        query: string,
        provider: string,
        model: string,
    ): Promise<DecomposeResponse> {
        return post("/api/decompose", { query, provider, model });
    },

    /** Wszystkie tagi — do autocomplete */
    tags(): Promise<string[]> {
        return get("/api/tags");
    },

    /** Opcje filtrów taksonomii */
    taxonomy(): Promise<Taxonomy> {
        return get("/api/taxonomy");
    },

    /** Statystyki kolekcji */
    stats(): Promise<Record<string, unknown>> {
        return get("/api/stats");
    },

    /** Pojedyncza decyzja po sygnaturze */
    bySignature(sig: string): Promise<Document> {
        return get(`/api/signature/${encodeURIComponent(sig)}`);
    },
};

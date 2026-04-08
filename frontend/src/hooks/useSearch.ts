import { useCallback, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api, Document, Filters, SearchResponse } from "../api";

interface SearchState {
    allDocs: Document[];
    tags: string[];
    answer: string;
    searchTime: number;
    total: number;
    loadingDocs: boolean;
    loadingAnswer: boolean;
    error: string | null;
}

const INITIAL_STATE: SearchState = {
    allDocs: [],
    tags: [],
    answer: "",
    searchTime: 0,
    total: 0,
    loadingDocs: false,
    loadingAnswer: false,
    error: null,
};

interface UseSearchOptions {
    provider: string;
    model: string;
    useGraph?: boolean;
    useLLM?: boolean;
}

export function useSearch(options: UseSearchOptions) {
    const { provider, model, useGraph = true, useLLM = true } = options;

    const [state, setState] = useState<SearchState>(INITIAL_STATE);
    const stopStreamRef = useRef<(() => void) | null>(null);

    const stopStream = useCallback(() => {
        stopStreamRef.current?.();
        stopStreamRef.current = null;
        setState((s) => ({ ...s, loadingAnswer: false }));
    }, []);

    const search = useCallback(
        async (query: string, filters: Filters = {}) => {
            if (!query.trim()) return;

            stopStream();
            setState({ ...INITIAL_STATE, loadingDocs: true });

            try {
                // Dekompozycja zapytania
                let searchQuery: string | undefined;
                if (useLLM && query.split(" ").length > 3) {
                    try {
                        const decomposed = await api.decompose(
                            query,
                            provider,
                            model,
                        );
                        searchQuery = decomposed.search_keywords
                            .slice(0, 3)
                            .join(" ");
                    } catch {
                        // fallback
                    }
                }

                // Wyszukiwanie — top_k=50 żeby mieć zapas
                const result: SearchResponse = await api.search({
                    query,
                    search_query: searchQuery,
                    filters,
                    use_graph: useGraph,
                    top_k: 50,
                });

                setState((s) => ({
                    ...s,
                    allDocs: result.docs,
                    tags: result.tags,
                    searchTime: result.search_time,
                    total: result.total,
                    loadingDocs: false,
                }));

                // Streaming LLM — tylko pierwsze 8 dokumentów
                if (useLLM && result.docs.length > 0) {
                    setState((s) => ({
                        ...s,
                        answer: "",
                        loadingAnswer: true,
                    }));

                    stopStreamRef.current = api.streamAnswer(
                        {
                            query,
                            docs: result.docs.slice(0, 8),
                            provider,
                            model,
                        },
                        (token) =>
                            flushSync(() =>
                                setState((s) => ({
                                    ...s,
                                    answer: s.answer + token,
                                })),
                            ),
                        () => setState((s) => ({ ...s, loadingAnswer: false })),
                        (msg) =>
                            setState((s) => ({
                                ...s,
                                loadingAnswer: false,
                                error: msg,
                            })),
                    );
                }
            } catch (err) {
                setState((s) => ({
                    ...s,
                    loadingDocs: false,
                    loadingAnswer: false,
                    error: err instanceof Error ? err.message : String(err),
                }));
            }
        },
        [provider, model, useGraph, useLLM, stopStream],
    );

    return { ...state, search, stopStream };
}

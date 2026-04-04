import { jsx as _jsx } from "react/jsx-runtime";
/**
 * Tryb WIDGET — osadzalny na dowolnej stronie przez <script>.
 *
 * Budowanie:
 *   VITE_API_URL=https://rag.uodo.gov.pl npm run build -- --mode widget
 *
 * Użycie na stronie zewnętrznej:
 *   <div id="uodo-rag-root"></div>
 *   <script src="https://rag.uodo.gov.pl/widget.iife.js"></script>
 *   <script>
 *     UodoRag.mount('#uodo-rag-root', {
 *       useLLM: true,
 *       onDocumentClick: (doc) => console.log(doc.signature),
 *     })
 *   </script>
 *
 * Lub przez Web Component (automatyczna inicjalizacja):
 *   <uodo-rag-widget api-url="https://rag.uodo.gov.pl"></uodo-rag-widget>
 */
import { createRoot } from 'react-dom/client';
import { UodoRagWidget } from './UodoRagWidget';
import './styles/widget.css';
// ─── Funkcja mount — ręczna inicjalizacja ────────────────────────
function mount(selector, props = {}) {
    const container = document.querySelector(selector);
    if (!container) {
        console.error(`[UodoRag] Element '${selector}' nie znaleziony.`);
        return;
    }
    createRoot(container).render(_jsx(UodoRagWidget, { ...props }));
}
// ─── Web Component — automatyczna inicjalizacja ──────────────────
class UodoRagElement extends HTMLElement {
    connectedCallback() {
        const apiUrl = this.getAttribute('api-url') ?? undefined;
        const useLLM = this.getAttribute('use-llm') !== 'false';
        createRoot(this).render(_jsx(UodoRagWidget, { apiUrl: apiUrl, useLLM: useLLM }));
    }
}
if (!customElements.get('uodo-rag-widget')) {
    customElements.define('uodo-rag-widget', UodoRagElement);
}
// ─── Eksport globalny (dostępny jako UodoRag.mount) ──────────────
export { mount };
window.UodoRag = { mount };

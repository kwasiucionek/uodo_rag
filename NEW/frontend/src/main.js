import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { UodoRagWidget } from "./UodoRagWidget";
import { DocumentView } from "./DocumentView";
import "./styles/widget.css";
const params = new URLSearchParams(window.location.search);
const docSig = params.get("doc");
createRoot(document.getElementById("root")).render(_jsx(StrictMode, { children: _jsx("div", { style: { maxWidth: 1100, margin: "0 auto", padding: "2rem 1rem" }, children: docSig ? (_jsx(DocumentView, { signature: docSig, onBack: () => window.close() })) : (_jsxs(_Fragment, { children: [_jsx("h1", { style: { marginBottom: "1.5rem" }, children: "Wyszukiwarka Decyzji UODO" }), _jsx(UodoRagWidget, { useLLM: true })] })) }) }));

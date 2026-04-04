import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { UodoRagWidget } from "./UodoRagWidget";
import { DocumentView } from "./DocumentView";
import "./styles/widget.css";

const params = new URLSearchParams(window.location.search);
const docSig = params.get("doc");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "2rem 1rem" }}>
      {docSig ? (
        <DocumentView signature={docSig} onBack={() => window.close()} />
      ) : (
        <>
          <h1 style={{ marginBottom: "1.5rem" }}>Wyszukiwarka Decyzji UODO</h1>
          <UodoRagWidget useLLM={true} />
        </>
      )}
    </div>
  </StrictMode>,
);

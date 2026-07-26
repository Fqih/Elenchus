import type { Verdict } from "../types";
import "./App.css";

export function EvidencePanel({
  verdict,
  onClose,
}: {
  verdict: Verdict;
  onClose: () => void;
}) {
  return (
    <aside className="evidence-panel" role="dialog" aria-label="Claim evidence">
      <header>
        <h2>Claim detail</h2>
        <button className="close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      <div className="meta">
        <div>
          label: <strong>{verdict.label}</strong>
        </div>
        <div>
          confidence: <strong>{verdict.confidence.toFixed(3)}</strong>
        </div>
        <div>
          tier: <strong>{verdict.tier}</strong>
        </div>
      </div>
      <h3>Claim</h3>
      <p>{verdict.claim.text}</p>
      <h3>Evidence</h3>
      {verdict.evidence ? (
        <>
          <div className="evidence-excerpt">{verdict.evidence.text}</div>
          <p>
            <small>source id: {verdict.evidence.source_id}</small>
          </p>
        </>
      ) : (
        <p className="no-evidence">No evidence available.</p>
      )}
    </aside>
  );
}
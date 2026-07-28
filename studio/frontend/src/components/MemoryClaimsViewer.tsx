import { useState } from "react";
import { useRunMemoryClaims } from "../hooks/useStudioApi";
import "./App.css";

/**
 * Browser for the Lethe MemoryItems tagged with run:{runId} under
 * a project's per-project SQLite. Each item is one supported claim
 * from the original verification run; the tags carry provenance
 * (run id, project id, source id + version).
 */
export function MemoryClaimsViewer({
  projectId,
  runId,
  expectedCount,
}: {
  projectId: string;
  runId: string;
  /** How many items the run row promises (the MemoryItem ids). */
  expectedCount: number;
}) {
  const [open, setOpen] = useState(false);
  const query = useRunMemoryClaims(projectId, open ? runId : null);

  if (expectedCount === 0) return null;

  return (
    <div className="memory-claims">
      <button
        className="memory-claims-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? "▾" : "▸"} Lethe memory ({expectedCount} item
        {expectedCount === 1 ? "" : "s"})
      </button>
      {open && (
        <div className="memory-claims-body">
          {query.isLoading && <p className="muted">Loading memory items…</p>}
          {query.isError && (
            <p className="error">
              Failed to load memory: {String(query.error)}
            </p>
          )}
          {query.data && query.data.length === 0 && (
            <p className="muted">No memory items found for this run.</p>
          )}
          {query.data && query.data.length > 0 && (
            <ol className="memory-claims-list">
              {query.data.map((item) => (
                <li key={item.id} className="memory-claim">
                  <div className="memory-claim-content">{item.content}</div>
                  <div className="memory-claim-tags">
                    {item.tags
                      .filter(
                        (t) =>
                          t.startsWith("source:") ||
                          t.startsWith("v") ||
                          t === "elenchus_verified",
                      )
                      .map((tag) => (
                        <span key={tag} className="tag">
                          {tag}
                        </span>
                      ))}
                  </div>
                  <div className="memory-claim-meta">
                    id <code>{item.id}</code> · importance{" "}
                    {item.importance_score.toFixed(2)} · accessed{" "}
                    {item.access_count}×
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

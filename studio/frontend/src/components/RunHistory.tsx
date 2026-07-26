import { useRuns } from "../hooks/useStudioApi";
import { GateBadge } from "./GateBadge";
import type { Run } from "../types";
import "./Lists.css";

export function RunHistory({
  projectId,
  onSelect,
}: {
  projectId: string;
  onSelect: (run: Run) => void;
}) {
  const { data: runs, isLoading, isError, error } = useRuns(projectId);

  if (isLoading) return <p className="empty">Loading runs…</p>;
  if (isError) return <p className="empty">Error: {(error as Error).message}</p>;
  if (!runs || runs.length === 0) {
    return <p className="empty">No runs yet. Submit your first check above.</p>;
  }

  return (
    <div className="list">
      {runs.map((r) => (
        <div
          key={r.id}
          className="list-item"
          onClick={() => onSelect(r)}
          role="button"
          tabIndex={0}
        >
          <header>
            <GateBadge result={r.gate_result} />
            <span className="name">{r.model_or_prompt_label}</span>
            <span className="version" style={{ fontFamily: "var(--font-mono)" }}>
              {r.latency_ms.toFixed(0)} ms
            </span>
          </header>
          <div className="preview">
            {r.candidate_answer.slice(0, 120)}…
          </div>
          <div className="preview" style={{ fontSize: "0.7rem" }}>
            pinned: {Object.entries(r.source_document_versions)
              .map(([id, v]) => `${id.slice(0, 6)}=v${v}`)
              .join(", ")}
          </div>
        </div>
      ))}
    </div>
  );
}

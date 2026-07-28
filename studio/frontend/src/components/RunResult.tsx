import type { Run, Verdict } from "../types";
import { GateBadge } from "./GateBadge";
import { ClaimSpan } from "./ClaimSpan";
import { MemoryClaimsViewer } from "./MemoryClaimsViewer";
import "./RunResult.css";

export function RunResult({
  run,
  onClaimClick,
  projectId,
}: {
  run: Run;
  onClaimClick: (verdict: Verdict) => void;
  /** Required when phase7_memory_item_ids is non-empty so the
   *  MemoryClaimsViewer can fetch the items from the Studio API. */
  projectId?: string;
}) {
  // Build segments from the candidate_answer + claim spans.
  // Each claim occupies [claim.span[0], claim.span[1]). Anything between
  // claims is plain text.
  const segments: Array<
    { kind: "text"; text: string } | { kind: "claim"; verdict: Verdict }
  > = [];

  const sorted = [...run.verdicts].sort(
    (a, b) => a.claim.span[0] - b.claim.span[0],
  );

  let cursor = 0;
  for (const v of sorted) {
    const [start, end] = v.claim.span;
    if (cursor < start) {
      segments.push({ kind: "text", text: run.candidate_answer.slice(cursor, start) });
    }
    segments.push({ kind: "claim", verdict: v });
    cursor = end;
  }
  if (cursor < run.candidate_answer.length) {
    segments.push({ kind: "text", text: run.candidate_answer.slice(cursor) });
  }

  // Phase 7 summary — only shown when either integration populated state.
  const hadRetry = run.phase7_retry_attempts > 0 || run.phase7_retry_stop_reason !== null;
  const hadMemory = run.phase7_memory_item_ids.length > 0;
  const phase7Active = hadRetry || hadMemory;

  return (
    <div className="run-result">
      <header>
        <GateBadge result={run.gate_result} />
        <span>verified in {run.latency_ms.toFixed(0)} ms</span>
        <span>model: {run.model_or_prompt_label}</span>
      </header>
      {phase7Active && (
        <section className="phase7">
          <h4>Phase 7</h4>
          {hadRetry && (
            <div className="phase7-row">
              <span className="phase7-label">Soteria retry</span>
              <span>
                {run.phase7_retry_attempts} attempt{run.phase7_retry_attempts === 1 ? "" : "s"}
                {run.phase7_retry_stop_reason && (
                  <span className="phase7-stop">
                    stop reason: <code>{run.phase7_retry_stop_reason}</code>
                  </span>
                )}
              </span>
            </div>
          )}
          {hadMemory && (
            <div className="phase7-row">
              <span className="phase7-label">Lethe memory</span>
              <span>
                {run.phase7_memory_item_ids.length} item
                {run.phase7_memory_item_ids.length === 1 ? "" : "s"} stored
              </span>
              {projectId && (
                <MemoryClaimsViewer
                  projectId={projectId}
                  runId={run.id}
                  expectedCount={run.phase7_memory_item_ids.length}
                />
              )}
            </div>
          )}
        </section>
      )}
      <div className="answer">
        {segments.map((seg, i) =>
          seg.kind === "text" ? (
            <span key={i}>{seg.text}</span>
          ) : (
            <ClaimSpan
              key={i}
              claim={seg.verdict.claim}
              label={seg.verdict.label}
              onClick={() => onClaimClick(seg.verdict)}
            />
          ),
        )}
      </div>
    </div>
  );
}

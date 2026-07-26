import type { Run, Verdict } from "../types";
import { GateBadge } from "./GateBadge";
import { ClaimSpan } from "./ClaimSpan";
import "./RunResult.css";

export function RunResult({
  run,
  onClaimClick,
}: {
  run: Run;
  onClaimClick: (verdict: Verdict) => void;
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

  return (
    <div className="run-result">
      <header>
        <GateBadge result={run.gate_result} />
        <span>verified in {run.latency_ms.toFixed(0)} ms</span>
        <span>model: {run.model_or_prompt_label}</span>
      </header>
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
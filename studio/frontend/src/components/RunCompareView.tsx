import { useEffect, useState } from "react";
import { useRun } from "../hooks/useStudioApi";
import type { Run, Verdict } from "../types";
import "./RunCompare.css";

type VerdictKey = string;

/**
 * Side-by-side comparison of two runs. Useful for A/B'ing two model or
 * prompt labels against the same source. Differences per claim are
 * surfaced as a "DIFF" badge; identical verdicts stay plain.
 *
 * Each run is fetched on demand via the existing `useRun` hook (the
 * caller already has the run metadata in `runs`). The selector
 * dropdowns let the user swap either side without leaving the panel.
 */
export function RunCompareView({
  projectId: _projectId,
  runs,
}: {
  projectId: string;
  runs: Run[];
}) {
  if (runs.length < 2) {
    return (
      <div className="run-compare">
        <p>
          To compare runs side-by-side, you need at least 2 runs in this project.
        </p>
      </div>
    );
  }

  const [leftId, setLeftId] = useState(runs[0].id);
  const [rightId, setRightId] = useState(
    runs[1].id === runs[0].id ? runs[0].id : runs[1].id,
  );

  // If the available runs change (project switch), reset selectors.
  useEffect(() => {
    if (!runs.find((r) => r.id === leftId)) {
      setLeftId(runs[0].id);
    }
    if (!runs.find((r) => r.id === rightId)) {
      setRightId(runs[1]?.id ?? runs[0].id);
    }
    // We intentionally only react to the runs list identity, not to
    // user-driven selector changes (which would cause a feedback loop).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  const leftQuery = useRun(leftId);
  const rightQuery = useRun(rightId);

  return (
    <div className="run-compare">
      <header className="run-compare-header">
        <div className="run-compare-selector">
          <label htmlFor="rc-left">Run A</label>
          <select
            id="rc-left"
            value={leftId}
            onChange={(e) => setLeftId(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {labelFor(r)}
              </option>
            ))}
          </select>
        </div>
        <div className="run-compare-selector">
          <label htmlFor="rc-right">Run B</label>
          <select
            id="rc-right"
            value={rightId}
            onChange={(e) => setRightId(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {labelFor(r)}
              </option>
            ))}
          </select>
        </div>
      </header>

      {leftQuery.isLoading || rightQuery.isLoading ? (
        <p>Loading runs…</p>
      ) : leftQuery.isError || rightQuery.isError ? (
        <p className="error">
          Failed to load a run for comparison: {String(
            leftQuery.error ?? rightQuery.error,
          )}
        </p>
      ) : leftQuery.data && rightQuery.data ? (
        <CompareTable left={leftQuery.data} right={rightQuery.data} />
      ) : null}
    </div>
  );
}

function labelFor(r: Run): string {
  return `${r.model_or_prompt_label} · ${new Date(r.created_at).toLocaleString()}`;
}

function CompareTable({ left, right }: { left: Run; right: Run }) {
  // Align verdicts by claim id where possible. If the runs produced
  // different claims, fall back to position-by-position in the answer.
  const leftByKey = indexBy(left.verdicts);
  const rightByKey = indexBy(right.verdicts);
  const allKeys = uniqueKeys(left.verdicts, right.verdicts);

  return (
    <table className="run-compare-table">
      <thead>
        <tr>
          <th>Claim</th>
          <th>{left.model_or_prompt_label}</th>
          <th>{right.model_or_prompt_label}</th>
          <th>Δ</th>
        </tr>
      </thead>
      <tbody>
        {allKeys.map((k) => {
          const lv = leftByKey.get(k);
          const rv = rightByKey.get(k);
          const differs = (lv?.label ?? "—") !== (rv?.label ?? "—");
          return (
            <tr key={k} className={differs ? "differs" : "same"}>
              <td className="claim-cell">{lv?.claim.text ?? rv?.claim.text}</td>
              <td>{lv ? <LabelBadge verdict={lv} /> : <span className="muted">—</span>}</td>
              <td>{rv ? <LabelBadge verdict={rv} /> : <span className="muted">—</span>}</td>
              <td>{differs ? <span className="diff-badge">DIFF</span> : null}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function indexBy(verdicts: Verdict[]): Map<VerdictKey, Verdict> {
  const m = new Map<VerdictKey, Verdict>();
  for (let i = 0; i < verdicts.length; i++) {
    // Claim id may collide between runs (each run reuses ids), so the
    // key is claim id + position.
    const v = verdicts[i];
    m.set(`${v.claim.id}#${i}`, v);
  }
  return m;
}

function uniqueKeys(a: Verdict[], b: Verdict[]): VerdictKey[] {
  const out: VerdictKey[] = [];
  const seen = new Set<VerdictKey>();
  const max = Math.max(a.length, b.length);
  for (let i = 0; i < max; i++) {
    const ka = a[i] ? `${a[i].claim.id}#${i}` : null;
    const kb = b[i] ? `${b[i].claim.id}#${i}` : null;
    for (const k of [ka, kb]) {
      if (k && !seen.has(k)) {
        seen.add(k);
        out.push(k);
      }
    }
  }
  return out;
}

function LabelBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`compare-label compare-label-${verdict.label}`}>
      {verdict.label} · {(verdict.confidence * 100).toFixed(0)}%
    </span>
  );
}

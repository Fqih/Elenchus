import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useProject, useSourceDocuments, useRuns } from "../hooks/useStudioApi";
import { SourceDocForm } from "../components/SourceDocForm";
import { SourceDocList } from "../components/SourceDocList";
import { CheckForm } from "../components/CheckForm";
import { RunResult } from "../components/RunResult";
import { EvidencePanel } from "../components/EvidencePanel";
import { RunHistory } from "../components/RunHistory";
import { RunCompareView } from "../components/RunCompareView";
import type { Run, Verdict } from "../types";
import "./Pages.css";

export function ProjectDetail() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const { data: project, isError: projectErr } = useProject(projectId);
  const { data: docs } = useSourceDocuments(projectId);
  const { data: runs } = useRuns(projectId);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [selectedVerdict, setSelectedVerdict] = useState<Verdict | null>(null);

  if (projectErr) {
    return (
      <div className="page">
        <p>Project not found. <Link to="/">Go back</Link></p>
      </div>
    );
  }

  return (
    <div className="page">
      <header>
        <Link to="/">← Back</Link>
        <h1>{project?.name ?? "Loading…"}</h1>
      </header>

      <div className="detail-grid">
        <section className="section">
          <h2>Source documents</h2>
          <SourceDocForm projectId={projectId} onCreated={() => {}} />
          <SourceDocList projectId={projectId} />
        </section>

        <section className="section">
          <h2>Run a check</h2>
          <CheckForm
            projectId={projectId}
            hasSourceDocs={(docs?.length ?? 0) > 0}
            onSubmitted={(r) => setSelectedRun(r)}
          />
        </section>
      </div>

      {selectedRun && (
        <section className="section">
          <h2>Result</h2>
          <RunResult run={selectedRun} onClaimClick={setSelectedVerdict} projectId={projectId} />
        </section>
      )}

      <section className="section">
        <h2>Run history</h2>
        <RunHistory projectId={projectId} onSelect={setSelectedRun} />
      </section>

      {runs && runs.length >= 2 && (
        <section className="section">
          <h2>Compare two runs</h2>
          <RunCompareView projectId={projectId} runs={runs} />
        </section>
      )}

      {selectedVerdict && (
        <EvidencePanel
          verdict={selectedVerdict}
          onClose={() => setSelectedVerdict(null)}
        />
      )}
    </div>
  );
}

import { useState } from "react";
import { useSubmitCheck } from "../hooks/useStudioApi";
import type { Run } from "../types";
import "./Forms.css";

export function CheckForm({
  projectId,
  hasSourceDocs,
  onSubmitted,
}: {
  projectId: string;
  hasSourceDocs: boolean;
  onSubmitted: (run: Run) => void;
}) {
  const [question, setQuestion] = useState("");
  const [label, setLabel] = useState("gpt-4");
  const [answer, setAnswer] = useState("");
  const mutation = useSubmitCheck(projectId);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!label.trim() || !answer.trim()) return;
        mutation.mutate(
          {
            question: question.trim() || null,
            model_or_prompt_label: label.trim(),
            candidate_answer: answer,
          },
          { onSuccess: (r) => { onSubmitted(r); setAnswer(""); } },
        );
      }}
    >
      <label>
        Question (optional)
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. How long does shipping take?"
        />
      </label>
      <label>
        Model / prompt label
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          required
        />
      </label>
      <label>
        Candidate answer
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Paste the candidate answer here…"
          rows={6}
          required
        />
      </label>
      <div className="actions">
        <button
          type="submit"
          disabled={mutation.isPending || !label.trim() || !answer.trim() || !hasSourceDocs}
        >
          {mutation.isPending ? "Verifying…" : "Submit check"}
        </button>
        {!hasSourceDocs && (
          <span className="hint">Add a source document first.</span>
        )}
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}

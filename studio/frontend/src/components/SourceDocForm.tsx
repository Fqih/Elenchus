import { useState } from "react";
import { useAddSourceDocument } from "../hooks/useStudioApi";
import type { SourceDocument } from "../types";
import "./Forms.css";

export function SourceDocForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (doc: SourceDocument) => void;
}) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const mutation = useAddSourceDocument(projectId);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim() || !content.trim()) return;
        mutation.mutate(
          { name: name.trim(), content },
          { onSuccess: (d) => { onCreated(d); setName(""); setContent(""); } },
        );
      }}
    >
      <label>
        Source name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. shipping-faq"
          required
        />
      </label>
      <label>
        Source content
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste the source text here…"
          rows={8}
          required
        />
      </label>
      <div className="actions">
        <button
          type="submit"
          disabled={mutation.isPending || !name.trim() || !content.trim()}
        >
          {mutation.isPending ? "Adding…" : "Add source doc"}
        </button>
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}

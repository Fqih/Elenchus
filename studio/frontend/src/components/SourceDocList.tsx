import { useState } from "react";
import { useSourceDocuments, useUpdateSourceDocument } from "../hooks/useStudioApi";
import type { SourceDocument } from "../types";
import "./Lists.css";

export function SourceDocList({ projectId }: { projectId: string }) {
  const { data: docs, isLoading, isError, error } = useSourceDocuments(projectId);
  const [editing, setEditing] = useState<string | null>(null);

  if (isLoading) return <p className="empty">Loading source docs…</p>;
  if (isError) return <p className="empty">Error: {(error as Error).message}</p>;
  if (!docs || docs.length === 0) {
    return <p className="empty">No source documents yet. Add one above.</p>;
  }

  return (
    <div className="list">
      {docs.map((d) => (
        <SourceDocItem
          key={d.id}
          doc={d}
          isEditing={editing === d.id}
          onStartEdit={() => setEditing(d.id)}
          onCancelEdit={() => setEditing(null)}
        />
      ))}
    </div>
  );
}

function SourceDocItem({
  doc,
  isEditing,
  onStartEdit,
  onCancelEdit,
}: {
  doc: SourceDocument;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
}) {
  const [content, setContent] = useState(doc.content);
  const update = useUpdateSourceDocument(doc.project_id, doc.id);

  if (isEditing) {
    return (
      <div className="list-item">
        <header>
          <span className="name">{doc.name}</span>
          <span className="version">v{doc.version}</span>
        </header>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
          style={{ width: "100%", fontFamily: "var(--font-mono)" }}
        />
        <div className="actions">
          <button
            onClick={() =>
              update.mutate(
                { content },
                { onSuccess: () => onCancelEdit() },
              )
            }
            disabled={update.isPending || content === doc.content}
          >
            {update.isPending ? "Saving…" : "Save (bumps to v" + (doc.version + 1) + ")"}
          </button>
          <button onClick={onCancelEdit}>Cancel</button>
        </div>
        {update.isError && (
          <p className="error">{(update.error as Error).message}</p>
        )}
      </div>
    );
  }

  return (
    <div className="list-item">
      <header>
        <span className="name">{doc.name}</span>
        <span className="version">v{doc.version}</span>
      </header>
      <div className="preview">{doc.content.slice(0, 200)}…</div>
      <div className="actions">
        <button onClick={onStartEdit}>Edit (bumps version)</button>
      </div>
    </div>
  );
}

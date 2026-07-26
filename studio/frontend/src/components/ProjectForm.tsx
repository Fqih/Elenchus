import { useState } from "react";
import { useCreateProject } from "../hooks/useStudioApi";
import type { Project } from "../types";
import "./Forms.css";

export function ProjectForm({ onCreated }: { onCreated: (p: Project) => void }) {
  const [name, setName] = useState("");
  const mutation = useCreateProject();

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return;
        mutation.mutate(
          { name: name.trim() },
          { onSuccess: (p) => { onCreated(p); setName(""); } },
        );
      }}
    >
      <label>
        Project name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. customer-support-kb"
          required
        />
      </label>
      <div className="actions">
        <button type="submit" disabled={mutation.isPending || !name.trim()}>
          {mutation.isPending ? "Creating…" : "Create project"}
        </button>
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}

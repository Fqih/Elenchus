import { Link } from "react-router-dom";
import { useProjects } from "../hooks/useStudioApi";
import { ProjectForm } from "../components/ProjectForm";
import "./Pages.css";

export function ProjectList() {
  const { data: projects, isLoading, isError, error } = useProjects();

  return (
    <div className="page">
      <h1>Elenchus Studio</h1>

      <section className="section">
        <h2>New project</h2>
        <ProjectForm onCreated={() => { /* query invalidated by hook */ }} />
      </section>

      <section className="section">
        <h2>Existing projects</h2>
        {isLoading && <p className="empty">Loading…</p>}
        {isError && <p className="error">{(error as Error).message}</p>}
        {projects && projects.length === 0 && (
          <p className="empty">No projects yet. Create one above.</p>
        )}
        {projects && projects.length > 0 && (
          <div className="project-list">
            {projects.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`} className="project-card">
                <div className="name">{p.name}</div>
                <div className="id">{p.id}</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

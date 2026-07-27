import { Routes, Route } from "react-router-dom";
import { ProjectList } from "./pages/ProjectList";
import { ProjectDetail } from "./pages/ProjectDetail";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/projects/:projectId" element={<ProjectDetail />} />
    </Routes>
  );
}

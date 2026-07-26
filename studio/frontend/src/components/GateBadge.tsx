import type { GateResult } from "../types";
import "./App.css";

export function GateBadge({ result }: { result: GateResult }) {
  return <span className={`gate-badge gate-${result}`}>{result}</span>;
}
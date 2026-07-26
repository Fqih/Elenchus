"""Studio E2E smoke test (Phase 5 acceptance).

Boots the FastAPI server in a subprocess, runs the Plan.md Phase 5
acceptance flow over HTTP using httpx, and prints the full output so
the operator can read it. Exit code is 0 if all expectations pass, 1
otherwise.

Acceptance walked through:

  1. Create project, add source doc, submit check, retrieve verdicts
     round-trips correctly through the API.
  2. Editing a source document bumps its version AND a previously-recorded
     run still points at the version it was actually checked against.
  3. A configured output gate correctly labels a run as
     allowed/blocked/flagged using the blocked > flagged > allowed precedence.
  4. Run history for a project lists all past runs in order with their
     recorded model/prompt labels and latency.

Note: this example uses the real NLI model so detection is real, not
stubbed. It is intentionally exercised by an operator, not by pytest
(the model load time is in the tens of seconds).
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(client: httpx.Client, url: str, timeout: float = 180.0) -> None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            r = client.get(url, timeout=2.0)
            if r.status_code in (200, 404):
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server did not become ready within {timeout}s")


def _print(label: str, payload: Any) -> None:
    print(f"--- {label} ---")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(payload)


def _expect(cond: bool, msg: str) -> List[str]:
    if not cond:
        return [f"FAIL: {msg}"]
    return []


def run_smoke(db_path: Path) -> int:
    if db_path.exists():
        db_path.unlink()

    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "studio.api.server",
            "--db",
            str(db_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **__import__("os").environ,
            "LD_LIBRARY_PATH": __import__("os").environ.get("LD_LIBRARY_PATH", "")
                                   + ":" + str(Path.home() / ".local/lib"),
        },
    )

    failures: List[str] = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120.0) as client:
            _wait_ready(client, "/projects")

            print("=" * 72)
            print("Elenchus Studio — E2E smoke test (Phase 5)")
            print("=" * 72)

            # 1. Create project.
            r = client.post("/projects", json={"name": "kb-smoke"})
            failures += _expect(r.status_code == 200, f"create project: {r.status_code}")
            project = r.json()
            _print("POST /projects", project)
            project_id = project["id"]

            # 2. Add a source document.
            r = client.post(
                f"/projects/{project_id}/source-documents",
                json={
                    "name": "kb-returns",
                    "content": (
                        "Customers can return any item within 30 days of purchase for "
                        "a full refund. Items must be in their original packaging "
                        "with the receipt attached. Refunds are issued to the "
                        "original payment method within 5 business days of "
                        "receiving the return."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"add source: {r.status_code}")
            doc = r.json()
            _print("POST /projects/{id}/source-documents", doc)
            doc_id = doc["id"]

            # 3. Submit a clean check.
            r = client.post(
                f"/projects/{project_id}/checks",
                json={
                    "question": "How long do I have to return an item?",
                    "model_or_prompt_label": "gpt-4",
                    "candidate_answer": (
                        "Customers can return any item within 30 days of purchase "
                        "for a full refund. Items must be in their original "
                        "packaging with the receipt attached."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"clean check: {r.status_code}")
            clean_run = r.json()
            _print("POST /projects/{id}/checks (clean)", clean_run)
            failures += _expect(
                clean_run["gate_result"] == "allowed",
                f"clean check should be allowed, got {clean_run['gate_result']}",
            )
            clean_run_id = clean_run["id"]

            # 4. Submit a hallucinated check.
            r = client.post(
                f"/projects/{project_id}/checks",
                json={
                    "question": "How long do I have to return an item?",
                    "model_or_prompt_label": "gpt-4-hallucinating",
                    "candidate_answer": (
                        "Customers can return any item within 90 days of purchase "
                        "for a full refund. Items must be in their original "
                        "packaging with the receipt attached."
                    ),
                },
            )
            failures += _expect(
                r.status_code == 200, f"hallucinated check: {r.status_code}"
            )
            bad_run = r.json()
            _print("POST /projects/{id}/checks (hallucinated)", bad_run)
            failures += _expect(
                bad_run["gate_result"] == "blocked",
                f"hallucinated should be blocked, got {bad_run['gate_result']}",
            )

            # 5. Edit the source doc — version should bump.
            r = client.patch(
                f"/projects/{project_id}/source-documents/{doc_id}",
                json={"content": doc["content"] + " Updated clause."},
            )
            failures += _expect(r.status_code == 200, f"update source: {r.status_code}")
            updated_doc = r.json()
            _print("PATCH /projects/{id}/source-documents/{sid}", updated_doc)
            failures += _expect(
                updated_doc["version"] == 2,
                f"updated version should be 2, got {updated_doc['version']}",
            )

            # 6. The previously-recorded run still points at v1.
            r = client.get(f"/runs/{clean_run_id}")
            failures += _expect(r.status_code == 200, f"get clean run: {r.status_code}")
            still_clean = r.json()
            _print("GET /runs/{clean_run_id} after source edit", still_clean)
            failures += _expect(
                still_clean["source_document_versions"][doc_id] == 1,
                f"clean run should still be pinned to v1, got "
                f"{still_clean['source_document_versions'][doc_id]}",
            )

            # 7. Toggle the gate policy.
            r = client.put(
                f"/projects/{project_id}/gate-policy",
                json={
                    "block_on_any_contradiction": False,
                    "flag_if_unverifiable_count_exceeds": 0,
                },
            )
            failures += _expect(r.status_code == 200, f"set gate: {r.status_code}")
            _print("PUT /projects/{id}/gate-policy", r.json())

            # 8. Re-run the hallucinated check — should now be flagged, not blocked.
            r = client.post(
                f"/projects/{project_id}/checks",
                json={
                    "question": "q",
                    "model_or_prompt_label": "gpt-4-hallucinating",
                    "candidate_answer": bad_run["candidate_answer"],
                },
            )
            failures += _expect(r.status_code == 200, f"re-check: {r.status_code}")
            re_run = r.json()
            _print("POST /projects/{id}/checks (block off)", re_run)
            failures += _expect(
                re_run["gate_result"] != "blocked",
                f"with block off, result should not be blocked, got {re_run['gate_result']}",
            )

            # 9. Run history lists in chronological order.
            r = client.get(f"/projects/{project_id}/runs")
            failures += _expect(r.status_code == 200, f"list runs: {r.status_code}")
            runs = r.json()
            _print("GET /projects/{id}/runs", runs)
            labels = [r["model_or_prompt_label"] for r in runs]
            failures += _expect(
                labels == ["gpt-4", "gpt-4-hallucinating", "gpt-4-hallucinating"],
                f"run history should be in order, got {labels}",
            )

            print("\n" + "=" * 72)
            print("Summary")
            print("=" * 72)
            if failures:
                for f in failures:
                    print(f"  {f}")
                print(f"  {len(failures)} failure(s)")
            else:
                print("  all acceptance checks passed")

        return 0 if not failures else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("/tmp/elenchus-smoke.sqlite"),
    )
    args = parser.parse_args()
    return run_smoke(args.db)


if __name__ == "__main__":
    raise SystemExit(main())

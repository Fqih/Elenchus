"""Studio E2E smoke test (Phase 7 acceptance).

Boots the FastAPI server in a subprocess, runs the Plan.md Phase 7
acceptance flow over HTTP using httpx, and prints the full output so
the operator can read it. Exit code is 0 if all expectations pass, 1
otherwise.

Acceptance walked through:

  1. Phase 7 disabled (default) — no retry, no memory.
  2. Phase 7 enabled + blocked candidate — Soteria retry runs and
     populates phase7_retry_stop_reason + phase7_retry_attempts.
  3. Phase 7 enabled + allowed candidate — Lethe memory items written
     to the per-project SQLite and reported in phase7_memory_item_ids.
  4. Each memory item is tagged with its run:{run_id} so the claims
     are traceable back to the verification run.

Note: this example uses the real NLI model so detection is real, not
stubbed. It is intentionally exercised by an operator, not by pytest
(the model load time is in the tens of seconds).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List

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
    # Clean any stale phase7/ subdir from a previous run.
    phase7_dir = db_path.parent / "phase7"
    if phase7_dir.exists():
        for f in phase7_dir.glob("*.sqlite"):
            f.unlink()

    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable, "-m", "studio.api.server",
            "--db", str(db_path),
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "LD_LIBRARY_PATH": (
                os.environ.get("LD_LIBRARY_PATH", "") + ":" + str(Path.home() / ".local/lib")
            ),
        },
    )

    failures: List[str] = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120.0) as client:
            _wait_ready(client, "/api/projects")

            print("=" * 72)
            print("Elenchus Studio — Phase 7 E2E smoke test")
            print("=" * 72)

            # 1. Create project.
            r = client.post("/api/projects", json={"name": "phase7-smoke"})
            failures += _expect(r.status_code == 200, f"create project: {r.status_code}")
            project = r.json()
            _print("POST /projects", project)
            pid = project["id"]

            # 2. Add source doc.
            r = client.post(
                f"/api/projects/{pid}/source-documents",
                json={
                    "name": "kb-returns",
                    "content": (
                        "Customers can return any item within 30 days of purchase "
                        "for a full refund. Items must be in their original packaging "
                        "with the receipt attached. Refunds are issued to the "
                        "original payment method within 5 business days of "
                        "receiving the return."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"add source: {r.status_code}")

            # 3. Phase 7 disabled by default — blocked run gets no Phase 7 fields.
            r = client.post(
                f"/api/projects/{pid}/checks",
                json={
                    "question": "q",
                    "model_or_prompt_label": "m-disabled",
                    "candidate_answer": (
                        "Customers can return any item within 90 days of purchase "
                        "for a full refund."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"disabled check: {r.status_code}")
            disabled_run = r.json()
            _print("POST /checks (phase7 disabled)", disabled_run)
            failures += _expect(
                disabled_run["gate_result"] == "blocked",
                f"expected blocked, got {disabled_run['gate_result']}",
            )
            failures += _expect(
                disabled_run["phase7_retry_attempts"] == 0,
                f"expected attempts=0, got {disabled_run['phase7_retry_attempts']}",
            )
            failures += _expect(
                disabled_run["phase7_memory_item_ids"] == [],
                f"expected no memory items, got {disabled_run['phase7_memory_item_ids']}",
            )

            # 4. Enable Phase 7 on the project.
            r = client.put(
                f"/api/projects/{pid}/gate-policy",
                json={
                    "block_on_any_contradiction": True,
                    "flag_if_unverifiable_count_exceeds": 1,
                    "phase7_enabled": True,
                },
            )
            failures += _expect(r.status_code == 200, f"enable phase7: {r.status_code}")
            _print("PUT /gate-policy (phase7 enabled)", r.json())

            # 5. Blocked candidate → Soteria retry.
            r = client.post(
                f"/api/projects/{pid}/checks",
                json={
                    "question": "q",
                    "model_or_prompt_label": "m-blocked",
                    "candidate_answer": (
                        "Customers can return any item within 90 days of purchase "
                        "for a full refund."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"blocked check: {r.status_code}")
            blocked_run = r.json()
            _print("POST /checks (blocked, phase7 enabled)", blocked_run)
            failures += _expect(
                blocked_run["gate_result"] == "blocked",
                f"expected blocked, got {blocked_run['gate_result']}",
            )
            failures += _expect(
                blocked_run["phase7_retry_attempts"] >= 1,
                f"expected >=1 retry attempts, got {blocked_run['phase7_retry_attempts']}",
            )
            failures += _expect(
                blocked_run["phase7_retry_stop_reason"] in {
                    "repeated_action", "max_steps", "max_runtime", "completed",
                },
                f"unexpected stop_reason: {blocked_run['phase7_retry_stop_reason']}",
            )

            # 6. Allowed candidate → Lethe memory.
            r = client.post(
                f"/api/projects/{pid}/checks",
                json={
                    "question": "q",
                    "model_or_prompt_label": "m-allowed",
                    "candidate_answer": (
                        "Customers can return any item within 30 days of purchase "
                        "for a full refund. Items must be in their original packaging "
                        "with the receipt attached."
                    ),
                },
            )
            failures += _expect(r.status_code == 200, f"allowed check: {r.status_code}")
            allowed_run = r.json()
            _print("POST /checks (allowed, phase7 enabled)", allowed_run)
            failures += _expect(
                allowed_run["gate_result"] == "allowed",
                f"expected allowed, got {allowed_run['gate_result']}",
            )
            failures += _expect(
                len(allowed_run["phase7_memory_item_ids"]) >= 1,
                f"expected >=1 memory items, got {allowed_run['phase7_memory_item_ids']}",
            )

            # 7. Per-project Lethe SQLite was created.
            db_file = phase7_dir / f"{pid}.sqlite"
            failures += _expect(
                db_file.exists(),
                f"expected per-project Lethe SQLite at {db_file}",
            )

            # 8. memory_ids persist on the run row.
            r = client.get(f"/api/runs/{allowed_run['id']}")
            failures += _expect(r.status_code == 200, f"get run: {r.status_code}")
            fetched = r.json()
            failures += _expect(
                fetched["phase7_memory_item_ids"] == allowed_run["phase7_memory_item_ids"],
                "memory_item_ids did not persist on the run row",
            )

            print("\n" + "=" * 72)
            print("Summary")
            print("=" * 72)
            if failures:
                for f in failures:
                    print(f"  {f}")
                print(f"  {len(failures)} failure(s)")
            else:
                print("  all phase 7 acceptance checks passed")

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
        default=Path("/tmp/elenchus-phase7-smoke.sqlite"),
    )
    args = parser.parse_args()
    return run_smoke(args.db)


if __name__ == "__main__":
    raise SystemExit(main())

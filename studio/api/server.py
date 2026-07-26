"""Studio FastAPI server entry point.

Run with:

    python -m studio.api.server --db /tmp/studio.sqlite --port 8765

Loads the real cross-encoder NLI model on startup so the verify endpoint
is hot. The DB file is created if missing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from elenchus.config import VerificationConfig
from elenchus.nli_verifier import NliVerifier

from studio.api.app import create_app
from studio.db.store import StudioStore


def _build_nli(cfg: VerificationConfig) -> NliVerifier:
    return NliVerifier(config=cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    store = StudioStore(args.db)
    app = create_app(store=store, nli_factory=_build_nli)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

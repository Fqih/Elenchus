# HaluEval QA Benchmark

Phase 11 brings Elenchus onto a publicly-distributed hallucination
benchmark. HaluEval (Li et al., 2023) ships ~7k QA samples sourced from
HotpotQA. Each sample has a source passage, a reference answer, an
adversarial hallucinated answer, and a binary `Hallucination` /
`Not Hallucination` label.

## Setup

```bash
pip install -e ".[eval]"      # installs the `datasets` package
```

## Run

```bash
# Use 100 samples per seed × 3 seeds. Default pool is 8000 (~all of HaluEval QA).
python -m benchmark.halueval_runner \
    --n 100 \
    --seeds 1 2 3 \
    --pool-size 8000 \
    --output benchmark/halueval_results.json
```

The runner writes a JSON file with one entry per seed:

- precision, recall, f1 — treating `contradicted` as the positive class
- label_accuracy, macro_f1 — exact two-class accuracy and macro-F1
- confusion_matrix — 2x2 grid of pred × gold counts

## Mapping

| HaluEval label | Elenchus label |
|----------------|----------------|
| `Hallucination` | `contradicted` |
| `Not Hallucination` | `supported` |

HaluEval does not produce an `unverifiable` tier; we run Elenchus's full
verifier per sample and project any `unverifiable` prediction off-universe
(skipped from metric computation but counted in `n_total`).

## Where the numbers go

This file is intentionally a stub before the real benchmark is run — the
JSON written by `halueval_runner.py` is the source of truth, and this
file gets populated from the JSON via `benchmark/hallueval_results.json`
once a meaningful run completes (HaluEval QA on a CPU takes a few
minutes per 100 samples). A future commit will include the populated
numbers and the Markdown table mirroring `RESULTS.md` (the RAGTruth
report). Until then, run the command above to generate the JSON.

## Caveats (mirrored from `RESULTS.md`)

- This is a CPU-only run; the latency column tracks wall-clock per seed.
- Confidence thresholds use the library default; no special tuning.
- HaluEval's `Not Hallucination` rows are sometimes ambiguous even for a
  strong NLI model; the macro-F1 column reflects that and is the
  honest head-to-head number.

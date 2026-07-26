# Elenchus — Phase 3 benchmark results

Generated on 2026-07-24 from the checked-in RAGTruth artifacts.

## Status

- The primary RAGTruth run is complete: three approaches, three seeds, and
  200 sentence-level claims per seed.
- A separate disputed-case stress run is complete using RAGTruth's explicit
  `implicit_true=true` annotations.
- **FaithBench itself was not run.** The disputed-case run is a development
  proxy and is never presented or combined as a FaithBench result.

Raw outputs:

- `benchmark/data/benchmark_results.json`
- `benchmark/data/stress_results.json`

## Main result

Mean ± population standard deviation across seeds 1, 2, and 3:

| approach | detection precision | detection recall | detection F1 | macro-F1 | exact 3-way accuracy | escalation |
|---|---:|---:|---:|---:|---:|---:|
| cosine | 0.094 ± 0.090 | 0.114 ± 0.103 | 0.103 ± 0.096 | 0.333 ± 0.017 | 0.878 ± 0.010 | 0% |
| NLI-only | 0.134 ± 0.021 | **0.733 ± 0.073** | 0.227 ± 0.034 | 0.366 ± 0.015 | 0.653 ± 0.029 | 0% |
| tiered | **0.144 ± 0.018** | 0.712 ± 0.054 | **0.240 ± 0.027** | **0.372 ± 0.015** | **0.685 ± 0.029** | 31.2% ± 3.7% |

Compared with NLI-only, the tiered path gains 1.0 percentage point of
precision, 1.3 points of detection F1, 0.6 points of macro-F1, and 3.2
points of exact label accuracy. Recall falls by 2.1 points. The result is
therefore a modest precision/accuracy improvement, not a win on every metric.

Cosine's 87.8% exact accuracy is a class-imbalance artifact: it has only
11.4% recall on hallucinated claims. A majority-class-friendly accuracy
number does not make it a useful detector.

## Methodology

### Dataset and semantic labels

`benchmark.prepare_dataset` joins the official RAGTruth `response.jsonl` and
`source_info.jsonl`, keeps `quality == "good"`, and uses the same claim
boundary parser as the Elenchus batch and streaming paths. The resulting
131,962 rows contain:

| gold label | rows | share |
|---|---:|---:|
| supported | 117,590 | 89.1% |
| contradicted | 4,918 | 3.7% |
| unverifiable | 9,454 | 7.2% |

The label mapping is semantic:

- `Evident Conflict` → `contradicted`
- `Evident Baseless Info` → `unverifiable`
- `Subtle Baseless Info` → `unverifiable`
- no overlapping hallucination span → `supported`

When conflict and baseless annotations overlap the same sentence, conflict
takes precedence. Baseless information is not forced into `contradicted`;
absence from a source is not evidence for the opposite claim.

The main run loads the first 5,000 prepared rows, then samples 200 with each
seed. That pool contains 4,714 supported, 120 contradicted, and 166
unverifiable rows. The three evaluated samples contain only 39 hallucinated
rows in total, so precision and recall remain noisy.

### Metrics

Two views are reported:

1. **Hallucination detection** treats both `contradicted` and
   `unverifiable` as positive. Precision, recall, and F1 answer whether the
   gate catches any claim that is not supported by its source.
2. **Exact three-way classification** reports label accuracy and macro-F1.
   Predicting `unverifiable` for an actual conflict can count as a successful
   detection while still being an exact-label error.

This separation avoids treating abstention as either a free exact-label pass
or a missed hallucination.

### Compared approaches

| approach | implementation |
|---|---|
| cosine | `all-MiniLM-L6-v2`; maximum claim/source-sentence cosine ≥ 0.5 means supported, otherwise contradicted. |
| NLI-only | The public production `Verifier` with confidence-gap and NLI-decision thresholds set to zero, no judge, and therefore an explicit forced-decision Tier-1 baseline. |
| tiered | The public production `Verifier` with NLI decision threshold 0.50, confidence-gap threshold 0.15, and a deterministic Tier-2 stand-in. |

For both Elenchus approaches:

- NLI input direction is `(source evidence premise, generated claim
  hypothesis)`.
- Retrieval ranks all source chunks before applying top-k and includes
  adjacent windows of up to four sentences.
- Benchmark code calls `Verifier.verify_claim`; it does not copy the
  production confidence or escalation logic.
- Each benchmark call is required to produce exactly one Verification Log
  entry.

The Tier-2 stand-in checks numerical disagreement, accepts accounted-for
numbers or very high lexical coverage, and otherwise abstains. It is
deterministic for reproducibility, but it is not a substitute for evaluating
a real LLM judge.

## Per-seed stability

| seed | approach | precision | recall | F1 | macro-F1 | accuracy | escalated |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | cosine | 0.067 | 0.091 | 0.077 | 0.345 | 0.880 | 0/200 |
| 1 | NLI-only | 0.111 | 0.636 | 0.189 | 0.383 | 0.685 | 0/200 |
| 1 | tiered | 0.123 | 0.636 | 0.206 | 0.367 | 0.710 | 53/200 |
| 2 | cosine | 0.214 | 0.250 | 0.231 | 0.346 | 0.890 | 0/200 |
| 2 | NLI-only | 0.129 | 0.750 | 0.220 | 0.346 | 0.660 | 0/200 |
| 2 | tiered | 0.143 | 0.750 | 0.240 | 0.393 | 0.700 | 63/200 |
| 3 | cosine | 0.000 | 0.000 | 0.000 | 0.309 | 0.865 | 0/200 |
| 3 | NLI-only | 0.163 | 0.812 | 0.271 | 0.369 | 0.615 | 0/200 |
| 3 | tiered | 0.167 | 0.750 | 0.273 | 0.358 | 0.645 | 71/200 |

Tiered improves exact accuracy on every seed and detection F1 on every seed.
It does not improve macro-F1 on seeds 1 and 3, and it loses one detected
positive on seed 3. Those counter-results are retained rather than hidden by
the mean.

## Disputed-case escalation proxy

This is a **separate RAGTruth proxy**, not a FaithBench result. The first
30,000 prepared rows contain 170 sentences overlapping at least one
`implicit_true=true` annotation. Fifty are sampled per seed.

The corrected stress test compares the actual NLI-only verdict with the
actual tiered verdict. It no longer compares against the no-judge fallback,
which previously made every escalation appear to flip the label.

| seed | total | escalated | labels changed | escalation rate | change rate given escalation |
|---:|---:|---:|---:|---:|---:|
| 1 | 50 | 40 | 9 | 80.0% | 22.5% |
| 2 | 50 | 34 | 13 | 68.0% | 38.2% |
| 3 | 50 | 42 | 10 | 84.0% | 23.8% |
| mean | 50 | 38.7 | 10.7 | **77.3%** | **28.2%** |

The routing threshold is sensitive to these hard cases, but most escalations
do not change the forced-decision Tier-1 label. That means there is still
room to reduce unnecessary Tier-2 work or improve the judge.

## Flagship demo

The five-case synthetic customer-support demo now catches all three
hallucinated answers and leaves both clean answers unflagged:

- detection rate: **100.0%** (3/3)
- false-positive rate: **0.0%** (0/2)

This small hand-authored demo validates the intended workflow; it is not
comparable to the RAGTruth benchmark.

## Limitations

1. Only 39 positive examples occur across the three main samples. A few
   decisions materially move precision and recall.
2. `--pool-size 5000` takes a prefix before seeded sampling, so the run is
   not a full-dataset estimate.
3. The four-sentence evidence-window default was selected using small
   development smoke runs over the same pool and seeds. These are development
   metrics, not an untouched held-out evaluation.
4. The Tier-2 judge is a keyword/numeric stand-in, not an LLM judge.
5. Sentence-level claims can combine multiple atomic facts and make one
   three-way label inherently coarse.
6. The local model still over-flags supported rows: tiered precision is only
   0.144. The current result is useful progress, not production-grade
   calibration.
7. No real FaithBench result exists yet.

## Reproduce

```bash
python -m benchmark.prepare_dataset
python -m benchmark.run_benchmark --n 200 --seeds 1 2 3 --pool-size 5000
python -m benchmark.faithbench_stress --max-n 50 --seeds 1 2 3 --pool-size 30000
python examples/customer_support_demo.py
```

For an already-cached model/dataset in a network-restricted environment:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m benchmark.run_benchmark --n 200 --seeds 1 2 3 --pool-size 5000
```

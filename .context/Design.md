# Elenchus — Design Rationale

This is the *why* behind Architecture.md's *what*. If a future decision seems
to contradict something here, that's worth flagging and discussing, not
silently overriding.

## Why tiered verification instead of one method

An LLM judging another LLM's output is structurally circular — the judge can
hallucinate too, and it's slow and costly to call for every claim. A single
local NLI model alone is fast and non-circular but will genuinely struggle on
ambiguous cases (subtle implication, partial support, numeric approximation).
Tiering gives a default that's cheap and non-circular, with an *optional*
escalation path for the minority of claims that actually need more judgment.
The escalation rate itself (measured in Phase 3) is part of the proof that
this design works as intended — if most claims escalate, the "cheap by
default" claim doesn't hold, and that would need to be reported honestly, not
hidden.

## Why sentence-level claim extraction in v1

Sub-sentence decomposition (splitting compound sentences into finer atomic
claims) would give more precise verdicts, but it typically needs either a
fine-tuned model or an LLM call — reintroducing a dependency the whole point
of Tier 1 is to avoid. Sentence-level extraction is simple, deterministic,
and good enough to prove the core loop works. Finer decomposition is
documented as a deferred improvement (see Plan.md), not treated as a v1
requirement.

## Why span-level evidence, not just a verdict

A bare "claim 3: not supported" tells a developer *that* something's wrong
but not *where* — they still have to re-read the whole source to find out.
Attaching a character-offset evidence span to every verdict turns Elenchus
from a scoring tool into a debugging tool, which is the difference between
"interesting metric" and "something I'd actually use while building a RAG
system."

## Why streaming and batch share one code path

If `StreamingVerifier` had its own verification logic, the two modes could
silently drift apart — a claim verified one way live and a different way in
a post-hoc check. Reusing the exact same Tier 1/Tier 2 pipeline, just fed
incrementally, makes "streaming and batch agree" a property of the
architecture rather than something that has to be manually kept in sync.
This is tested directly in Phase 4 (see Plan.md and Rules.md).

## Why evidence is the NLI premise

Natural-language inference is directional: a premise may entail a broader
hypothesis even when the reverse is not true. Elenchus therefore always sends
the source evidence as the premise and the generated claim as the hypothesis.
Tests must include directional entailment, not only equivalent paraphrases
whose labels happen to be unchanged when the pair is reversed.

## Why retrieval ranks before applying the passage limit

Taking the first N chunks makes document order affect correctness and can omit
the only relevant source in a multi-document check. v1 enumerates every chunk,
ranks individual chunks and bounded adjacent-sentence windows with a
deterministic local lexical score, and only then applies
`max_evidence_passages_per_claim`. Windows allow a sentence-level compound
claim to be supported by nearby source sentences without inventing a
non-contiguous evidence span. NLI remains the semantic decision-maker; the
lexical score only chooses which passages fit in the configured model budget.

## Why RAGTruth as the primary benchmark, and FaithBench separately

RAGTruth is purpose-built for RAG: query, retrieved documents, LLM answer,
and human-annotated span-level hallucination labels — it maps directly onto
Elenchus's claim/evidence model without reinterpretation, and it's the
closest thing to a standard benchmark in this space. FaithBench is curated
specifically from cases where strong models disagree, which makes it the
right instrument for a different question: not "how accurate is Tier 1
overall" but "does the escalation threshold actually catch the hard cases."
Reporting these as two separate results (rather than combining them into one
number) keeps each claim honest about what it's actually measuring.
If FaithBench is unavailable, RAGTruth's explicit `implicit_true=true`
annotations can provide a development proxy for the routing question, but
it must be named explicitly as a proxy and never counted as a FaithBench
result.

The Elenchus rows in the benchmark go through the public `Verifier` pipeline.
Reimplementing its confidence or abstention logic in benchmark code would make
the reported numbers measure a subtly different system.

## Why the Output Gate is a pure function

Gate logic (block/allow/flag) needs to be auditable and easy to reason about
— "why did this get blocked?" should always have a direct, inspectable
answer. Keeping it as `(verdicts) -> GateResult` with no side effects and no
hidden state means the policy can be tested in isolation, changed without
touching the API or frontend, and explained in one sentence.

## Why Soteria/Lethe integration lives in Studio, not in the library

Elenchus's value as a library depends on it staying usable by anyone,
regardless of what else they're using. If verification logic depended on
Soteria or Lethe being present, it would stop being a general-purpose
faithfulness checker and become specific to my own stack. Studio is
explicitly the place where "all three tools together" gets demonstrated —
the library itself stays a clean, independent piece.

## Why Studio v1 is local, single-user, no auth

The goal of Studio is to prove the stack works together in a real workflow,
not to ship a product. Auth, multi-tenancy, and hosting are real engineering
work that would delay the actual point (verdicts, spans, comparison, gate,
integration) without adding to what it demonstrates. If Studio later becomes
something worth hosting, that's a deliberate follow-on decision, not
something to half-build now.

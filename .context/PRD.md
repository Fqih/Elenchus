# Elenchus — Product Requirements Document

## Problem

RAG and agent systems produce answers that sound grounded but sometimes aren't.
A chatbot answering from a knowledge base will occasionally state something
that isn't actually in any retrieved document — not because the model is
"lying," but because generation doesn't guarantee faithfulness to source
material. Existing faithfulness-checking tools mostly do one of two things
badly for a developer trying to debug this: they give a single opaque score
for an entire response ("faithfulness: 0.82" — supported by what, exactly?),
or they rely entirely on an LLM to judge another LLM's output, which is
expensive, slow, and structurally circular (the judge can hallucinate too).

Elenchus checks faithfulness at the level of individual claims, tells you
*which* claim failed and *why*, defaults to a verification method that
doesn't depend on calling another LLM, and only escalates to an LLM judge
when a fast local model is genuinely unsure.

## Who this is for

- Developers building RAG systems who need to catch ungrounded answers before
  they reach a user (support bots, internal knowledge assistants, document
  Q&A tools).
- Anyone evaluating or comparing LLM outputs for faithfulness who currently
  relies on manual spot-checking or a single opaque metric.

## Goals

- Per-claim verdicts (supported / contradicted / unverifiable), not one score
  for a whole response.
- A verification method that works with zero API calls and zero cost by
  default — a local NLI model — with LLM-as-judge as an optional, explicitly
  invoked escalation path for claims the local model can't confidently judge.
- Span-level evidence: which part of the output is the claim, and which part
  of the source supports or contradicts it.
- A benchmarked precision/recall number against a public hallucination
  dataset, not just "it seems to work."
- Usable as a streaming guardrail (check claims as they're generated) as well
  as a post-hoc checker (check a finished response).
- An append-only Verification Log — every claim checked, its verdict,
  confidence, which tier decided it, and the evidence span, all inspectable
  after the fact.

## Non-Goals

- **Generating candidate answers.** Studio v1 does not call an LLM provider
  on the user's behalf — no `GenerationConfig`, no provider adapters, no
  generation endpoint. Users bring their own answer (however it was
  produced) and paste it in. A generate-and-verify flow is a deliberate,
  documented v2 possibility, not a v1 requirement.
- **Document formats beyond plain text and Markdown.** PDF, DOCX, and URL
  ingestion are deferred — v1 source documents are plain text or Markdown,
  uploaded as files or pasted directly.
- Not a general-purpose hallucination detector for *un-sourced* claims (things
  the model states with no source material to check against at all — that's
  a much harder, different problem: calibration/uncertainty estimation, not
  grounding verification).
- Not a replacement for retrieval quality evaluation. Elenchus assumes you
  already retrieved *something* and checks whether the answer is faithful to
  what was retrieved — it doesn't judge whether the right documents were
  retrieved in the first place.
- Not trying to support every language on day one. English first; the NLI
  model choice can be swapped for multilingual variants later without
  changing the architecture.

## Core User Story (flagship demo)

A customer-support RAG bot answers questions from a company knowledge base.
Elenchus sits between the bot's generated answer and the user: it splits the
answer into claims, checks each one against the retrieved knowledge-base
chunks, and flags anything unsupported before the answer is shown (or logs it
for review, depending on configuration). The demo dataset is a synthetic
knowledge base with a mix of clean and deliberately-hallucinated answers, so
the detection rate is measurable and honest, not hand-picked.

## Elenchus Studio (planned Phases 5–7)

The library proves Elenchus works. The planned Studio phases are intended to
prove the whole stack — Elenchus, Lethe, and Soteria together — is something
a developer could actually drop into a real workflow, not just something
that scores well on a benchmark.

Studio is designed as a small local web app, backed by the Elenchus library,
that lets a developer:

- Upload one or more source documents (or paste text directly) to act as the
  grounding material for a check. v1 supports plain text and Markdown only —
  PDF, DOCX, and URL ingestion are deferred (see Non-Goals) to keep this from
  turning into a document-parsing project.
- Paste an existing RAG answer to check. v1 is paste-and-verify only — it
  does not call an LLM to generate a candidate answer on Studio's behalf
  (see Non-Goals and Design.md for why).
- See the answer rendered with each claim color-coded by verdict
  (supported / contradicted / unverifiable), and click a claim to see its
  evidence span highlighted in the source.
- Compare two or more model/prompt configurations side by side on the same
  source + question, to see which one hallucinates less.
- Configure an **output gate**: a policy that blocks, flags, or allows a
  response based on its verdicts (e.g. "block if any claim is contradicted,"
  "flag if more than one claim is unverifiable").
- See verification history for a project — every check that's been run, its
  verdicts, and whether the gate allowed or blocked it.
- When a gate blocks a response, optionally trigger a **Soteria-managed
  retry** — regenerate the answer under a bounded, observable retry loop
  instead of failing silently.
- When a response passes the gate, optionally **write the now-verified
  claims into Lethe** as remembered facts, tagged with their verification
  metadata — so only claims that have actually been checked against source
  material become part of an agent's long-term memory.

### User stories

- As a developer building a support bot, I want to paste a candidate answer
  and my knowledge-base snippet and immediately see which sentences aren't
  actually supported, so I can fix the prompt or retrieval before shipping.
- As someone evaluating two prompt variants, I want to run both against the
  same source and see a side-by-side verdict comparison, so I can pick the
  one that hallucinates less without eyeballing it manually.
- As someone building a longer-running agent, I want verified facts to flow
  into its memory automatically, and unverified or contradicted claims to
  never make it there, without writing that plumbing myself each time.

### Scope for v1

Local, single-user, no auth, no multi-tenant concerns, no hosted deployment.
The goal is "runs on my machine and demonstrates the stack working together,"
not a product launch. Soteria and Lethe integration ship after the core
Studio UI (upload, check, view verdicts, compare) is working end to end —
see Plan.md for the phase order.

## Success Metrics

- Hallucination-detection precision/recall/F1 plus exact three-way label
  accuracy and macro-F1 on **RAGTruth** (chosen over HaluEval/FaithBench because
  it's purpose-built for RAG — query, retrieved documents, LLM answer, and
  human span-level hallucination annotations, which maps directly onto
  Elenchus's claim + evidence-span model) reported with methodology,
  alongside a simple cosine-similarity baseline for comparison. Conflicting
  spans map to `contradicted`; baseless spans map to `unverifiable`; both are
  positive cases for the binary detection metric. FaithBench is used
  separately, when available, specifically to stress-test tier-2 escalation
  on cases models tend to disagree on. Any RAGTruth `implicit_true=true`
  fallback is named and reported as a proxy, never as a FaithBench result.
- Escalation rate: what fraction of claims actually need the LLM-judge tier
  in practice, on the benchmark and on the flagship demo. This number matters
  for the "cost-aware by design" claim — it should be a minority of claims,
  not most of them, or the "non-circular by default" pitch doesn't hold up.
- Latency: local-tier-only verification should be fast enough to run
  claim-by-claim during streaming generation without becoming the bottleneck.

## Out of Scope for v1

- Multi-language support beyond English.
- A hosted/SaaS version — this ships as a library, same as Lethe.
- Automatic claim *correction* (rewriting the ungrounded part) — v1 detects
  and flags, it doesn't fix.

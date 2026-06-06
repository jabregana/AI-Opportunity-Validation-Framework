# Case Study: Building a Schema-Alignment Proxy for Agent Memory

A short technical writeup of how this project was built, what it surfaced, and what the harness was worth. Written for an outside reader (PM lead, infra eng, or technical hiring panel) who wants the story without the full repo dive.

## Problem framing

Five production agent-memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) all share one structural weakness: the same relationship gets written to the graph under multiple surface forms. `WORKS_AT`, `EMPLOYED_BY`, and `JOB_AT` end up as three distinct edge types pointing at the same concept. Retrieval degrades. Every downstream query has to enumerate variations.

Mem0 chose to handle this with an LLM in the extraction prompt. Maintainer kartik-mem0 confirmed on issue #4896 (April 2026): "our v3 SDK handles contradictions by design through the extraction prompt and memory linking, not through an explicit UPDATE/conflict resolution code path." Mem0 also removed graph memory from the OSS distribution in v2/v3.

That left an unoccupied slot: a deterministic write-path proxy that aliases near-duplicate relations before they hit the graph. No LLM in the hot path.

The 90-day landscape scan (`docs/opportunity.md`) verified that adjacent niches (LSP-driven code memory, embedded reasoning-memory event sourcing, real-time graph GC) were each either already shipped by someone else or partially closed. The schema-alignment slot was the only one with on-record evidence the closest incumbent had chosen a different architecture.

## Sequencing decision: harness first, variants second

The first commit in the repo was not a proxy. It was an evaluation harness with workloads, statistical tests, and CI gates. The reasoning: picking a wedge in a moving competitive landscape is easy to get wrong, and iterating on variants without rigorous measurement is how technical debt and miscalibrated claims compound. The first real variant landed against the same gates as every later iteration, so progress (and the two genuine reversals when real data flipped synthetic results) is unambiguous.

The harness uses:

- Per-item B-cubed F1 as the primary clustering metric, bootstrapped paired against a baseline. Replaced an earlier index-resampled pairwise F1 bootstrap that was producing impossible CIs because of a duplicate-pair pathology.
- LORD++ online FDR control instead of vanilla Benjamini-Hochberg, so sequential peeking during development does not inflate type-I error.
- Non-inferiority testing against the previous green commit with a tightened δ = 0.25 of MDE for nightly, δ = 0.5 of MDE for fast PR gates. CUPED variance reduction offsets the resulting sample-size inflation.
- Three operational CI/CD guardrails: INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap recommendation at high null proportion, 14-day cap on stale baselines.
- Two-tier kill-switch design where any structural-rule failure (Tier B false-merge rate) blocks PR regardless of clustering wins.

Full statistical framework: `docs/experiments.md`.

## Iteration record

Five variants shipped, each surfaced something concrete.

| Variant | Approach | What it surfaced |
|---|---|---|
| v0.1.0 token-only | Hashing-trick bag-of-tokens, cosine threshold | Establishes the case/underscore-variant ceiling. F1 = 0.60 on ConceptNet. |
| v0.2.0 neural-only | model2vec potion-base-32M with sentence prompt template | "More complex is better" intuition was wrong. Regressed against v0.1.0 on ConceptNet (-0.12 B-cubed F1, BLOCK_PR). |
| v0.3.0 hybrid | Token + neural concat, token-dominant weighting | Won ConceptNet (+0.04 over v0.1.0). Failed WikiData Tier B at 4.3% false merges (above 1% kill switch). |
| v0.3.1 hybrid + filter | Adds a deterministic structural filter (digit mismatch, trailing preposition asymmetry) | First variant to clear both UC-4.1 superiority and UC-4.4 Tier B kill switch on real WikiData data. GA candidate. |
| v0.4.0 multi-tenant | PerSourceNamespaceProxy with source-prefixed canonicals | Ships the architectural extension for source-attributed resolution. Documented metric and policy gaps for v0.4.1+. |

The most important iteration moment was bringing in the W-WIKIDATA-PROPS workload. ConceptNet alone (synthetic, dominated by case-variant synonyms) ranked v0.3.0 as the winner. Real WikiData property aliases (288 properties, 2457 surface forms, real paraphrases like `head of government` / `premier` / `PM`) flipped the ranking: v0.2.0 won UC-4.1 decisively but failed UC-4.4 at 100% false merges. Without real data we would have shipped the wrong winner.

## Headline numbers

Single-thread latency on the W-WIKIDATA-PROPS workload (UC-4.6):

| Variant | p50 latency | p99 latency | Throughput |
|---|---|---|---|
| b-raw-identity (no proxy) | 0 ms | 0 ms | 7.3M writes/sec |
| v0.1.0 token-only | 3.3 ms | 5.9 ms | 314 writes/sec |
| v0.2.0 neural-only | 2.6 ms | 5.3 ms | 377 writes/sec |
| v0.3.0 / v0.3.1 hybrid | 14.4 ms | 27.4 ms | 70 writes/sec |
| v0.4.0 per-source isolation | 14.5 ms | 27.6 ms | 69 writes/sec |

A reference LLM-in-loop conflict resolver (the Mem0 v3 architecture) runs at 500-2000 ms p50, 5000+ ms p99 on a typical commodity API. v0.3.1 is roughly 30-200x faster. The wedge thesis ("no LLM in the hot path") is now a concrete latency number.

Gauntlet pass status:

| Gate | b-raw | v0.1.0 | v0.2.0 | v0.3.0 | **v0.3.1** |
|---|---|---|---|---|---|
| UC-4.1 ConceptNet B-cubed | 0.41 | 0.60 ★ | 0.48 (regress) | 0.64 ★ | 0.61 |
| UC-4.1 WikiData B-cubed | 0.20 | 0.23 | 0.36 ★ | 0.23 | 0.23 |
| UC-4.4 WikiData Tier B | n/a | 28.6% FAIL | 100% FAIL | 4.3% FAIL | **0% PASS** |
| UC-4.6 p99 latency | 0 ms | 5.9 ms | 5.3 ms | 27.4 ms | **27.4 ms** |
| UC-4.7 held-out accuracy | 0.2% | 28.4% | (untested) | 20.3% | **20.1%** |

v0.3.1 is the first variant to pass all UC-4.x gates simultaneously on real WikiData. v0.1.0 wins UC-4.7 held-out generalization (28.4%) because its lower threshold catches more near-matches; v0.3.1 trades that for Tier B safety.

## Known limits

A probe with real sentence transformers (MiniLM-L6-v2 at 22M parameters and BGE-base-en-v1.5 at 110M; `docs/finding-neural-ceiling.md`) confirmed that bigger neural models do not separate true paraphrases from sibling or antonym hard negatives. The cosine distributions overlap by 55-67% under any tested model. This is the antonym/sibling problem of distributional semantics; cosine reflects training-context co-occurrence, not semantic identity. Bigger models compress the distribution upward, making the overlap worse.

v0.3.1 is therefore at or near the ceiling of off-the-shelf distributional embedders on this task. Further paraphrase coverage requires fine-tuning (expensive, needs labeled corpus), an LLM in the loop (rejected by the wedge thesis), or hand-curated rules. The residual antonym/sibling false-positive class is small, known, and documented.

The v0.4.0 multi-tenant work ships the architecture (variants can consume source-id context, canonicals are source-prefixed) but the naïve per-source isolation regresses on the standard B-cubed F1 metric because it over-isolates globally-unambiguous entities (Microsoft means Microsoft_Corp regardless of which team queries). v0.4.1 needs both a smarter policy (cross-source consensus) and source-aware metrics that reward correct source-conditional disambiguation. The data synthesis required to evaluate v0.4.1 properly is its own work item.

## What the harness was actually worth

Four moments where the harness changed the outcome:

1. **The bootstrap pathology.** An "index-resampled pairwise F1 bootstrap" was the first attempt at a more powerful test. The harness produced impossible CIs (CI lower bound -0.20 with an observed point estimate of +0.013). That impossibility forced investigation. The bug: bootstrap with replacement creates duplicate items that are trivially same-pred-same-oracle for any deterministic variant, inflating the baseline. Per-item B-cubed F1 replaced it. Without the harness producing a result that violated common sense, this bug would have shipped.

2. **v0.2.0 looks like progress but isn't.** "Real neural embedder" intuitively reads as an upgrade from token-overlap. The harness reported it as REGRESSION_DETECTED on ConceptNet (-0.12 B-cubed, BLOCK_PR). Forced re-thinking, leading to the hybrid concat.

3. **Equal-weight hybrid concat regresses against token-only.** The natural default failed. The harness produced -0.08 B-cubed with a CI excluding zero. A parameter sweep found that token-dominant weighting (`tw=2, nw=1`, threshold 0.8) actually beats v0.1.0. Without the harness, a casual "hybrid is better" claim would have been wrong.

4. **WikiData flipped the ranking.** v0.3.0 won on ConceptNet, v0.2.0 won on WikiData. The hybrid was a workload artifact. Without the second workload we would have shipped v0.3.0 publicly believing it generalized.

These are the kinds of mistakes that ship in real teams when measurement is an afterthought. The harness was worth more than any single variant.

## Next steps

- v0.4.1 cross-source consensus variant + source-aware metrics. Needs synthesized multi-tenant workload (see `docs/roadmap.md`).
- Full UC-4.7 with a downstream retrieval system (LongMemEval-S or equivalent) replacing the held-out-split lite version.
- SAFFRON ledger when the rolling 30d null proportion approaches 0.7.
- Always-valid CIs when gauntlets run on hundreds of pairs per night.

The single-tenant story is in good shape. v0.3.1 is the GA candidate. Open questions are about scale, multi-tenancy, and downstream integration, not about whether the core proxy works.

## Candid audit

A separate document, [`GAPS-AND-LIMITATIONS.md`](GAPS-AND-LIMITATIONS.md), audits what the current state of the project does and does not prove. The headline: we have a well-instrumented prototype, not a verified product. The largest gaps are no head-to-head against Mem0, no real agent memory data (LongMemEval is stubbed), no scale tests beyond K ≈ 300 canonicals, and a multi-tenant story that rests on two small workloads we authored ourselves.

## Pointers

- Opportunity: [`docs/opportunity.md`](docs/opportunity.md)
- Test plan + statistical framework: [`docs/experiments.md`](docs/experiments.md)
- Roadmap (v0.4.0+): [`docs/roadmap.md`](docs/roadmap.md)
- Neural-embedder ceiling probe: [`docs/finding-neural-ceiling.md`](docs/finding-neural-ceiling.md)
- README with file tree and run instructions: [`README.md`](README.md)

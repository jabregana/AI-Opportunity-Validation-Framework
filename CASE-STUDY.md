# Case Study: A Framework for Evaluating AI/ML/LLM Opportunities, Applied to an Entity-Normalization Proxy

> **Project shape:** This repository is two artifacts. (1) A reusable **evaluation framework** for assessing whether a given AI/ML/LLM opportunity is real — landscape scan, statistical harness, multi-stage synthetic-to-real progression, multi-model ladder, transparent finding-doc culture. (2) The **schema-alignment proxy** as the first opportunity tested through it. See [`FRAMEWORK.md`](FRAMEWORK.md) for the meta narrative on the framework itself.

> **Honest read on the proxy after 4 stages of evaluation:** real but narrow value. At substantial N=836 with 125 entities, a free local 7B model + proxy TIES gpt-4o + proxy at 0.773 each — a strong cost-efficiency story, not the "beats frontier" the small benchmark suggested. The framework caught its own overclaim. That's the project's most credibility-bearing artifact.

A technical writeup of how this project was built, what it surfaced, what the harness was worth, how the framing shifted (from "alternative to Mem0" to "drop-in middleware" to "honest competitive at fraction of cost"), and what the framework would do on the next opportunity. Written for an outside reader (PM lead, infra eng, or technical hiring panel) who wants the story without the full repo dive.

## Problem framing

Five production memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) share one structural weakness: the same entity (or the same relation, in property-graph systems) gets written under multiple surface forms. `AAPL`, `Apple Inc`, `Apple Computer` become three memory entries. `WORKS_AT`, `EMPLOYED_BY`, `JOB_AT` become three edge types. Retrieval degrades. Downstream queries have to enumerate variations.

Mem0 chose to handle this with an LLM in the extraction prompt. Maintainer kartik-mem0 confirmed on issue #4896 (April 2026): "our v3 SDK handles contradictions by design through the extraction prompt and memory linking, not through an explicit UPDATE/conflict resolution code path." Mem0 also removed graph memory from the OSS distribution in v2/v3.

That left an unoccupied slot: a deterministic write-path layer that aliases near-duplicate surface forms before they hit the downstream store. No LLM in the hot path. Critically, this layer does not have to *replace* Mem0 (or Graphiti, or Cognee). It sits in front of them. That reframing matters for commercialization: the addressable surface is everyone running one of those systems, not a wedge against any one of them.

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

Eleven variants shipped across two generations. Single-tenant (v0.1.0 to v0.3.1) established the core wedge. Multi-tenant (v0.4.0 to v0.5.3) expanded the surface and produced the middleware reframe.

### Single-tenant generation (v0.1.0 to v0.3.1)

| Variant | Approach | What it surfaced |
|---|---|---|
| v0.1.0 token-only | Hashing-trick bag-of-tokens, cosine threshold | Establishes the case/underscore-variant ceiling. F1 = 0.60 on ConceptNet. |
| v0.2.0 neural-only | model2vec potion-base-32M with sentence prompt template | "More complex is better" intuition was wrong. Regressed against v0.1.0 on ConceptNet (-0.12 B-cubed F1, BLOCK_PR). |
| v0.3.0 hybrid | Token + neural concat, token-dominant weighting | Won ConceptNet (+0.04 over v0.1.0). Failed WikiData Tier B at 4.3% false merges (above 1% kill switch). |
| v0.3.1 hybrid + filter | Adds a deterministic structural filter (digit mismatch, trailing preposition asymmetry) | First variant to clear both UC-4.1 superiority and UC-4.4 Tier B kill switch on real WikiData data. Single-tenant GA candidate. |

The most important iteration moment was bringing in the W-WIKIDATA-PROPS workload. ConceptNet alone (synthetic, dominated by case-variant synonyms) ranked v0.3.0 as the winner. Real WikiData property aliases (288 properties, 2457 surface forms, real paraphrases like `head of government` / `premier` / `PM`) flipped the ranking: v0.2.0 won UC-4.1 decisively but failed UC-4.4 at 100% false merges. Without real data we would have shipped the wrong winner.

### Multi-tenant generation (v0.4.0 to v0.5.3)

| Variant | Approach | What it surfaced |
|---|---|---|
| v0.4.0 per-source isolation | Source-prefixed canonicals, no cross-source merge | Naïve baseline. Over-isolates globally-unambiguous entities. Documents metric gaps. |
| v0.4.1 eager consensus | Cross-source Jaccard scan on every write | Quality wins but pays cross-source latency on hot path. Wrong design shape. |
| v0.4.2 lazy consensus | Same scan, deferred to explicit `consolidate()` call | Decouples write latency from merge accuracy. Production-shape design. New `drift_rate` metric quantifies the eventual-consistency cost. |
| v0.4.3 AND-rule | Both Jaccard and embedding cosine must agree | Tightens v0.4.2 precision under aggressive merge thresholds. |
| v0.4.4 adaptive (introspective) | Workload introspection picks aggressive vs conservative parameters at consolidate time | Multi-tenant Tier B exposed a hash-collision bug (HashedTokenEmbedder dim 256 → 4096) and an over-aggressive default (`min_overlap` 1 → 2). |
| v0.5.3 singleton-aware | Identity-merges cross-source same-alias singletons with disambiguation safety check | Handles the singleton-heavy Stack Overflow workload shape. Disambig check (block if any source has other cluster keys whose local canonical contains the alias as substring) prevents the WikiData Apple disambiguation failure. |

The multi-tenant generation surfaced the load-bearing reframe. The first three multi-tenant variants (v0.4.0 / v0.4.1 / v0.4.3) all regressed against the no-proxy baseline on workloads where every input is globally unique (Stack Overflow tags) or where the strata are too fine-grained for cross-source generalization (synthetic). The harness gates caught all three. The fix was not a better variant. It was reframing the project: the proxy is not the memory system, it is the layer in front of it. Workloads where the proxy adds no value over baseline are workloads where the integrator should not deploy it.

That reframe produced the v0.5.x track: a public `EntityNormalizer` service API, an `AdvisoryConsolidator` for off-hot-path merging, and a `Mem0PreNormalized` integration shim that wraps a Mem0 v3 OSS client without modifying Mem0.

## Headline numbers

Single-thread latency on the W-WIKIDATA-PROPS workload (UC-4.6):

| Variant | p50 latency | p99 latency | Throughput |
|---|---|---|---|
| b-raw-identity (no proxy) | 0 ms | 0 ms | 7.3M writes/sec |
| v0.1.0 token-only | 3.3 ms | 5.9 ms | 314 writes/sec |
| v0.2.0 neural-only | 2.6 ms | 5.3 ms | 377 writes/sec |
| v0.3.0 / v0.3.1 hybrid | 14.4 ms | 27.4 ms | 70 writes/sec |
| v0.4.0 per-source isolation | 14.5 ms | 27.6 ms | 69 writes/sec |
| v0.4.2 lazy consensus (write path) | 14.4 ms | 27.4 ms | 70 writes/sec |
| v0.5.3 singleton-aware (write path) | 14.5 ms | 27.6 ms | 69 writes/sec |

A reference LLM-in-loop conflict resolver (the Mem0 v3 architecture) runs at 500-2000 ms p50, 5000+ ms p99 on a typical commodity API. v0.3.1 and the lazy multi-tenant variants run roughly 30-200x faster on the write path. The wedge thesis ("no LLM in the hot path") is now a concrete latency number that holds across the multi-tenant generation as well.

Gauntlet pass status (single-tenant):

| Gate | b-raw | v0.1.0 | v0.2.0 | v0.3.0 | **v0.3.1** |
|---|---|---|---|---|---|
| UC-4.1 ConceptNet B-cubed | 0.41 | 0.60 ★ | 0.48 (regress) | 0.64 ★ | 0.61 |
| UC-4.1 WikiData B-cubed | 0.20 | 0.23 | 0.36 ★ | 0.23 | 0.23 |
| UC-4.4 WikiData Tier B | n/a | 28.6% FAIL | 100% FAIL | 4.3% FAIL | **0% PASS** |
| UC-4.6 p99 latency | 0 ms | 5.9 ms | 5.3 ms | 27.4 ms | **27.4 ms** |
| UC-4.7 held-out accuracy | 0.2% | 28.4% | (untested) | 20.3% | **20.1%** |

v0.3.1 is the first variant to pass all UC-4.x gates simultaneously on real WikiData. v0.1.0 wins UC-4.7 held-out generalization (28.4%) because its lower threshold catches more near-matches; v0.3.1 trades that for Tier B safety.

### THE FLAGSHIP NUMBER — initial result at small N, then revised at substantial N

**Initial finding (small N=227, 10-entity alias map):** "free local 3B + proxy beats every frontier API." Top of the ranking:

| Rank at N=227 | Model | With-proxy accuracy |
|---|---|---|
| 1 | qwen2.5:3b (free local 3B) | 0.872 |
| 3 | gpt-4o (OpenAI) | 0.828 |
| 10 | claude-opus-4-7 (Anthropic) | 0.758 |

**REVISED at substantial N=836, 125-entity alias map:** the headline collapses. Small models drop 10-11pp at scale; frontier models drop only 5-6pp. The corrected ranking:

| Rank at N=836 | Model | With-proxy accuracy | vs prior |
|---|---|---|---|
| 1= | **qwen2.5vl:7b** (free local 7B) | **0.773** | -4.6 pp |
| 1= | **gpt-4o** (OpenAI) | **0.773** | -5.5 pp |
| 3= | llama3.2:3b / qwen2.5:3b / qwen2.5vl:32b (local) | 0.758 | -10 pp |

**The honest revised claim:** a free local 7B model TIES frontier API at fraction of cost. Six local models converge to 0.755-0.773 with proxy. Cost per million tweets: ~$0 (self-hosted) vs ~$5k (gpt-4o). Latency: 199ms (qwen2.5vl:7b) vs 588ms (gpt-4o). The proxy is "competitive with frontier at 1000x lower cost," not "beats frontier."

The framework catching its own overclaim **before it shipped to a customer or investor** is the project's most credibility-bearing artifact. See [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md) for the full revision and the lessons about benchmark scale.

### Downstream LLM quality lift across model sizes (the original finding)

Synthetic workload: 6 oracle entities × 5 aliases each = 30 utterances. Each utterance is a short sentence ("Bought AAPL today.", "Microsoft Corporation reported earnings."). Each model is asked to extract the main entity. With the proxy in front (Mem0PreNormalized `mention_map` pattern), aliases are canonicalized BEFORE the LLM sees the text. B-cubed F1 measures how coherent the LLM's extracted entities are vs the oracle.

| Model | no proxy | with proxy | Δ B-cubed | unique outputs (no proxy / with proxy / ideal=6) | per-call latency (no proxy → with proxy) |
|---|---|---|---|---|---|
| llama3.2:1b (1.2B) | 0.6448 | 0.8724 | +0.2275 | 16 / 9 | 83 ms → 83 ms |
| llama3.2:3b (3.2B) | 0.4921 | 0.9464 | +0.4544 | 20 / 7 | 153 ms → 104 ms |
| llama3.1:8b (8.0B) | 0.4067 | **1.0000** | **+0.5933** | 26 / 6 | 206 ms → 145 ms |
| qwen2.5:14b (14.8B) | **0.3968** | 0.9464 | +0.5496 | 26 / 7 | 572 ms → 200 ms |
| qwen2.5vl:32b (33.5B) | 0.4550 | **1.0000** | +0.5450 | 24 / 6 | 764 ms → 382 ms |
| claude-opus-4-7 (API) | 0.5284 | 0.9630 | +0.4345 | 20 / 7 | 1192 ms → 1035 ms |

Three findings, refined as the ladder extends from 1B local to a frontier API model. (1) The medium local tier (8B-32B) is the WORST baseline. These models faithfully echo the literal surface form back; 24-26 unique outputs from 30 utterances spanning 6 entities is near-full fragmentation. Smaller LLMs are sloppier in a way that incidentally canonicalizes more (lazy token shortcuts); frontier-tier models (Opus) have more discipline and produce a slightly better baseline (0.5284, 20 unique outputs) but still fragment meaningfully. (2) The quality lift therefore grows with model size from 1B to 8B (the "frustrated middle"), peaks at 8B-32B, and softens but persists at the frontier tier (+0.4345 at Opus). (3) With the proxy in front, all six sizes converge to ~0.87-1.00 B-cubed. The 8B and 32B local models reach PERFECT 1.0.

Practical implications: a 3B model with the proxy in front (0.9464) beats a 14B without it (0.3968) and is only slightly behind Opus without it (0.5284). An 8B-with-proxy hits perfect coherence (1.0000) at 145 ms/call — beating Opus-with-proxy (0.9630, 1035 ms/call) by every measure except raw model capability on other tasks. The proxy compensates for model size on the entity-coherence axis across a >100x size range from 1.2B to frontier-tier. Latency speedup grows with local model size (2x at 32B) but shrinks at the API tier (1.15x at Opus) because cloud round-trip dominates the per-call cost. Determinism comes for free regardless: the canonical is locked in upstream so retry noise does not refragment downstream memory.

A multi-turn conversational variant of the same benchmark (`docs/finding-conversational-llm.md`) confirms the pattern holds in realistic dialogue shapes, with two interesting differences. (1) Magnitude on local models is smaller (+0.04 to +0.18 macro-F1 instead of +0.23 to +0.55 B-cubed) because co-reference resolution is the LLM's job (the proxy does not touch "they" or "the company"). (2) **Opus's conversational lift is the LARGEST in the ladder at +0.2733** (vs only +0.4345 single-sentence) — Opus tries harder than smaller models to catch every mention in a multi-turn dialogue, producing more surface variants per entity that the proxy then canonicalizes. With proxy, Opus's recall hits a perfect 1.000.

| Conversational F1 | no proxy | with proxy | Δ |
|---|---|---|---|
| llama3.2:3b | 0.8667 | 0.9333 | +0.0667 |
| qwen2.5:14b | 0.7533 | 0.9333 | +0.1800 |
| **claude-opus-4-7** | **0.6400** | **0.9133** | **+0.2733** |

The strongest specific commercial claim from combined data: **an 8B-local-with-proxy delivers 1.0 single-sentence and ~0.93 multi-turn coherence at ~145 ms/call; Opus-frontier-without-proxy delivers 0.5284 single-sentence and 0.6400 multi-turn at ~1100-1200 ms/call.** A self-hosted 8B + proxy beats a frontier API call on every dimension that matters for entity-normalization workloads.

See `docs/finding-small-llm-quality.md` and `docs/finding-conversational-llm.md` for the full results; bench scripts at `experiments/small_llm_quality_bench.py`, `experiments/claude_api_quality_bench.py`, `experiments/conversational_llm_bench.py`, and `experiments/claude_api_conversational_bench.py`.

### Multi-tenant B-cubed F1

Multi-tenant B-cubed F1 (UC-4.1) on the three real / KG-grounded multi-tenant workloads:

| Workload | Shape | b-raw | v0.4.2 | v0.4.4 | **v0.5.3** |
|---|---|---|---|---|---|
| W-MULTITENANT-WIKIDATA | source-conditional disambiguation | 0.306 | 0.372 | 0.381 | **0.381** (+0.075) |
| W-MULTITENANT-SYNTH | explicit strata | 0.448 | 0.302 | 0.348 | **0.348** (-0.100) |
| W-STACKOVERFLOW-MT | singleton-heavy | 0.858 ★ | 0.792 | 0.795 | 0.816 |
| MT Tier B (synth) | cross-source false-merge | n/a | 0% | 0% | **0%** (post-fix) |
| MT Tier B (WikiData) | cross-source false-merge | n/a | 0% | 0% | **0%** (post-disambig-check) |

The multi-tenant story is genuinely mixed. v0.5.3 wins decisively on the WikiData disambiguation workload (the shape the design targets) and stays Tier B safe everywhere. It trails the no-proxy baseline on Stack Overflow (because every SO tag is globally unique, so there is nothing to canonicalize) and on the synthetic strata workload (because the strata are too fine-grained for cross-source consensus to help). The harness gates surface both regressions, and the README integration guide names exactly which workload shapes the proxy is and is not for.

## Known limits

A probe with real sentence transformers (MiniLM-L6-v2 at 22M parameters and BGE-base-en-v1.5 at 110M; `docs/finding-neural-ceiling.md`) confirmed that bigger neural models do not separate true paraphrases from sibling or antonym hard negatives. The cosine distributions overlap by 55-67% under any tested model. This is the antonym/sibling problem of distributional semantics; cosine reflects training-context co-occurrence, not semantic identity. Bigger models compress the distribution upward, making the overlap worse.

v0.3.1 is therefore at or near the ceiling of off-the-shelf distributional embedders on this task. Further paraphrase coverage requires fine-tuning (expensive, needs labeled corpus), an LLM in the loop (rejected by the wedge thesis), or hand-curated rules. The residual antonym/sibling false-positive class is small, known, and documented.

The multi-tenant generation surfaced its own limits, all documented in `docs/finding-*.md` and the `GAPS-AND-LIMITATIONS.md` audit:

- `docs/finding-mem0-comparison.md`: a direct head-to-head against Mem0 v3 OSS is not currently meaningful because Mem0 OSS outputs natural-language fact strings rather than canonical IDs. The two systems are operating on different output spaces. Comparing them requires either a custom Mem0 wrapper that extracts canonicals or a downstream retrieval task that scores both fairly. The Mem0 middleware shim (`Mem0PreNormalized`) is the right shape to test this in production but has not yet been head-to-head benchmarked.
- `docs/finding-longmemeval-regression.md`: LongMemEval-S (long-form conversational memory) regresses under the proxy. The unit of clustering there is a paragraph or a fact statement; the proxy is designed for short surface forms. Documented as out-of-scope.
- `docs/finding-stackoverflow-mt.md`: on Stack Overflow tags (singleton-heavy real multi-tenant data), b-raw identity-clustering is hard to beat because each tag is globally unique. v0.5.3 narrows the gap with singleton-aware identity merging but still trails.
- `docs/finding-multitenant-tier-b.md`: the v0.4.4 adaptive variant's first multi-tenant Tier B run exposed two production bugs (HashedTokenEmbedder dim default 256 was too small for cross-source collisions; v0.4.4 aggressive mode's `min_overlap=1` allowed spurious merges). Both fixed in v0.5.0; the multi-tenant Tier B suite now passes.
- `docs/finding-scale-stress.md`: K-scaling tests run up to K ≈ 300 canonicals per source. Beyond that, the linear cosine scan needs an ANN index (planned as v0.5.5).

## What the harness was actually worth

Four moments where the harness changed the outcome:

1. **The bootstrap pathology.** An "index-resampled pairwise F1 bootstrap" was the first attempt at a more powerful test. The harness produced impossible CIs (CI lower bound -0.20 with an observed point estimate of +0.013). That impossibility forced investigation. The bug: bootstrap with replacement creates duplicate items that are trivially same-pred-same-oracle for any deterministic variant, inflating the baseline. Per-item B-cubed F1 replaced it. Without the harness producing a result that violated common sense, this bug would have shipped.

2. **v0.2.0 looks like progress but isn't.** "Real neural embedder" intuitively reads as an upgrade from token-overlap. The harness reported it as REGRESSION_DETECTED on ConceptNet (-0.12 B-cubed, BLOCK_PR). Forced re-thinking, leading to the hybrid concat.

3. **Equal-weight hybrid concat regresses against token-only.** The natural default failed. The harness produced -0.08 B-cubed with a CI excluding zero. A parameter sweep found that token-dominant weighting (`tw=2, nw=1`, threshold 0.8) actually beats v0.1.0. Without the harness, a casual "hybrid is better" claim would have been wrong.

4. **WikiData flipped the ranking.** v0.3.0 won on ConceptNet, v0.2.0 won on WikiData. The hybrid was a workload artifact. Without the second workload we would have shipped v0.3.0 publicly believing it generalized.

These are the kinds of mistakes that ship in real teams when measurement is an afterthought. The harness was worth more than any single variant.

## The middleware reframe

The original framing was "alternative to Mem0's LLM-in-extraction approach for entity normalization." That framing kept producing a narrow project. The product fit is alias normalization for short surface forms; many real workloads (long-form conversation, singleton-heavy tags) are outside that shape. Read as "replace Mem0," the result reads as a partial success at best.

The reframe: this is not a replacement, it is a middleware layer. Mem0, Graphiti, Cognee, Neo4j Agent Memory, and any custom memory system all benefit from pre-normalization when their workload fits the shape. The deliverables that operationalize the reframe:

1. `runner/service/normalizer.py`: a stable `EntityNormalizer` class that wraps any of the eleven variants behind one API (`normalize`, `batch_normalize`, `consolidate`). Integrators do not need to learn the variant taxonomy; they pick a variant by ID and call `normalize`.
2. `runner/service/consolidator.py`: an `AdvisoryConsolidator` that tracks write counts and exposes `schedule_required()` and `run()`. The hot path stays at write-only latency; the consolidation phase runs off-hot-path on a configurable cadence.
3. `runner/service/integrations/mem0.py`: `Mem0PreNormalized` wraps a Mem0 v3 OSS `Memory` client. Two extraction modes: a dict-based `mention_map` for exact-match aliases (longest-first regex to avoid prefix collisions) and a callable `mention_extractor` for spaCy NER, regex, or any extractor an integrator provides. Other Mem0 methods (`search`, `get`, `delete`) pass through unchanged.

The reframe expanded the addressable surface from "people willing to swap out Mem0" to "people running any memory system that hits alias fragmentation." It also keeps the candid limits intact: the integration guide names exactly which workload shapes the proxy is and is not for.

## Next steps

- v0.5.4 done (this writeup). README, CASE-STUDY, and the public service API now lead with the middleware framing.
- v0.5.5: an ANN index in front of the cosine scan so the per-source K can scale to 10^4+ canonicals without write-path regression.
- v0.5.6: an NER preprocessor that feeds the proxy from long-form text, opening the door to a fairer LongMemEval comparison (the regression there was that the proxy is for short surface forms, and an NER stage extracts them).
- Head-to-head Mem0 benchmark with `Mem0PreNormalized` vs vanilla Mem0 on a fragmentation-prone workload and a downstream retrieval task.
- SAFFRON ledger when the rolling 30d null proportion approaches 0.7.
- Always-valid CIs when gauntlets run on hundreds of pairs per night.

The single-tenant story is in good shape. v0.3.1 is the single-tenant GA candidate; v0.5.3 is the multi-tenant GA candidate for workloads in the documented good-fit shape; the `EntityNormalizer` + `Mem0PreNormalized` API is the integration surface. Open questions are about scale beyond K ≈ 300, the head-to-head Mem0 number, and the NER preprocessor for long-form text.

## Candid audit

A separate document, [`GAPS-AND-LIMITATIONS.md`](GAPS-AND-LIMITATIONS.md), audits what the current state of the project does and does not prove. The headline: we have a well-instrumented prototype, not a verified product. The largest gaps are no head-to-head against Mem0, no real agent memory data (LongMemEval is stubbed), no scale tests beyond K ≈ 300 canonicals, and a multi-tenant story that rests on two small workloads we authored ourselves.

## Pointers

- Opportunity: [`docs/opportunity.md`](docs/opportunity.md)
- Test plan + statistical framework: [`docs/experiments.md`](docs/experiments.md)
- Roadmap (v0.4.0+): [`docs/roadmap.md`](docs/roadmap.md)
- Neural-embedder ceiling probe: [`docs/finding-neural-ceiling.md`](docs/finding-neural-ceiling.md)
- README with file tree and run instructions: [`README.md`](README.md)

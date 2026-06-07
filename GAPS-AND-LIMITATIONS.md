# Gaps and limitations

A candid audit of what the project does and does not prove. Updated as gaps close (and as new ones surface). The most important gap-closing event was the substantial-N revision in June 2026 that corrected the small-benchmark overclaim.

## TL;DR after 4 stages of evaluation

I have a well-instrumented prototype with a defensible measurement framework. The proxy is incrementally useful for entity-heavy LLM pipelines. It is NOT a market-defining product. The framework catching its own small-N overclaim in stage 4 is the project's most credibility-bearing artifact.

The remaining gaps are smaller and more specific than the original audit suggested. Many big gaps closed; some new smaller ones surfaced.

## What's been closed since the original audit

### Wave 1 (2026-06-06): the original "Items 1-5"

| Original gap | Status | Finding doc |
|---|---|---|
| No comparison against Mem0 | **Closed with nuance.** Mem0 v3 OSS outputs natural-language facts, not canonical IDs. Direct head-to-head was a category error. Followed up with a live wrapper test on a real Mem0 instance. | `docs/finding-mem0-comparison.md`, `docs/finding-mem0-live-wrapper.md` |
| Real UC-4.7 with LongMemEval-S | **Closed, negative result.** All variants regress against b-raw on long-form conversational text (p=1.0000, BLOCK_PR). Narrowed the claim from "agent memory" to "entity normalization in property graphs." | `docs/finding-longmemeval-regression.md` |
| Scale stress test | **Closed, revealed a scaling cliff.** At K ~16k, ingestion throughput collapsed 9x. Led to v0.5.5 ANN index and v0.5.7 multi-tenant ANN. | `docs/finding-scale-stress.md`, `docs/finding-ann-scale.md`, `docs/finding-mt-ann-scale.md` |
| Multi-tenant Tier B fixture | **Closed, caught two real bugs.** HashedTokenEmbedder hash collision and v0.4.4 over-aggressive merge. Both fixed in v0.5.0. | `docs/finding-multitenant-tier-b.md` |
| Real multi-tenant dataset | **Closed, negative result.** Stack Overflow tag dataset shows proxies under-cluster on singleton-heavy data. Led to the v0.5.3 singleton-aware variant. | `docs/finding-stackoverflow-mt.md` |

### Wave 2 (2026-06-06 to 2026-06-07): commercialization battery

| New gap surfaced | Status | Finding doc |
|---|---|---|
| Live Mem0 deployment validation | **Closed.** Wrapper produces canonical-named stored memories (Alphabet 0 to 3, Microsoft 1 to 5, Tesla 1 to 5). Validates at the storage level. | `docs/finding-mem0-live-wrapper.md` |
| Multi-session retrieval F1 | **Closed with nuance.** On a shared-user store, Mem0's own dedup absorbs much of the wrapper's value. Per-tenant deployments still benefit. | `docs/finding-multi-session-mem0.md` |
| Open-world alias coverage (out-of-map entities) | **Closed.** Partial map (2 of 5 aliases) recovers 87% of the full-map lift. Embedding fallback adds another 3.7%. | `docs/finding-open-world-alias.md` |
| Unseen-entity handling | **Closed with a documented limit.** Embedding fallback partially handles unseen entities (5 to 4 alias collapse) but misses acronym/expansion pairs. | `docs/finding-unseen-entity.md` |
| Coreference resolver value | **Closed, negative.** Coref preprocessor regresses (-0.024 F1). LLMs do coreference internally. | `docs/finding-coref-doesnt-help.md` |
| Real-data benchmark at small N | **Closed.** 30 to 269 tweets, +25% surface-variant reduction, +10 pp accuracy. | `docs/finding-real-dataset.md`, `docs/finding-scale-tweet.md` |
| Production case study | **Closed.** 50-entity curated map on 405 real tweets, +7.7 pp accuracy (95% CI +4.7 to +10.9). | `docs/finding-case-study-financial.md` |
| Full LLM ladder at small N | **Closed.** 14 models across 5 providers (Anthropic Opus, OpenAI gpt-4o, Google Gemini Pro/Flash, 10 local). | `docs/finding-full-ladder-sweep.md` |

### Wave 3 (2026-06-07): the substantial-N pressure test

**The biggest gap-closer.** The previous small-N benchmark (N=227, 10-entity map) was tail-biased to famous brands. Scaled to N=836 with 125 entities:

| Original (small N=227) | Revised (substantial N=836) |
|---|---|
| qwen2.5:3b + proxy: 0.872 | qwen2.5:3b + proxy: 0.758 (**-11.4 pp**) |
| llama3.2:3b + proxy: 0.855 | llama3.2:3b + proxy: 0.758 (-9.7 pp) |
| qwen2.5vl:7b + proxy: 0.819 | qwen2.5vl:7b + proxy: 0.773 (-4.6 pp) |
| gpt-4o + proxy: 0.828 | gpt-4o + proxy: 0.773 (-5.5 pp) |
| **Headline:** "3B beats every frontier" | **Headline:** "7B ties frontier at 1000x lower cost" |

Smaller models drop more at scale. Frontier models are more robust to long-tail entities like regional banks, ETFs, and abstract concepts like "Federal Reserve" or "S&P 500." The framework forced this revision before any public claim went out.

Full revision: `docs/finding-substantial-N-revision.md`.

## What remains as honest gaps

These are limits that the gap-closing waves did NOT close. They are smaller and more specific than the original audit suggested.

### Open gaps in the data

| Gap | Severity | How to close it |
|---|---|---|
| Substantial-N full ladder (Opus + Gemini Pro/Flash at N=836) | Medium | About $50 + 30 min of API calls. Completes the revised ranking across all 4 frontier providers. |
| Multi-corpus generalization beyond Twitter | Medium | Add Reuters financial news, Reddit r/wallstreetbets, internal Slack archives. Tests whether the pattern is corpus-specific. |
| Out-of-distribution tweets (no target entity mentioned) | Medium | Currently filtered out. Including them tests precision when the proxy should not fire. |
| Multi-entity tweets | Low to medium | Each tweet currently has one primary oracle. Multi-entity tweets are the harder real-world case. |
| Per-vertical performance (pharma, legal, customer support) | High for commercialization | Build vertical alias maps and run the bench per-vertical. Pharma especially: brand-generic plus FDA Orange Book. |

### Open gaps in the methodology

| Gap | Severity | How to close it |
|---|---|---|
| Semantic-similarity-tolerant metric (vs exact-string) | Medium | Frontier-model verbosity gets penalized as hard as wrong-entity errors. A softer metric (cosine over threshold = match) might shift the rankings. |
| Always-valid CIs (per experiments.md §5.5) | Low | Needed once the gauntlet runs on hundreds of pairs per night. The fixed-N bootstrap is sufficient at the current scale. |
| SAFFRON ledger fully implemented | Low | Only the recommendation gate exists today. Needed once the rolling 30-day null proportion approaches 0.7. |
| Pre-registration log at `runs/registry.md` | Low | Process hygiene. Not load-bearing for current claims. |
| Cache-warmed Mem0 A/B for true latency overhead | Low to medium | The Mem0 latency comparison was confounded by cold vs warm cache. About 30 min to re-run with explicit warming. |

### Open gaps in the production story

| Gap | Severity | How to close it |
|---|---|---|
| No live customer deployment | High for commercialization | Pilot with a real fintech, pharma, or customer-support customer. Turns "rigorous prototype" into "production-validated middleware." |
| Vertical alias map at scale (>500 entities for pharma, etc.) | High for commercial moat | The actual defensible asset is not the proxy code. It is the maintained alias map. Building one is real domain work. |
| Memory store auditor tooling | Medium | "Diagnose fragmentation in your existing memory store" land-and-expand product. Not built. |
| Open-source community + brand | High for distribution | The Datadog/Sentry-style infrastructure brand requires sustained community effort. Not started. |

## What I have explicitly proven I cannot do

These are negative results documented across the project. Treat them as boundary markers. They prevent overselling.

| I cannot | Evidence | Implication |
|---|---|---|
| Cluster long-form conversational memory | `docs/finding-longmemeval-regression.md`. All variants regress, p=1.0. | Do not claim "agent memory" broadly. This is entity normalization. |
| Help via coreference preprocessing | `docs/finding-coref-doesnt-help.md`. -0.024 F1 regression. | LLMs do coref internally. Do not add another step. |
| Canonicalize acronym to expansion without an alias map | `docs/finding-unseen-entity.md`. Embedding misses AAPL to Apple Inc. | Need explicit alias maps for these pairs. |
| Beat frontier on canonical accuracy at substantial N | `docs/finding-substantial-N-revision.md`. Ties, not wins. | Revised commercial claim to "competitive at fraction of cost." |
| Cluster sentence-level paraphrases | `docs/finding-neural-ceiling.md`. Bigger embedders do not help. | Need a fine-tuned model or a different mechanism. |

## What this audit tells you about the project state

- The original "Items 1-5" gaps from the first audit (Mem0 comparison, real UC-4.7, scale stress, Tier B, real MT data) are ALL closed.
- The biggest gap discovered by closing them was the small-N tail-bias overclaim. Now corrected in stage 4.
- The remaining open gaps are smaller, more specific, and have clear paths to close.
- The discipline of documenting closed gaps AND new gaps surfaced is itself the credibility-bearing artifact. The project does not hide what did not work.

## Recommended next experiments, in priority order

1. **Complete the substantial-N ladder.** Run Opus + Gemini Pro/Flash at N=836. About $50, 30 min. Locks in the revised ranking across all four frontier providers.
2. **Apply the framework to a second vertical.** Build a pharma alias map (brand-generic + FDA Orange Book) and run the same evaluation. Demonstrates the framework's reusability AND tests whether the cost-efficiency story holds in a different domain.
3. **Live customer pilot.** Pick a fintech or customer-support company with high-volume entity-extraction load. Deploy the proxy + a curated alias map. Measure cost savings vs their current LLM bill.
4. **Memory store auditor tool.** Build a diagnostic that scans an existing Mem0, Graphiti, or Cognee store, reports fragmentation per entity, and proposes alias-map additions. Land-and-expand wedge.
5. **Apply the framework to a different AI/ML opportunity entirely.** The meta-value of this repo is the framework, not the proxy. Pick the next opportunity. Run it through the same four stages.

## What this audit does NOT cover

- Code quality / maintainability of the proxy itself. (See the test suite. 194 tests passing. No formal coverage report.)
- License implications for commercial deployment. (See LICENSE. FSL-1.1-ALv2. 2-year window before Apache 2.0 conversion.)
- Comparison against academic entity-resolution literature (Senzing, Dedupe.io, py_entitymatching, etc.). The project focuses on the LLM-pipeline use case. Classical ER tools are orthogonal.
- Long-term operational concerns (alias-map drift, multi-region deployment, compliance for regulated industries). Out of scope until there is a live deployment.

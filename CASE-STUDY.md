# Case study: applying the framework to an entity-normalization proxy

> **Read this first.** This repo is two things. (1) A reusable framework for testing whether an AI/ML/LLM opportunity is real. (2) The schema-alignment proxy, which is the first opportunity I ran through it. See [`FRAMEWORK.md`](FRAMEWORK.md) for the full framework narrative.

> **Honest read after 4 stages.** Real but narrow value. At substantial N (836 tweets, 125 entities), a free local 7B model + proxy ties gpt-4o + proxy at 0.773 each. That is a cost story, not the "beats frontier" story the small benchmark suggested. The framework catching its own overclaim is the project's most credibility-bearing artifact. See [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md).

Written for an outside reader (PM lead, infra eng, hiring panel) who wants the story without the full repo dive. Two threads: what the framework did at each stage, and what it surfaced about this specific opportunity.

## The framework's four stages

```
THEORETICAL  ->  SYNTHETIC DATA  ->  REAL DATA  ->  SUBSTANTIAL REAL DATA
   |               |                  |              |
landscape       pilot variants    small benchmarks   scaled benchmarks
scan +          on contrived      on real text       on production-shape
wedge pick      workloads                            workloads
   |               |                  |              |
"is there       "does the         "does it work     "what's the actual
 a slot?"        mechanism         on real text?"    magnitude and
                 work?"                              ranking at scale?"
```

Each stage catches errors the previous missed. Stage 4 caught stage 3's overclaim in this project.

## Stage 1: pick a defensible wedge

Five production memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) share one structural weakness. The same entity, or the same relation, gets written under multiple surface forms. `AAPL`, `Apple Inc`, and `Apple Computer` become three separate memory entries. `WORKS_AT`, `EMPLOYED_BY`, and `JOB_AT` become three separate edge types. Retrieval degrades.

Mem0 chose to handle this with an LLM in the extraction prompt. Maintainer kartik-mem0 confirmed it publicly on issue #4896 (April 2026): "our v3 SDK handles contradictions by design through the extraction prompt and memory linking, not through an explicit UPDATE/conflict resolution code path." Mem0 also removed graph memory from the OSS distribution in v2/v3.

That left an opening: a deterministic write-path layer that aliases near-duplicate surface forms before they hit the downstream store. No LLM in the hot path.

The 90-day landscape scan (`docs/opportunity.md`) tested four candidate wedges. Three were killed:
- LSP code memory was already shipped by `Jakedismo/codegraph-rust`
- Embedded reasoning memory was partially closed by Neo4j Agent Memory's 8 PyPI releases in 83 days
- Real-time graph GC was still open but the signal was weaker

Niche 4 (schema alignment) was the only candidate where the closest incumbent had publicly committed to a different architecture.

**Stage 1 output:** picked Niche 4, documented why the other three were ruled out, set a defensible wedge.

## Stage 2: build the harness, then the variants

I built the harness BEFORE the first variant. The reason: picking a wedge in a moving market is easy to get wrong, and iterating variants without rigorous measurement is how miscalibrated claims compound. The first variant landed against the same gates as every later one.

The harness uses:
- Per-item B-cubed F1 (Bagga and Baldwin, 1998) as the primary clustering metric, bootstrapped paired against baseline. I replaced an earlier index-resampled pairwise F1 bootstrap that was producing impossible confidence intervals because of a duplicate-pair pathology. The harness caught its own design bug.
- LORD++ online FDR control (Ramdas et al. 2017) at q=0.10 instead of vanilla Benjamini-Hochberg. Sequential peeking during development does not inflate type-I error.
- Non-inferiority testing against the previous green commit, with margin tied to MDE per metric (0.25x MDE for nightly, 0.5x MDE for fast PR gates). CUPED variance reduction offsets the resulting sample-size inflation.
- Three CI/CD guardrails: INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap recommendation at high null proportion, 14-day cap on stale baselines.
- A two-tier kill-switch design where any structural-rule failure (Tier B false-merge rate) blocks the PR regardless of clustering wins.

Iteration record:

| Variant | Approach | What it surfaced |
|---|---|---|
| v0.1.0 token-only | Hashing-trick bag-of-tokens, cosine threshold | Establishes the case/underscore variant ceiling. F1 = 0.60 on ConceptNet. |
| v0.2.0 neural-only | model2vec sentence template | "More complex is better" intuition was wrong. Regressed -0.12 B-cubed on ConceptNet, BLOCK_PR. |
| v0.3.0 hybrid | Token + neural concat, token-dominant weighting | Won ConceptNet (+0.04 over v0.1.0). Failed WikiData Tier B at 4.3% false merges (above the 1% kill switch). |
| v0.3.1 hybrid + filter | Adds deterministic structural filter (digit mismatch, trailing preposition asymmetry) | First variant to clear both UC-4.1 superiority and UC-4.4 Tier B kill switch on real WikiData. Single-tenant GA candidate. |

**The most important stage 2 moment** was bringing in the W-WIKIDATA-PROPS workload after starting with synthetic ConceptNet. ConceptNet alone ranked v0.3.0 as the winner. Real WikiData property aliases (2457 surface forms, real paraphrases like `head of government` / `premier` / `PM`) flipped the ranking. v0.2.0 won the main metric on real data but failed the false-merge safety gate at 100%. **Without real data I would have shipped the wrong variant.** This was the first time the framework caught a synthetic-bias overclaim.

**Stage 2 output:** v0.3.1 as the single-tenant GA candidate. Documented findings about the synthetic-to-real ranking flip, the neural-embedder ceiling probe (bigger models do not separate paraphrases from antonyms better), and the structural filter's design.

**Multi-tenant extension (v0.4.0 through v0.5.7):** Six additional variants added per-source isolation, cross-source consensus (eager and lazy), AND-rule safety, adaptive workload introspection, singleton-aware identity merging, and ANN-backed nearest-canonical lookup at scale. Each shipped against the same harness. Key moments: v0.4.2's lazy-consolidation pattern (production-shape design), v0.5.0's bug fixes from multi-tenant Tier B (HashedTokenEmbedder hash collision, v0.4.4 aggressive-merge over-firing), v0.5.5's ANN index restoring sub-linear lookup at K > about 10k.

## Stage 3: real data at small N

I built integration shims for three memory frameworks (Mem0, Graphiti, Cognee) covering three different API shapes (sync client, async client, async module). Each shares the same `mention_map` / `mention_extractor` contract.

I built downstream LLM benchmarks comparing proxy on/off across a model ladder. First on synthetic single-sentence (30 utterances, 6 entities), then multi-turn conversational (10 dialogues), then real Twitter Financial News (initial 30 tweets, then 227 with bootstrap CIs).

Initial 14-model ladder ranking at N=227 with a 34-alias / 10-entity map:

| Rank | Model | Type | With-proxy accuracy |
|---|---|---|---|
| 1 | qwen2.5:3b | Local 3.1B (free) | 0.872 |
| 2 | llama3.2:3b | Local 3.2B (free) | 0.855 |
| 3 | gpt-4o | OpenAI frontier | 0.828 |
| 7 | gemini-2.5-flash | Google frontier | 0.802 |
| 9 | gemini-2.5-pro | Google frontier | 0.775 |
| 10 | claude-opus-4-7 | Anthropic frontier | 0.758 |

**Stage 3 initial headline (overclaim):** free local 3B + proxy beats every frontier API.

This was published in commit history. It was supported by statistical bootstrap CIs at p<0.0001. It was internally consistent across providers. **And it was wrong about magnitude and ranking at scale.** I did not know that yet.

## Stage 4: substantial real data, the headline collapses

I expanded the alias map from 34 aliases / 10 entities to **416 aliases / 125 entities**, covering S&P 500 tech, finance, healthcare, energy, consumer, industrials, indices, ETFs, and fintech. Pulled all matching tweets from the Twitter Financial News validation split: **836 tweets across 103 entities** (3.7x more data, 12x more entities).

Re-ran the local 10-model ladder + gpt-4o on the substantial workload.

| Model | Small N=227 (with proxy) | Substantial N=836 (with proxy) | Drop |
|---|---|---|---|
| qwen2.5:3b | 0.872 | **0.758** | **-11.4 pp** |
| llama3.2:3b | 0.855 | 0.758 | -9.7 pp |
| qwen2.5vl:7b | 0.819 | **0.773** | -4.6 pp |
| **gpt-4o** | **0.828** | **0.773** | **-5.5 pp** |
| llama3.1:8b | 0.806 | 0.755 | -5.1 pp |
| gemma2:9b | 0.811 | 0.757 | -5.4 pp |
| qwen2.5vl:32b | 0.793 | 0.758 | -3.5 pp |
| claude-opus-4-7 | 0.758 | pending re-run | |

**Smaller models drop more at scale (10-11 pp) than frontier models (5-6 pp).** Frontier models have wider world knowledge for long-tail entities (regional banks, ETFs, abstract entities like Federal Reserve or S&P 500). The small benchmark was tail-biased to famous brands.

The revised top of the ranking:

| Rank | Model | Type | With-proxy accuracy | Latency per call |
|---|---|---|---|---|
| 1 (tie) | **qwen2.5vl:7b** | Local 7B (free) | **0.773** | 199 ms |
| 1 (tie) | **gpt-4o** | OpenAI frontier | **0.773** | 588 ms |
| 3 (tie) | llama3.2:3b, qwen2.5:3b, qwen2.5vl:32b | Local (free) | 0.758 | 121-651 ms |

A free local 7B model **ties** gpt-4o at 0.773 each. Six local models cluster at 0.755-0.773. The proxy lifts everyone to a ceiling around 0.77 that the workload itself imposes.

**Stage 4 output:** the corrected commercial claim. The framework catching its own overclaim before it shipped to a customer or investor is the project's most credibility-bearing artifact.

## The substantial commercial story (after stage 4)

**Old claim (overclaim at small N):**
> Free local 3B + proxy BEATS frontier API by 11 pp.

**New claim (defensible at substantial N):**
> Free local 7B + proxy TIES frontier API at 1000x lower cost and 7-8x lower latency. Six local models converge to 0.755-0.773 with proxy.

Cost per million tweets:

| Path | Cost | Accuracy | Latency per call |
|---|---|---|---|
| qwen2.5vl:7b + proxy (self-hosted) | ~$0 | 0.773 | 199 ms |
| llama3.2:3b + proxy (self-hosted) | ~$0 | 0.758 | 121 ms |
| gpt-4o + proxy (API) | ~$5,000 | 0.773 | 588 ms |
| claude-opus-4-7 + proxy (API) | ~$10,000 | ~0.75-0.76 (extrapolated) | 1617 ms |

For about 1.5 pp accuracy at most, you pay 1000x more. The pitch is now "competitive at fraction of cost." Useful for high-volume entity-extraction pipelines. NOT market-defining.

## What stays true after the revision

These claims survive the substantial-N test:

1. **The proxy lift is statistically significant on every well-functioning model.** 9 of 10 local at p<0.0001. gpt-4o at p<0.0001. The lift is real.
2. **The canonical-output-rate lift is universal and large** (+0.25 to +0.58 across all models). This is the most reliable commercial metric.
3. **The latency advantage of local models is huge** (7-13x faster than frontier APIs).
4. **The proxy lift grows with workload difficulty.** llama3.2:3b's lift went from +0.10 at small-N to +0.13 at substantial-N. mistral:7b's lift at substantial-N is +0.15. Harder data, bigger proxy value.

## What the harness was actually worth

Five moments where the harness changed the outcome. Each one a synthetic or small-N overclaim caught before it became a public mistake:

1. **The bootstrap pathology.** An "index-resampled pairwise F1 bootstrap" produced impossible CIs (CI lower bound -0.20 with point estimate +0.013). The impossibility forced investigation. Bug: bootstrap with replacement creates duplicate items that are trivially same-pred-same-oracle for deterministic variants. Per-item B-cubed F1 replaced it. Without the harness producing a result that violated common sense, this bug would have shipped.

2. **v0.2.0 looks like progress but isn't.** "Real neural embedder" intuitively reads as an upgrade. The harness flagged REGRESSION_DETECTED (-0.12 B-cubed, BLOCK_PR). Forced re-thinking, led to the hybrid concat.

3. **Equal-weight hybrid concat regresses against token-only.** The natural default failed. A parameter sweep found token-dominant weighting (token weight 2, neural weight 1, threshold 0.8) actually beats v0.1.0. Without the harness, a casual "hybrid is better" claim would have been wrong.

4. **WikiData flipped the ranking.** v0.3.0 won on ConceptNet, v0.2.0 won on WikiData. The hybrid was a workload artifact. Without the second workload, I would have shipped v0.3.0 publicly thinking it generalized.

5. **Substantial N flipped the headline.** "3B beats frontier" at N=227 became "7B ties frontier" at N=836. Without the four-stage discipline, the original claim would have been published to customers. The framework worked.

These are the kinds of mistakes that ship in real teams when measurement is an afterthought. The harness was worth more than any single variant.

## What this opportunity actually buys you

The proxy is **incrementally useful for entity-heavy LLM pipelines. It is not a market-defining product.**

Where the proxy actually helps:

| Scenario | Why proxy helps |
|---|---|
| Financial news and trading alert routing | Subscribers want alerts on "Tesla." The feed says "TSLA," "$TSLA," "Tesla Motors." |
| Drug name normalization in clinical NLP | LLM extracts "Lipitor." System needs "atorvastatin." The curated alias map is the real value. |
| Per-tenant memory for AI assistants (Mem0, Graphiti, Cognee) | Cross-session entity continuity within isolated user stores |
| CRM auto-tagging from emails and calls | Pre-normalize entity mentions before record lookup |
| Internal knowledge search | Consistent canonical for index quality |

Where it does NOT help (proven negative results):
- General conversational AI (the LLM does coreference internally)
- Long-form text understanding (LongMemEval regression)
- Open-ended entity discovery (embedding fallback misses acronym/expansion pairs)
- Cases already running heavyweight ER tools (Senzing, Tilores, Reltio at the data layer)

## The commercial conclusion

The proxy code is about 50 lines of regex with an alias map. **Any competent engineer can reproduce it in a day.** The code is NOT the product.

What IS defensible, in order of moat strength:

1. **Curated vertical alias maps as a data subscription.** The only real moat. A pharma map covering FDA Orange Book plus brand-generic plus manufacturer aliases takes ongoing maintenance. Same for finance, legal, support routing.
2. **Integration shim maintenance.** Tracking Mem0, Graphiti, Cognee API evolution. Small recurring business.
3. **Benchmark methodology plus reusable harness.** Credibility signal, not a product on its own.
4. **The brand: being known as "the entity normalization people."** Datadog/Sentry pattern, requires distribution.

This is plausibly a $1M to $10M ARR open-source-with-vertical-data-subscriptions business if executed. It is NOT a $1B startup.

## What the framework would do next

The reusable components (harness, statistical gates, integration shim pattern, finding-doc culture, four-stage progression) carry directly to any AI/ML/LLM evaluation. The cost to apply the framework end-to-end on a new opportunity is roughly 4 to 6 weeks, ending in a defensible go/no-go decision backed by data.

**The framework is the durable asset.** The proxy is the first case study. The framework outlived the original headline claim. That is exactly what a good evaluation framework does.

## Pointers

- Framework meta-narrative: [`FRAMEWORK.md`](FRAMEWORK.md)
- Substantial-N revision (the credibility-bearing self-correction): [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md)
- Opportunity / landscape scan (stage 1): [`docs/opportunity.md`](docs/opportunity.md)
- Statistical framework spec: [`docs/experiments.md`](docs/experiments.md)
- Candid audit of what's still open: [`GAPS-AND-LIMITATIONS.md`](GAPS-AND-LIMITATIONS.md)
- All 24 finding docs chronologically: `docs/finding-*.md`
- Repo entry plus run instructions: [`README.md`](README.md)

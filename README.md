# agent-memory-gaps

**Drop-in entity-normalization middleware for LLM memory systems.** Sits in front of Mem0, Graphiti, Cognee, or any custom store. Canonicalizes entity surface forms on the write path so the downstream memory accumulates a coherent graph instead of fragmenting into one entry per alias. Backed by an evaluation harness with online FDR control, CUPED variance reduction, non-inferiority gates, and adversarial false-merge tests so every shipped variant is measured against the same statistical bar.

## What it does

```python
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized
from mem0 import Memory

# Build the proxy (single-tenant) and wrap your existing Mem0 client
norm = EntityNormalizer("embed-proxy-v0.3.1")
m = Mem0PreNormalized(
    Memory(),
    norm,
    mention_map={"AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation"},
)

# Use Mem0 normally; entity aliases get canonicalized BEFORE Mem0's
# LLM sees the text. Net effect: smaller, more consistent memory graph.
m.add("Bought AAPL last week and watching MSFT", user_id="trader1")
```

Two ways to integrate:

1. `EntityNormalizer` service API: wrap any of the bundled variants behind a stable `normalize(surface, context) -> canonical` interface. Drop into your own write path or query rewriter.
2. `Mem0PreNormalized` wrapper: drop-in middleware over a Mem0 v3 OSS client. Pre-normalizes entity mentions in input text before forwarding to Mem0. Reduces store fragmentation without changing Mem0 itself.
3. `GraphitiPreNormalized` wrapper (v0.6.0): same pattern over a Graphiti graph-memory client. Preserves the async `add_episode` / `add_episode_bulk` contract.

Cognee and other memory frameworks can be added behind the same `mention_map` / `mention_extractor` contract; see `runner/service/integrations/` for the wrapper template.

## What problem this addresses

LLM memory systems hit a shared problem: the same underlying entity gets written under multiple surface forms. `AAPL`, `Apple Inc`, `Apple Computer` become three separate memory entries even though they reference the same company. Property-graph systems (Graphiti, Cognee, Neo4j Agent Memory) hit the same problem on the relation side: `WORKS_AT`, `EMPLOYED_BY`, `JOB_AT` become three separate edge types pointing at one conceptual relation.

Mem0's stated stance (per maintainer comment on [issue #4896](https://github.com/mem0ai/mem0/issues/4896), April 2026) is to handle this via the LLM extraction prompt rather than a deterministic write-path resolver. Mem0 also removed graph memory from the OSS distribution in v2.0.0 / v3.0.0. That leaves a slot for a deterministic, fast pre-normalization layer that sits in front of those systems: vector-matches incoming surface forms against existing canonicals and aliases near-duplicates before the write commits. No LLM in the hot path; downstream system stores fewer duplicate entries; canonicals stay stable across reads.

A 90-day scan of the surrounding landscape is in [docs/opportunity.md](docs/opportunity.md). It records why three adjacent niches (LSP-driven code memory, reasoning-memory event sourcing, real-time graph GC) were either already shipped, partially closed, or deferred.

## Where the middleware adds value (and where it doesn't)

The harness has now evaluated the variants on six workloads spanning synthetic, KG-grounded, conversational, and real multi-tenant data. The candid summary:

| Workload shape | Proxy adds value | Notes |
|---|---|---|
| Single-tenant entity aliases with multiple surface forms (WikiData property labels) | Yes, statistically significant | v0.3.1 PASS_AND_MERGE vs no-proxy baseline |
| Multi-tenant with source-conditional disambiguation (WikiData entity disambiguation) | Yes | v0.5.3 +0.075 B-cubed over baseline |
| Multi-tenant singleton-heavy (Stack Overflow tags) | Marginally trails baseline | b-raw's identity-clustering is hard to beat when each input is globally unique |
| Multi-tenant with explicit strata (synthetic) | Marginally trails baseline at safe settings | Aggressive settings trade Tier B safety for B-cubed wins |
| Long-form conversational text (LongMemEval-S adapted) | No, regresses | Proxy is for entity names, not paragraph clustering |
| Mem0 v3 OSS comparison (head-to-head) | Not directly comparable | Mem0 OSS outputs natural-language facts, not canonical IDs |

The product fit is **alias normalization for short surface forms in multi-alias entity stores**. For workloads outside that shape, the proxy adds friction without payoff. The harness gates catch this so it cannot ship unnoticed.

### Downstream LLM coherence: the flagship commercialization number

Across a 1.2B → 3.2B → 14.8B model ladder (Ollama), pre-normalizing entity aliases before the LLM's extraction call delivers a consistent ~0.95 B-cubed F1. Without the proxy, baseline coherence DROPS as model size grows (the 14B model faithfully echoes every surface variant back, hitting 0.3968). The proxy's absolute quality lift is therefore largest at the biggest tier:

| LLM | no proxy | with proxy | Δ B-cubed | per-call latency |
|---|---|---|---|---|
| 1.2B (llama3.2:1b) | 0.6448 | 0.8724 | +0.2275 | 83 ms → 83 ms |
| 3.2B (llama3.2:3b) | 0.4921 | 0.9464 | +0.4544 | 153 ms → 104 ms |
| 8.0B (llama3.1:8b) | 0.4067 | **1.0000** | +0.5933 | 206 ms → 145 ms |
| 14.8B (qwen2.5:14b) | 0.3968 | 0.9464 | +0.5496 | 572 ms → 200 ms |
| 33.5B (qwen2.5vl:32b) | 0.4550 | **1.0000** | +0.5450 | 764 ms → 382 ms |
| frontier (claude-opus-4-7, API) | 0.5284 | 0.9630 | +0.4345 | 1192 ms → 1035 ms |

A 3B model with the proxy beats a 14B model without it. The 8B and 32B both reach PERFECT 1.0 coherence with the proxy and beat frontier-tier Opus without it. The "lift grows with size" pattern peaks at 8B-32B (the "frustrated middle"); softens at the frontier tier because Opus has more discipline to self-canonicalize, but the lift still persists at +0.4345. Latency speedup grows for local models but shrinks at the API tier (cloud RTT dominates). A multi-turn conversational variant ([`docs/finding-conversational-llm.md`](docs/finding-conversational-llm.md)) confirms the pattern in dialogue, smaller magnitude (+0.04 to +0.18). See [`docs/finding-small-llm-quality.md`](docs/finding-small-llm-quality.md).

### When to use this middleware

Good fit:
- Your memory store accumulates short entity references (people, companies, products, tickers, SKUs, place names, technical terms) where the same thing arrives under multiple aliases.
- You can tolerate eventual consistency on cross-tenant canonicalization (the v0.4.2+ lazy consolidation pattern decouples the write path from the merge phase).
- You are paying a per-write LLM tax today for entity normalization and want to drop the latency and cost.

Bad fit:
- Long-form conversational memory where the unit of clustering is a paragraph or a fact statement (see the LongMemEval-S finding).
- Workloads where every input is globally unique (no aliases to canonicalize); the proxy adds cost without benefit (see the Stack Overflow tags finding).
- Cases where the downstream system needs the raw surface forms retained for provenance; the proxy rewrites them upstream.

## Findings to date

The harness has run four variant generations against two workloads (synthetic ConceptNet and real WikiData property aliases) under two use cases (UC-4.1 clustering quality, UC-4.4 false-merge resistance). Headline numbers:

### UC-4.1 B-cubed F1 (clustering quality, higher is better)

| Variant | Approach | ConceptNet (n=131) | WikiData (n=2457) |
|---|---|---|---|
| b-raw-identity | no proxy | 0.407 | 0.197 |
| embed-proxy-v0.1.0 | token-overlap hash | **0.602** ★ | 0.229 |
| embed-proxy-v0.2.0 | neural (model2vec + prompt template) | 0.479 (regressed) | **0.355** ★ |
| embed-proxy-v0.3.0 | hybrid token + neural concat | **0.642** ★ | 0.225 |
| embed-proxy-v0.3.1 | hybrid + structural filter | 0.605 | 0.226 |

The ranking flipped between synthetic and real data. ConceptNet is dominated by case/underscore variants where token overlap is perfect; WikiData has real paraphrases (`head of government` ↔ `premier` ↔ `PM`) that only the neural embedder catches. Without WikiData, we would have shipped v0.3.0 as the winner. Wrong.

### UC-4.4 Tier B false-merge rate (semantic over-clustering, lower is better)

| Variant | ConceptNet (n=11) | WikiData (n=70) |
|---|---|---|
| embed-proxy-v0.1.0 | 0/11 PASS | 20/70 (28.6%) FAIL |
| embed-proxy-v0.2.0 | 11/11 (100%) FAIL | 70/70 (100%) FAIL |
| embed-proxy-v0.3.0 | 0/11 PASS | 3/70 (4.3%) FAIL |
| **embed-proxy-v0.3.1** | **0/11 PASS** | **0/70 PASS** |

UC-4.4 catches what UC-4.1 cannot: a variant that aliases everything semantically similar scores well on clustering but destroys precision on the cases that matter (`ISO 639-1 code` vs `ISO 639-2 code`, `review score` vs `review score by`). v0.2.0 wins UC-4.1 on WikiData decisively, then fails UC-4.4 catastrophically.

### v0.3.1, first variant clearing both gates

v0.3.1 adds a deterministic structural filter on top of v0.3.0's hybrid embedder. Two rules:

- **Digit content differs** → block the merge. Catches ISO codes, version numbers, alpha-N qualifiers.
- **Trailing closed-class preposition asymmetry** → block. Catches `X` vs `X by`, `X` vs `X for`, etc.

The filter is intentionally narrow. It does not touch semantic similarity; it only refuses merges that violate a structural rule. Both rules were derived directly from observed v0.3.0 failures on the WikiData Tier B fixture.

v0.3.1 is the first variant to pass both UC-4.1 superiority (statistically beats v0.3.0 on WikiData at p=0.0000) and UC-4.4 Tier B (0% false merges on both ConceptNet and WikiData fixtures) on real data. It does not beat v0.2.0 on UC-4.1 raw F1 (0.226 vs 0.355) because v0.2.0's neural-only paraphrase coverage is genuinely stronger. The trade-off is intentional: v0.2.0 gets that coverage by aliasing everything, which is unacceptable on the kill switch.

### What the harness has surfaced (worth keeping in mind)

- A flawed bootstrap design (index-resampled pairwise F1) was caught by the harness producing impossible CIs. Replaced with per-item B-cubed F1 bootstrap.
- The "more complex is better" pattern fails decisively: v0.2.0 looks like an upgrade but regresses on ConceptNet UC-4.1 and fails UC-4.4 100%.
- Equal-weight hybrid concat regresses against token-only; the neural cosine acts as a veto on case variants where it is weak. Token-dominant weighting fixed it.
- Two synthetic-data findings (v0.1.0 best on ConceptNet, v0.3.0 winning the hybrid) both reversed on real data. Synthetic workloads under-test.

## Status

Active iteration. Eleven candidate variants, seven workloads (six implemented, one stubbed pending NER integration), four use-case gates wired (UC-4.1 clustering, UC-4.4 false-merge, UC-4.6 latency, UC-4.7 lite held-out). Public service API (`EntityNormalizer`, `AdvisoryConsolidator`) and a Mem0 v3 integration shim (`Mem0PreNormalized`). 148 tests.

The variant under active iteration is v0.5.3 (singleton-aware with disambig safety check). v0.3.1 remains the single-tenant GA candidate. See `GAPS-AND-LIMITATIONS.md` for the candid view of what is and isn't proven yet.

## What's in this repo

```
fixtures/
  manifest.json                              workload registry
  workloads/
    w_conceptnet_rel.py                      131 entries (synthetic case-variant baseline)
    w_wikidata_props.py                      2457 entries from real WikiData property aliases
    w_multitenant_synth.py                   516-entry multi-tenant with explicit strata
    w_multitenant_wikidata.py                138-entry KG-grounded multi-tenant
    w_stackoverflow_multitenant.py           211-entry real multi-tenant from SO tags
    w_longmemeval_s.py                       1000-entry LongMemEval-S adapted for clustering
  generators/
    wikidata_aliases.py                      WikiData property fetcher
    wikidata_disambiguation.py               disambiguation candidate fetcher
    stackoverflow_tags.py                    Stack Overflow related-tags fetcher
    tier_b_adversarials.py                   single-source hard-negative miner
    multitenant_tier_b.py                    cross-source hard-negative miner
  adversarials/
    conceptnet_tier_b.json                   11 single-source pairs
    wikidata_tier_b.json                     70 single-source pairs
    multitenant_tier_b_wikidata.json         17 cross-source pairs
    multitenant_tier_b_synth.json            79 cross-source pairs
runner/
  service/                                   public API for integrators
    normalizer.py                            EntityNormalizer
    consolidator.py                          AdvisoryConsolidator
    integrations/mem0.py                     Mem0PreNormalized
  variants/
    base.py                                  Variant ABC
    b_raw.py                                 identity baseline
    stub_proxy.py                            hash-bucket sanity check
    embed_proxy.py                           v0.1.0 token, v0.2.0 neural, v0.3.0/v0.3.1 hybrid + filter
    per_source.py                            v0.4.0 to v0.5.3 (multi-tenant: per-source, eager and lazy consensus, AND-rule, adaptive, singleton-aware)
    neural_embedder.py                       model2vec adapter with sentence template
    structural_filter.py                     digit-mismatch and trailing-preposition rules
  metrics/
    alignment.py                             pairwise F1, per-item B-cubed F1
    stats.py                                 paired bootstrap, McNemar
  fdr.py                                     LORD++ online FDR ledger
  cuped.py                                   CUPED variance reduction
  gates.py                                   INCONCLUSIVE-is-FAIL, SAFFRON-swap, B-VPREV-cap
  artifacts.py                               immutable three-block run-artifact writer
  runner.py                                  entrypoint with UC-4.1, UC-4.4, UC-4.6, UC-4.7 modes
experiments/                                 standalone analysis scripts
  mem0_baseline.py                           Mem0 v3 OSS probe
  scale_stress.py                            K-scaling latency/quality sweep
  multitenant_tier_b_score.py                MT Tier B variant scorer
tests/                                       148 unit tests, all passing
docs/
  opportunity.md                             wedge selection and 90-day landscape scan
  experiments.md                             test plan and statistical framework
  roadmap.md                                 v0.4.0+ multi-tenant and other open work
  finding-*.md                               seven findings (neural ceiling, noise robustness,
                                             cadence invariance, Mem0 comparison, LongMemEval
                                             regression, MT Tier B, Stack Overflow MT, scale)
GAPS-AND-LIMITATIONS.md                      candid audit of what does and does not generalize
CASE-STUDY.md                                tight technical narrative
```

## Integration patterns

### Pattern 1: as a service in your own pipeline

```python
from runner.service import EntityNormalizer, AdvisoryConsolidator

# Single-tenant
norm = EntityNormalizer("embed-proxy-v0.3.1")
canonical = norm.normalize("Apple Inc")
batch = norm.batch_normalize(["AAPL", "Apple Computer", "Apple Inc."])

# Multi-tenant (per-source disambiguation + lazy consolidation)
norm = EntityNormalizer("embed-proxy-v0.5.3-singleton-aware")
canonical = norm.normalize("Apple", context={"source_id": "finance"})

# Advisory consolidator schedules cross-source merges off the hot path
consolidator = AdvisoryConsolidator(norm, schedule_every_n_writes=1000)
if consolidator.schedule_required():
    consolidator.run()  # run in a background thread / cron job
```

### Pattern 2: as middleware in front of Mem0 v3 OSS

```python
from mem0 import Memory
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized

norm = EntityNormalizer("embed-proxy-v0.3.1")
m = Mem0PreNormalized(
    Memory(),
    norm,
    # Either a static alias map ...
    mention_map={"AAPL": "Apple Inc.", "MSFT": "Microsoft"},
    # ... or a callable extractor (spaCy NER, regex, LLM, etc.)
    # mention_extractor=my_ner_function,
)
m.add("Bought AAPL today", user_id="trader1")
# search / get / delete pass through unchanged
```

### Pattern 3: head-to-head harness runs

```sh
# UC-4.1: clustering quality, paired bootstrap vs a baseline
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --baseline embed-proxy-v0.3.0 \
  --workload W-WIKIDATA-PROPS \
  --use-case UC-4.1 \
  --tier fast

# UC-4.4: false-merge rate on the Tier B adversarial fixture
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --use-case UC-4.4 \
  --tier-b-fixture fixtures/adversarials/wikidata_tier_b.json \
  --tier fast
```

Both write a JSON artifact under `runs/` in the three-block schema described in [docs/experiments.md](docs/experiments.md) section 6.1.

Optional: `pip install -e .[neural]` to install model2vec for v0.2.0 / v0.3.0 / v0.3.1 and the multi-tenant variants. v0.1.0 needs no extra deps.

## Tests

```sh
python -m pytest tests/
```

148 tests cover the embedders, the variants (single-tenant and multi-tenant), the statistical machinery (LORD++, CUPED, paired bootstrap, McNemar), the three CI/CD gates, the structural filter, the public service API (`EntityNormalizer`, `AdvisoryConsolidator`), the Mem0 middleware shim, and the end-to-end pipeline.

## Statistical framework, in one paragraph

The harness uses an online FDR procedure (LORD++ at q=0.10) rather than vanilla Benjamini-Hochberg, so that sequential peeking during development does not inflate the type-I error rate. Each candidate proxy version is compared against the previous green commit using non-inferiority testing with a tightened margin (0.25 of MDE for nightly, 0.5 of MDE for fast PR gates). CUPED variance reduction lets the harness afford the tighter margin without quadrupling sample size. Three operational guardrails (INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap at high null proportion, 14-day cap on stale baselines) protect the gate from common automation failures. Full spec in [docs/experiments.md](docs/experiments.md).

## Design priority: write latency vs merge accuracy

The proxy separates two concerns that prior agent-memory frameworks couple together.

**Write latency is a hot-path constraint.** Every ingestion pays the inner variant's cost (deterministic embedding plus cosine search): roughly 27 ms p99 today across all variants v0.3.1 through v0.4.2, with a hard 100 ms p99 kill switch. No LLM in the hot path. No cross-source consensus computation on the write itself.

**Cross-source merge accuracy is a consolidation concern.** Cross-source intelligence (recognizing that sales' "Microsoft" and ops' "Microsoft" mean the same entity) accumulates in a separate consolidation phase. Run it every 100 writes, every shift, every night. Whatever cadence matches operational tolerance for eventual consistency.

This separation is the wedge against LLM-in-the-loop designs (Mem0 v3): they pay 500-2000 ms per write for what we accumulate offline. The trade-off we accept is that two writes minutes apart may see different merge states until the next consolidation runs. For agent memory the trade is correct. Write velocity matters; instant cross-source unification does not.

Concretely, the variants implement this:

| Variant | Write path | Merge timing |
|---|---|---|
| v0.4.0 per-source | inner variant only | never (no merge) |
| v0.4.1 consensus (eager) | inner + O(K) Jaccard scan | every write |
| **v0.4.2 lazy consensus** | **inner only** | **explicit `consolidate()` call** |

v0.4.2 is the production-shape design: write path serves online traffic at v0.3.1 latency; `consolidate()` runs as a background job on a configurable cadence. The harness implements this by running `consolidate()` between pass 1 (ingest) and pass 2 (re-query). A `drift_rate` metric reports the fraction of writes whose pre-consolidation canonical differs from the post-consolidation canonical, so the operational cost of lazy consolidation is always visible.

## Why this exists before the proxy does

Picking a wedge in a moving competitive landscape is easy to get wrong. The opportunity scan and the harness are deliberate sequencing: first establish that the niche is real and unoccupied, then put the measurement infrastructure in place, then build the proxy. The first real candidate variant landed against the same gates as every later iteration, so progress (and the two genuine reversals when real data flipped synthetic results) is unambiguous.

For a tighter narrative of the project (problem framing, decision sequencing, iteration record, known limits, what the harness was actually worth), see [`CASE-STUDY.md`](CASE-STUDY.md). For a candid audit of what the current state does and does not prove, see [`GAPS-AND-LIMITATIONS.md`](GAPS-AND-LIMITATIONS.md).

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, after which that release converts automatically to Apache 2.0.

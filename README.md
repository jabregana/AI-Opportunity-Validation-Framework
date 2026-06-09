# AI-Opportunity-Validation-Framework

**A repeatable framework for deciding whether an AI/ML/LLM opportunity is worth building.**

Most AI teams operate as: idea -> prototype -> launch. By the time the prototype is in front of a customer, the team has already spent months on the wrong shape, the wrong claim, or the wrong wedge. The customer reaction is the first real test.

This framework inserts four tests **before** the customer sees anything:

```
idea -> kill test -> synthetic validation -> small-N real data -> substantial-N real data -> deployment recommendation
```

Each test catches errors the previous one missed. Most opportunities die at one of the earlier stages, which is the point. The ones that survive arrive at the customer pre-corrected, with a deployment recipe, measured technical numbers (store reduction, F1 preservation, p99 latency, false-collection rate), and a business-outcome translation built on top of those numbers. The translation stays an estimate until a customer reports their own outcomes from a production deployment; the technical numbers are real measurements from real runs.

The framework is the durable asset. The individual opportunities tested through it are the case studies that show it works.

## The ambition

Run any AI/ML/LLM opportunity through this framework in four to six weeks and finish with one of two outcomes:

- **Go**: a specific deployment recipe (variant + config + sweep cadence + rollback signal), backed by measured numbers from real data, with the business-outcome translation written down
- **No-go**: a documented kill, including which stage caught it and what the evidence was

The framework's defensibility comes from doing this **across every dimension of an agent system** (model, prompt, tools, memory, policy, recovery) with the same statistical discipline, and from **forcing deployment decisions** out of the joint result. Most agent-eval tooling stops at "here are the traces" or "here is one axis tested." This one continues to "and so the team should ship X, not Y."

What the framework does NOT do: invent new mechanisms. Entity normalization, graph GC, prompt benchmarking all exist. The novelty is the **same statistical discipline applied uniformly + forced deployment decisions emerging from the data**.

## What the framework consists of

| Layer | What it does | Where it lives |
|---|---|---|
| Four-stage progression | Forces theoretical -> synthetic -> small real -> substantial real, in that order | [`FRAMEWORK.md`](FRAMEWORK.md) |
| Per-experiment UC gates | Calibrated pass/fail thresholds on store reduction, retrieval recall, false-collection, latency, tombstone recovery, retrieval F1 | `runner/gc_runner.py` |
| Per-variant effect detection | Paired bootstrap (10k resamples), one and two-sided p-values | `runner/metrics/stats.py` |
| Cross-variant FDR control | LORD++ online FDR ledger (Ramdas et al. 2017) for sequential testing | `runner/fdr.py` |
| Variance reduction | CUPED (Deng et al. 2013) cuts required N by 20-40% when prior baselines exist | `runner/cuped.py` |
| Cross-dimension matrix | Joint 72-config experiment across all six dimensions; surfaces interactions | `experiments/cross_dim_full_matrix.py` |
| Integration shim contract | One ABC adapts any downstream memory framework (Mem0, Graphiti, Cognee) into the gate-tested variant pipeline | `runner/dimensions/memory/lifecycle/integrations/base.py` |
| Finding-doc discipline | Every claim, including failures and retractions, gets a dated `docs/finding-*.md` | `docs/finding-*.md` (30+) |
| CI regression gate | Every PR re-runs the F1 benchmark, fails the build if any variant drops below 75% F1 preservation | `.github/workflows/ci.yml` |

## The two opportunities tested through it

I ran two real opportunities through all four stages. Both started from a 90-day landscape scan ([`docs/opportunity.md`](docs/opportunity.md)). Both produced revisable, deployable, measured outcomes.

### Opportunity 1: Schema-alignment proxy (entity normalization middleware)

Sits in front of Mem0, Graphiti, or Cognee. Intercepts entity writes, vector-matches against existing canonicals, substitutes the canonical before the LLM-extraction layer creates a duplicate node. Deterministic, no LLM in the hot path, ~30 ms p99.

### Opportunity 2: Agent Memory Lifecycle Management (graph GC)

Sits behind Mem0, Graphiti, or Cognee. Sweeps stale facts, preserves entities, tracks tombstones for over-collection recovery, supports per-tenant pinning. Eight deployment-shaped policy variants (passed all UC gates on synthetic + real-text workloads; pending one customer pilot for production-validated status). Drop-in middleware around any of the three frameworks.

## Results: what each produced

### Opportunity 1 results (entity-normalization proxy)

Four stages, four-stage-progression-caught-an-overclaim:

| Stage | Output | What the framework caught |
|---|---|---|
| Stage 1 | Wedge picked: Mem0 maintainer publicly rejected this approach on issue #4896 (April 2026) | Killed three other candidate wedges that incumbents had already shipped |
| Stage 2 | v0.3.1 (hybrid + structural filter) became GA candidate after ranking flipped on real WikiData aliases | Synthetic-data winner v0.3.0 was beaten on real data; framework caught its own statistical bootstrap bug mid-pilot |
| Stage 3 | At N=227: "free local 3B beats every frontier API" (p < 0.0001) | Headline was statistically significant but wrong |
| Stage 4 | At N=836 with 416-alias map: ranking collapsed; correct claim is "free local 7B ties gpt-4o at 0.773 with ~1000x lower cost" | Stage 4's 5-10x scale-up caught the small-N tail bias before publication |

The framework catching its own Stage 3 overclaim is the single most credibility-bearing artifact this project produced. Full self-correction: [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md).

### Opportunity 2 results (memory lifecycle management)

Three end-to-end results with real Mem0 (Ollama phi3:mini + all-minilm + Qdrant) this week:

| Workload | What it measures | Result |
|---|---|---|
| 2,000 SQuAD-style inputs, sweep every 100 | Steady-state store reduction over a 2-hour run | Mem0 LLM extracted 3,363 memories; v0.1.8 collected 3,308. **98.4% reduction**, 0 failures, clean sawtooth (50-65 surviving, 200-320 pre-sweep) |
| 50 SQuAD Q&A pairs, F1 preservation before/after sweep | Retrieval quality preservation under GC | **81.6% F1 preservation at 52% reduction**. UC-GC-RETRIEVAL gate (>= 80%) PASS |
| 200 SQuAD Q&A pairs (4x replication) | Same, larger N | **81.8% F1 preservation at 44% reduction**. PASS. Replication confirms n=50 estimate within 0.2pp |

Plus 14 unit tests on the Graphiti adapter, 13 on the Cognee adapter, 9 cross-adapter consistency tests. All three adapters compose with v0.1.x policies identically at the contract level.

**Important caveat surfaced 2026-06-09:** End-to-end Graphiti F1 benchmarks (three scenarios; see [`docs/finding-graphiti-f1-stage5.md`](docs/finding-graphiti-f1-stage5.md)) showed that v0.1.x variants return 0% reduction on Graphiti's edge-rich graph because the `in_degree == 0` orphan-node check at the heart of every v0.1.x rule rarely triggers when entities are connected by edges. This is an architectural assumption baked into v0.1.x that holds in flat-memory frameworks (Mem0) but not in graph-native ones (Graphiti, likely Cognee). The Mem0 numbers above stand; the Graphiti and Cognee paths await a v0.2.x variant family designed for graph topology rather than orphan-node assumption. This is the second time the framework caught itself surfacing a real limitation (first was the entity-norm Stage 3-to-4 ranking flip).

### Bonus: the cross-dimension result

A 72-config matrix joint experiment across all six dimensions found **75% of "obvious" variant combinations LOSE vs baseline**, and the top-10 all use baseline tools. The framework's current cross-dimension deployment recommendation: `prompt-v0.1.4-cot-plus-structured + b-allow-all-tools + recovery-v0.1.1-fallback-chain`, ~59.6% completion at CI [55.0-63.6], +23pp over baseline. Cost-weighted top-1 and top-2 are statistically indistinguishable, so the cheaper one wins. See [`docs/finding-cross-dim-cost-weighted.md`](docs/finding-cross-dim-cost-weighted.md).

## Where each opportunity stands on commercialization

| Opportunity | Stage | What's deployable today | What's missing for commercialization |
|---|---|---|---|
| Entity-norm proxy | 4 (substantial real data) | `embed-proxy-v0.5.7-mt-ann` (multi-tenant, ANN-backed) + drop-in middleware for Mem0/Graphiti/Cognee | Vertical alias maps as a paid subscription (pharma, finance, legal). Without those, the proxy itself is ~50 lines of regex anyone can rewrite. |
| Memory lifecycle (Mem0 path) | 5 (real LLM + real adapter at production-realistic scale) | `gc-v0.1.8-comprehensive-tuned` + Mem0 adapter + production runbook + CI regression gate | One customer running the Mem0 bundle in production for 30 days. That's the only remaining gap between "research asset" and "product" for the Mem0 path. |
| Memory lifecycle (Graphiti / Cognee path) | 5 (architectural limitation surfaced) | Adapters exist as real code, but v0.1.x rules return 0% reduction on edge-rich graphs (see [`docs/finding-graphiti-f1-stage5.md`](docs/finding-graphiti-f1-stage5.md)) | A v0.2.x variant family designed for graph topology rather than orphan-node assumption. Estimated 2-3 weeks Stage 1-2 effort. |

Both are within one focused engagement of being commercial. The memory lifecycle work is closer because the deployable bundle has measured numbers from this week's runs and a documented runbook. The entity-norm work needs vertical content (alias maps) to become defensible beyond the harness itself.

What does NOT get added next: more dimensions, more variants, more statistical machinery. The framework has enough. What gets added next: **one customer who runs a recommendation in production and reports their actual business outcome.**

---

## Opportunity 1 deep dive: schema-alignment proxy

### The wedge

I studied agent memory tools (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) for 90 days. They all share five problems: fragmented extraction, graph explosion, schema rigidity, cold extraction tax, no reasoning memory. Sitting in front of them as middleware is the cleanest opening.

I considered four candidate wedges:

| Wedge | Already taken? |
|---|---|
| LSP code memory graph | Yes. `Jakedismo/codegraph-rust` (786 stars) ships this exact pipeline |
| Reasoning memory in SQLite | Mostly. Neo4j Agent Memory shipped 8 PyPI releases in 83 days covering this |
| Real-time graph GC | Not yet, but the operational definition was fuzzy (became Opportunity 2 below) |
| Schema-alignment proxy | Not yet, and Mem0 maintainer rejected this approach on the record (issue #4896, April 2026) |

I picked the schema-alignment proxy because the incumbent's public rejection is the cleanest signal a wedge will stay open. Full landscape: [`docs/opportunity.md`](docs/opportunity.md).

### The mechanism

```python
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized
from mem0 import Memory

norm = EntityNormalizer("embed-proxy-v0.5.7-mt-ann")          # multi-tenant ANN-backed
m = Mem0PreNormalized(Memory(), norm, mention_map={"AAPL": "Apple Inc", "MSFT": "Microsoft"})
m.add("Bought AAPL today", user_id="trader1")
```

Same shape for `GraphitiPreNormalized` and `CogneePreNormalized`. All three share a 50-line adapter contract.

### What the proxy buys you

| Where it helps | Where it does not |
|---|---|
| Financial news + trading alert routing | General conversational AI (the LLM does coreference on its own) |
| Drug name normalization in clinical NLP | Long-form text understanding |
| Per-tenant memory on Mem0 / Graphiti / Cognee | Open-ended entity discovery beyond surface-form variation |
| CRM auto-tagging | Workloads already running Senzing / Tilores |

### Commercial position

Plausibly a $1M to $10M ARR business. Not a $1B startup. The proxy code is ~50 lines anyone can rewrite. **The moat is curated vertical alias maps (pharma, finance, legal) sold as a subscription**, plus integration-shim maintenance as the upstream APIs evolve. The benchmark methodology and the harness itself are the brand asset, not the code.

## Opportunity 2 deep dive: Agent Memory Lifecycle Management

### The wedge

Same 90-day landscape scan. Real-time graph GC was the second wedge I considered. The operational definition was fuzzy initially (when does "GC" fire? what does it preserve?), but the synthesis became `gc-v0.1.8-comprehensive-tuned`: fact collection + tombstone log + per-tenant pinning + tuned entity rule.

### The mechanism

```python
from mem0 import Memory
from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import Mem0GCMiddleware
import time

memory = Memory.from_config(your_config)
variant = build("gc-v0.1.8-comprehensive-tuned")
mw = Mem0GCMiddleware(memory)

# Anywhere you called memory.add(...), call mw.add(...) instead
mw.add("User likes oat milk", user_id="alice")
results = mw.search("dietary preferences", user_id="alice")

# Schedule a periodic sweep (every 4 hours is a safe default for < 10K adds/day)
mw.sweep(variant, current_time=time.time())
```

Same shape for `GraphitiGCMiddleware` (graph-native, async) and `CogneeGCMiddleware` (module-level API). Cross-adapter consistency: `tests/test_cross_adapter_consistency.py`.

### Production recipe

```
Variant:          gc-v0.1.8-comprehensive-tuned
Sweep cadence:    every 4 hours for typical loads (workload-specific in runbook)
Knobs:
  min_age_seconds       86400   1 day grace before fact collection
  min_query_count       3       entities with 3+ queries always survive
  tombstone_ttl_seconds 604800  7 days "soft delete" window
Rollback:         stop calling mw.sweep(); middleware degrades to pass-through
```

Full operational guide: [`docs/runbook-mem0-v0.1.8-deploy.md`](docs/runbook-mem0-v0.1.8-deploy.md).

### Business-outcome translation (estimates, pending pilot)

| Metric | Estimate | Source |
|---|---|---|
| Memory store size | 80-98% reduction | Stage 3 real-text 84.96%; Stage 5 real-Mem0 98.4% |
| Retrieval quality preserved | 80-82% F1 | Stage 5 F1 benchmarks (n=50 + n=200, both PASS) |
| Vector-store storage cost | ~50x cheaper at the same agent quality | derived from store-size reduction |
| Token-spend reduction | ~20% at typical RAG ratios | smaller context windows per query |
| Eng-hours saved | 16-32 hours per year per deployment | replaces ad-hoc cleanup scripts |
| Sweep cost | 0.067-0.245 s per call | sub-linear in store size; measured |

The numbers above are estimates derived from the measured benchmarks. The gap between estimate and verified outcome closes when a customer pilot reports their actual savings.

### Commercial position

This is the more-commercializable of the two opportunities today. The deployable bundle exists, the runbook exists, the regression gate runs on every PR, three downstreams are covered, and the headline numbers came out of THIS week's runs against real LLM extraction. The remaining gap is partnership, not engineering.

---

## How to apply the framework to your own opportunity

1. **Stage 1, 1-3 days.** Landscape scan. Find the incumbents. Kill any wedge that's already taken. Pick one with on-record evidence the incumbent will not build it.
2. **Stage 2, 1-2 weeks.** Build the simplest variant behind the variant interface. Run against a synthetic workload where you know the right answer. Iterate against the statistical gates. Write a finding doc per iteration.
3. **Stage 3, 3-5 days.** Add a real-data integration shim. Run the multi-model ladder. Do NOT publish the headline yet.
4. **Stage 4, 2-5 days.** Scale the real-data workload 5x to 10x. Use a more diverse entity set. Re-run. Either confirm or correct the Stage 3 headline.

Total: 4-6 weeks per opportunity. Output: go or no-go answer with cited data.

Reusable pieces: `runner/fdr.py`, `runner/cuped.py`, `runner/metrics/stats.py`, integration-shim ABC at `runner/dimensions/memory/lifecycle/integrations/base.py`, variant factory pattern at `runner/dimensions/memory/lifecycle/__init__.py`, finding-doc structure across `docs/finding-*.md` (30+ examples).

Full methodology and component inventory: [`FRAMEWORK.md`](FRAMEWORK.md).

## Honest gaps

What this repo does NOT have, in priority order:

1. **A customer pilot for either opportunity.** Until a real team runs a recommended bundle in production for 30 days and reports actual storage savings, latency change, and any incidents, the business-outcome claims are estimates. This is the gating constraint between "research asset" and "product."
2. **Real-calendar-time long-running data for Opportunity 2.** The 30/60/90-day projections come from a compressed-time simulator. Not the same as 8 weeks of real production traffic.
3. **More vertical corpora.** Twitter Financial News (entity-norm) and SQuAD (F1) are two corpora. Pharma, legal, customer-support corpora would each tighten one specific deployment recommendation.
4. **A non-English corpus.** Both opportunities should work on other languages; that has not been measured.
5. **Empirical depth across all six dimensions.** Memory, model, and recovery have strong evidence; prompt, tools, and policy are at Stage 2 baseline. The framework recognizes the gap; the cross-dim matrix uses what's available.

## Status

Active. **473 tests passing.** 30+ documented findings. 6 dimensions evaluated (3 strong, 3 at Stage 2 baseline). 3 memory-framework adapters (Mem0, Graphiti, Cognee) with cross-adapter consistency tests. CI regression gate on every PR.

## Install

```sh
pip install -e .
pip install -e .[dev]                # to run the test suite
pip install -e .[neural]             # entity-norm hybrid + multi-tenant variants
pip install -e .[ann]                # ANN scaling variant (hnswlib + numpy)
```

## Running the headline benchmarks

```sh
# Memory Lifecycle: real-Mem0 reduction smoke (~2 hours at N=2000)
.venv/bin/python experiments/mem0_smoke_test_real_llm.py --n-memories 2000 --sweep-every 100

# Memory Lifecycle: retrieval F1 preservation (~6 min at N=50, ~30 min at N=200)
.venv/bin/python experiments/mem0_retrieval_f1_benchmark.py --n-pairs 50 --aged-fraction 0.4

# Entity-norm: substantial-N case study (125 entities, 416 aliases, 836 tweets)
.venv/bin/python experiments/case_study_expanded.py --per-entity 1000

# Cross-dimension 72-config matrix (the recommendation source)
.venv/bin/python experiments/cross_dim_full_matrix.py
```

Outputs land in `runs/` as immutable JSON artifacts.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, then converts automatically to Apache 2.0.

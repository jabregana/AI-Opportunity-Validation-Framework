# AI-Opportunity-Validation-Framework

**A framework for deciding whether an AI opportunity should be built, scaled, or killed using staged evidence and deployment gates.**

Most AI teams operate as: idea -> prototype -> launch. By the time the prototype is in front of a customer, the team has already spent months on the wrong shape, the wrong claim, or the wrong wedge. The customer reaction is the first real test.

This framework inserts four tests **before** the customer sees anything:

```
idea -> kill test -> synthetic validation -> small-N real data -> substantial-N real data -> deployment recommendation
```

Each test catches errors the previous one missed. Most opportunities die at one of the earlier stages, which is the point. The ones that survive arrive at the customer pre-corrected, with a deployment recipe, measured technical numbers (store reduction, F1 preservation, p99 latency, false-collection rate), and a business-outcome translation built on top of those numbers. The translation stays an estimate until a customer reports their own outcomes from a production deployment; the technical numbers are real measurements from real runs with documented confidence intervals.

The framework is the durable asset. The individual opportunities tested through it are the case studies that show it works.

## Snapshot

- **Findings**: 30+ documented in `docs/finding-*.md`; three self-corrections in the last 7 days (entity-norm tail bias, Graphiti `in_degree==0` architectural assumption, Mem0 single-seed variance)
- **Methodology**: standard codified at [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md); self-validated on first application
- **Two opportunities through the framework**: entity-normalization proxy at Stage 4 (substantial-N evidence); agent-memory lifecycle management at Stage 5 for Mem0 (deployable bundle + runbook + multi-seed F1 on single SQuAD archetype, awaiting pilot), Stage 1 design for Graphiti/Cognee (code-complete v0.2.x variants; never benchmarked end-to-end pending customer signal)
- **The gap**: 0 customer pilots running a recommended bundle in production. This is the gating constraint between "research asset" and "product"

## The ambition

Run any AI/ML/LLM opportunity through this framework in four to six weeks and finish with one of two outcomes:

- **Go**: a specific deployment recipe (variant + config + sweep cadence + rollback signal), backed by measured numbers from real data with confidence intervals, and a business-outcome translation written down
- **No-go**: a documented kill, including which stage caught it and what the evidence was

The framework's defensibility comes from doing this **across every dimension of an agent system** (model, prompt, tools, memory, policy, recovery) with the same statistical discipline, and from **forcing deployment decisions** out of the joint result. Most agent-eval tooling stops at "here are the traces" or "here is one axis tested." This one continues to "and so the team should ship X, not Y."

What the framework does NOT do: invent new mechanisms. Entity normalization, graph GC, prompt benchmarking all exist. The novelty is the **same statistical discipline applied uniformly + forced deployment decisions emerging from the data**.

## The credibility-bearing pattern: the framework catches itself

In the most recent week of work, the framework caught itself surfacing real problems three times. Each catch is a finding doc in `docs/`, none was silently corrected, and each one demonstrates that the methodology is doing its job. This is what separates the framework from "we shipped a prototype and the demo worked":

| Self-correction | Surfaced by | Outcome |
|---|---|---|
| Entity-norm Stage 3 -> 4 ranking flip ("free local 3B beats every frontier API" was a small-N tail-bias artifact) | Stage 4 scale-up from N=227 to N=836 | Revised claim: "free local 7B ties gpt-4o at ~1000x lower cost." See [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md) |
| Graphiti `in_degree == 0` architectural assumption (every v0.1.x variant returns 0% reduction on edge-rich graphs) | Three Graphiti F1 scenarios (different backdates, different variants) all returning 0% | Documented; spawned v0.2.x graph-topology design. See [`docs/finding-graphiti-f1-stage5.md`](docs/finding-graphiti-f1-stage5.md) |
| Mem0 F1 single-seed headline understated 14pp variance ("81.6%" was one point in a [75%, 89%] distribution; 1-in-3 seeds fails the gate) | Multi-seed compliance from [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md) | Revised headline to "mean 84%, 95% CI [75%, 89%], 2-of-3 seeds pass." See [`docs/finding-mem0-f1-stage5.md`](docs/finding-mem0-f1-stage5.md) |

The methodology standard ([`docs/benchmark-methodology.md`](docs/benchmark-methodology.md)) was codified the same day as the third catch and immediately validated itself on first application. The framework's value comes from this kind of revisability, not from high single-numbers.

## What the framework consists of

| Layer | What it does | Where it lives |
|---|---|---|
| Four-stage progression | Forces theoretical -> synthetic -> small real -> substantial real, in that order | [`FRAMEWORK.md`](FRAMEWORK.md) |
| Benchmark methodology standard | Workload archetypes, multi-seed reporting, pre-registration, compliance checklist that gates VALIDATED vs PARTIAL | [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md) |
| Per-dim runner pattern + recipe | Each dimension gets its own runner (200-450 lines); 7-step recipe with worked example for adding a new one | [`docs/RUNNER-RECIPE.md`](docs/RUNNER-RECIPE.md) |
| UC gate machinery + standardized artifact schema | Per-experiment calibrated pass/fail thresholds on store reduction, retrieval recall, false-collection, latency, tombstone recovery, retrieval F1; all Stage-5 experiments emit a v1 top-level schema for cross-opportunity grep | `runner/gc_runner.py`, `runner/artifacts.py` |
| Statistical primitives | Paired bootstrap (10k resamples) for effect detection; LORD++ online FDR ledger (Ramdas et al. 2017) for sequential testing; CUPED (Deng et al. 2013) cuts required N by 20-40% when prior baselines exist | `runner/metrics/stats.py`, `runner/fdr.py`, `runner/cuped.py` |
| Cross-dimension matrix | Joint 72-config experiment across all six dimensions; surfaces interactions | `experiments/cross_dim_full_matrix.py` |
| Integration shim contract | One ABC adapts any downstream memory framework (Mem0, Graphiti, Cognee) into the gate-tested variant pipeline | `runner/dimensions/memory/lifecycle/integrations/base.py` |
| Finding-doc discipline | Every claim, including failures and retractions, gets a dated `docs/finding-*.md`. Artifacts are immutable | `docs/finding-*.md` (30+) |
| CI regression gate | Every PR re-runs the F1 benchmark, fails the build if any variant drops below 75% F1 preservation | `.github/workflows/ci.yml` |

## The two opportunities tested through it

Two real opportunities have run through all four stages. Both started from a 90-day landscape scan ([`docs/opportunity.md`](docs/opportunity.md)). Both produced revisable, deployable, measured outcomes.

### Opportunity 1: Schema-alignment proxy (entity normalization middleware)

Sits in front of Mem0, Graphiti, or Cognee. Intercepts entity writes, vector-matches against existing canonicals, substitutes the canonical before the LLM-extraction layer creates a duplicate node. Deterministic, no LLM in the hot path, ~30 ms p99.

### Opportunity 2: Agent Memory Lifecycle Management (graph GC)

Sits behind Mem0, Graphiti, or Cognee. Sweeps stale facts, preserves entities, tracks tombstones for over-collection recovery, supports per-tenant pinning. Eight deployment-shaped policy variants for flat-memory frameworks (Mem0); a seven-layer v0.2.x design exists for graph-native frameworks (Graphiti, Cognee) but is currently unbuilt. The Mem0 path has multi-seed F1 numbers on a single SQuAD archetype, awaiting pilot; the graph-native path is at Stage 1.

## Results: what each produced

### Opportunity 1: entity-normalization proxy (four stages complete)

| Stage | Output | What the framework caught |
|---|---|---|
| 1 | Wedge picked: Mem0 maintainer publicly rejected this approach on issue #4896 (April 2026) | Killed three other candidate wedges that incumbents had already shipped |
| 2 | v0.3.1 (hybrid + structural filter) became GA candidate after ranking flipped on real WikiData aliases | Synthetic-data winner v0.3.0 was beaten on real data; framework caught its own statistical bootstrap bug mid-pilot |
| 3 | At N=227: "free local 3B beats every frontier API" (p < 0.0001) | Headline was statistically significant but wrong (small-N tail bias) |
| 4 | At N=836 with 416-alias map: ranking collapsed; correct claim is "free local 7B ties gpt-4o at 0.773 with ~1000x lower cost" | Stage 4's 5-10x scale-up caught the tail bias before publication |

Full self-correction: [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md). This is one of the framework's three credibility-bearing self-corrections.

### Opportunity 2: memory lifecycle management

Two end-to-end results with real Mem0 (Ollama phi3:mini + all-minilm + Qdrant). Both Stage 5. Both use a single workload archetype (SQuAD); the methodology standard requires three for full compliance, so both ship marked PARTIAL pending archetype expansion.

| Workload | What it measures | Result | Compliance status |
|---|---|---|---|
| 2,000 SQuAD-style inputs, sweep every 100, 1 seed | Steady-state store reduction over a 2-hour run | Mem0 LLM extracted 3,363 memories; v0.1.8 collected 3,308. **98.4% reduction**, 0 failures, clean sawtooth (50-65 surviving, 200-320 pre-sweep) | PARTIAL: single-seed; multi-seed re-run is queued follow-up |
| 50 SQuAD Q&A pairs, F1 preservation before/after sweep, **3 seeds** | Retrieval quality preservation under GC | **Mean 83.8% F1 preservation, 95% CI [74.5%, 88.8%], at mean 36.4% reduction**. UC-GC-RETRIEVAL gate (>= 80%) passes in 2 of 3 seeds; fails in 1 of 3 (seed=42, 74.5%) | COMPLIANT (multi-seed); PARTIAL (single archetype) |

Three adapters exist (Mem0, Graphiti, Cognee) with 14 + 13 + cross-adapter consistency tests. The contract layer composes with v0.1.x policies identically across all three.

**Cross-framework finding**: end-to-end Graphiti benchmarks (3 scenarios; full detail in [`docs/finding-graphiti-f1-stage5.md`](docs/finding-graphiti-f1-stage5.md)) showed v0.1.x variants return 0% reduction on Graphiti's edge-rich graph because the `in_degree == 0` orphan-node check at the heart of every v0.1.x rule rarely triggers when entities are connected by edges. The Mem0 numbers above stand; the Graphiti and Cognee paths await a v0.2.x variant family designed for graph topology. The v0.2.x design (7 layers) is documented at [`docs/opportunity-v0.2.x-graph-topology-gc.md`](docs/opportunity-v0.2.x-graph-topology-gc.md).

### Cross-dimension result

A 72-config matrix joint experiment across all six dimensions found **75% of "obvious" variant combinations LOSE vs baseline**, and the top-10 all use baseline tools. The framework's current cross-dimension deployment recommendation: `prompt-v0.1.4-cot-plus-structured + b-allow-all-tools + recovery-v0.1.1-fallback-chain`, ~59.6% completion at CI [55.0-63.6], +23pp over baseline. Cost-weighted top-1 and top-2 are statistically indistinguishable, so the cheaper one wins. See [`docs/finding-cross-dim-cost-weighted.md`](docs/finding-cross-dim-cost-weighted.md).

## Where each opportunity stands on commercialization

| Opportunity | Stage | What's deployable today | What's missing for commercialization |
|---|---|---|---|
| Entity-norm proxy | 4 (substantial real data) | `embed-proxy-v0.5.7-mt-ann` (multi-tenant, ANN-backed) + drop-in middleware for Mem0/Graphiti/Cognee | Vertical alias maps as a paid subscription (pharma, finance, legal). Without those, the proxy itself is ~50 lines of regex anyone can rewrite |
| Memory lifecycle (Mem0 path) | 5 (real LLM + real adapter; multi-seed F1 on single SQuAD archetype; PARTIAL pending archetype expansion) | `gc-v0.1.8-comprehensive-tuned` + Mem0 adapter + production runbook + CI regression gate | One customer running the Mem0 bundle in production for 30 days |
| Memory lifecycle (Graphiti / Cognee path) | 1-2 (architectural design after v0.1.x assumption surfaced) | Adapters exist as real code; v0.1.x rules don't fit graph-native; v0.2.x code-complete but never benchmarked end-to-end | Build the v0.2.x family (5 layers in scope, 2 deferred to v0.3.x), per [`docs/opportunity-v0.2.x-graph-topology-gc.md`](docs/opportunity-v0.2.x-graph-topology-gc.md). Estimated 5-6 calendar weeks once customer signal arrives |

**Entity-normalization proxy**: plausibly a $1M to $10M ARR business, not a $1B startup. The proxy code is ~50 lines anyone can rewrite. The moat is curated vertical alias maps (pharma, finance, legal) sold as a subscription, plus integration-shim maintenance as upstream APIs evolve. The benchmark methodology and the harness itself are the brand asset, not the code.

**Memory lifecycle (Mem0 path)**: the more-commercializable of the two paths today. Deployable bundle, runbook, and CI regression gate exist; F1 numbers come from real LLM extraction at three seeds on a single SQuAD archetype. Remaining engineering gaps: additional workload archetypes for full methodology compliance, multi-seed CI on the n=2000 reduction smoke, archetype-specific variance characterization. Remaining commercial gap: one customer running the bundle in production for 30 days.

**Memory lifecycle (Graphiti / Cognee path)**: one v0.2.x build cycle away from a parallel commercializable offering when customer signal arrives. The seven-layer design ([`docs/opportunity-v0.2.x-graph-topology-gc.md`](docs/opportunity-v0.2.x-graph-topology-gc.md)) is documented and the variants are code-complete with passing unit tests; the end-to-end benchmark against real Graphiti has not been run. Estimated 5-6 calendar weeks once a Graphiti or Cognee prospect is on the table.

What does NOT get added next: more dimensions, more six-dimension variants, more statistical machinery. The framework has enough. What gets added next: **one customer who runs a recommendation in production and reports their actual business outcome.**

---

## Opportunity 1 deep dive: schema-alignment proxy

### The wedge

A 90-day study of agent memory tools (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) surfaced five shared problems: fragmented extraction, graph explosion, schema rigidity, cold extraction tax, no reasoning memory. Sitting in front of them as middleware is the cleanest opening.

Four candidate wedges considered:

| Wedge | Already taken? |
|---|---|
| LSP code memory graph | Yes. `Jakedismo/codegraph-rust` (786 stars) ships this exact pipeline |
| Reasoning memory in SQLite | Mostly. Neo4j Agent Memory shipped 8 PyPI releases in 83 days covering this |
| Real-time graph GC | Not yet, but the operational definition was fuzzy (became Opportunity 2 below) |
| Schema-alignment proxy | Not yet, and Mem0 maintainer rejected this approach on the record (issue #4896, April 2026) |

The schema-alignment proxy got the pick because the incumbent's public rejection is the cleanest signal a wedge will stay open. Full landscape: [`docs/opportunity.md`](docs/opportunity.md).

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

### What the proxy buys

| Where it helps | Where it does not |
|---|---|
| Financial news + trading alert routing | General conversational AI (the LLM does coreference on its own) |
| Drug name normalization in clinical NLP | Long-form text understanding |
| Per-tenant memory on Mem0 / Graphiti / Cognee | Open-ended entity discovery beyond surface-form variation |
| CRM auto-tagging | Workloads already running Senzing / Tilores |

## Opportunity 2 deep dive: Agent Memory Lifecycle Management

### The wedge

Same 90-day landscape scan. Real-time graph GC was the second wedge considered. The operational definition was fuzzy initially (when does "GC" fire? what does it preserve?), but the synthesis became `gc-v0.1.8-comprehensive-tuned`: fact collection + tombstone log + per-tenant pinning + tuned entity rule.

The architectural finding from end-to-end Graphiti testing (see "Cross-framework finding" above) refined the wedge: v0.1.x is the right family for **flat-memory frameworks** (Mem0); the v0.2.x design ([`docs/opportunity-v0.2.x-graph-topology-gc.md`](docs/opportunity-v0.2.x-graph-topology-gc.md)) is the right family for **graph-native frameworks** (Graphiti, Cognee). Both families share the same product story (Agent Memory Lifecycle Management) and the same configurable-policy approach.

### The mechanism (Mem0 path)

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

### Production recipe (Mem0 path)

```
Variant:          gc-v0.1.8-comprehensive-tuned
Sweep cadence:    every 4 hours for typical loads (workload-specific in runbook)
Knobs:
  min_age_seconds       86400   1 day grace before fact collection
  min_query_count       3       entities with 3+ queries always survive
  tombstone_ttl_seconds 604800  7 days "soft delete" window
Rollback:         stop calling mw.sweep(); middleware degrades to pass-through
Monitoring:       single sweep cycles can dip below the 80% F1 preservation
                  threshold; rollback if multiple consecutive cycles fall below
```

Full operational guide: [`docs/runbook-mem0-v0.1.8-deploy.md`](docs/runbook-mem0-v0.1.8-deploy.md).

### Business-outcome translation (estimates, pending pilot)

| Metric | Estimate | Source |
|---|---|---|
| Memory store size | 80-98% reduction | Stage 3 real-text 84.96%; Stage 5 real-Mem0 98.4% (single-seed) |
| Retrieval quality preserved | 75-89% F1 across seeds, mean 84% | Stage 5 multi-seed F1 (n=3 seeds); 1-in-3 seeds dips below 80% gate |
| Vector-store storage cost | ~50x cheaper at the same agent quality | derived from store-size reduction |
| Token-spend reduction | ~20% at typical RAG ratios | smaller context windows per query |
| Eng-hours saved | 16-32 hours per year per deployment | replaces ad-hoc cleanup scripts |
| Sweep cost | 0.067-0.245 s per call | sub-linear in store size; measured |

The numbers above are estimates derived from the measured benchmarks. Cost ranges reflect the variance the multi-seed methodology exposed. The gap between estimate and verified outcome closes when a customer pilot reports their actual savings.

---

## How to apply the framework to your own opportunity

1. **Stage 1, 1-3 days.** Landscape scan. Find the incumbents. Kill any wedge that's already taken. Pick one with on-record evidence the incumbent will not build it. See [`docs/opportunity-v0.2.x-graph-topology-gc.md`](docs/opportunity-v0.2.x-graph-topology-gc.md) for an example Stage 1 doc.
2. **Stage 2, 1-2 weeks.** Build the simplest variant behind the variant interface. Run against a synthetic workload where you know the right answer. Iterate against the statistical gates. Write a finding doc per iteration.
3. **Stage 3, 3-5 days.** Add a real-data integration shim. Run the multi-model ladder. Do NOT publish the headline yet.
4. **Stage 4, 2-5 days.** Scale the real-data workload 5x to 10x. Use a more diverse entity set. Re-run. Either confirm or correct the Stage 3 headline.

Total: 4-6 weeks per opportunity. Output: go or no-go answer with cited data and confidence intervals.

The per-dimension runner pattern + seven-step recipe with a worked example: [`docs/RUNNER-RECIPE.md`](docs/RUNNER-RECIPE.md). The benchmark methodology standard that every Stage 3+ run must comply with: [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md).

Reusable pieces: `runner/fdr.py`, `runner/cuped.py`, `runner/metrics/stats.py`, integration-shim ABC at `runner/dimensions/memory/lifecycle/integrations/base.py`, variant factory pattern at `runner/dimensions/memory/lifecycle/__init__.py`, standardized artifact helper at `runner/artifacts.py::emit_dimension_artifact`, finding-doc structure across `docs/finding-*.md` (30+ examples).

Full methodology and component inventory: [`FRAMEWORK.md`](FRAMEWORK.md).

## Honest gaps

What this repo does NOT have, in priority order:

1. **A customer pilot for either opportunity.** Until a real team runs a recommended bundle in production for 30 days and reports actual storage savings, latency change, and any incidents, the business-outcome claims are estimates. This is the gating constraint between "research asset" and "product."
2. **v0.2.x variants built for graph-native frameworks.** The design is documented (seven layers, configurable per domain/model/setup) but no code exists yet. Mem0 has the production-shape bundle today; Graphiti and Cognee customers wait until v0.2.x ships.
3. **Multi-seed CI on the n=2000 reduction smoke.** The 98.4% reduction headline is still single-seed (PARTIAL per [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md)). Wide-CI re-run is a queued follow-up, ~4 hours of Ollama time.
4. **More workload archetypes.** The methodology standard requires at least 3 archetypes per Stage 3+ run. Current Mem0 + Graphiti runs use one (SQuAD-shape). The archetype library (steady-state, bursty, large-fact, high-mutation, cluster-rich, adversarial) needs concrete fixture builds.
5. **Real-calendar-time long-running data.** The 30/60/90-day projections come from a compressed-time simulator. Not the same as 8 weeks of real production traffic.
6. **More vertical corpora.** Twitter Financial News (entity-norm) and SQuAD (F1) are two corpora. Pharma, legal, customer-support corpora would each tighten one specific deployment recommendation.
7. **A non-English corpus.** Both opportunities should work on other languages; that has not been measured.
8. **Empirical depth across all six dimensions.** Memory, model, and recovery have strong evidence; prompt, tools, and policy are at Stage 2 baseline. The framework recognizes the gap; the cross-dim matrix uses what's available.

## Status

Active. **30+ documented findings.** Three self-corrections this week alone (entity-norm Stage 3 -> 4, Graphiti `in_degree == 0` architectural assumption, Mem0 F1 single-seed variance). 6 dimensions evaluated (3 strong, 3 at Stage 2 baseline). 3 memory-framework adapters (Mem0, Graphiti, Cognee) with cross-adapter consistency tests. CI regression gate on every PR. Methodology standard codified ([`docs/benchmark-methodology.md`](docs/benchmark-methodology.md)) and immediately validated on first application.

## Install

```sh
pip install -e .
pip install -e .[dev]                # to run the test suite
pip install -e .[neural]             # entity-norm hybrid + multi-tenant variants
pip install -e .[ann]                # ANN scaling variant (hnswlib + numpy)
```

## Running the headline benchmarks

```sh
# Memory Lifecycle: real-Mem0 reduction smoke (~2 hours at N=2000, single-seed)
.venv/bin/python experiments/mem0_smoke_test_real_llm.py --n-memories 2000 --sweep-every 100

# Memory Lifecycle: retrieval F1 preservation (~30 min per seed at N=50; methodology requires 3+ seeds)
for seed in 42 123 456; do
    .venv/bin/python experiments/mem0_retrieval_f1_benchmark.py \
        --n-pairs 50 --aged-fraction 0.4 --seed $seed \
        --qdrant-path /tmp/qdrant_seed_$seed --history-db /tmp/mem0_seed_$seed.db \
        --out runs/mem0_retrieval_f1/seed_$seed.json
done

# Entity-norm: substantial-N case study (125 entities, 416 aliases, 836 tweets)
.venv/bin/python experiments/case_study_expanded.py --per-entity 1000

# Cross-dimension 72-config matrix (the recommendation source)
.venv/bin/python experiments/cross_dim_full_matrix.py
```

Outputs land in `runs/` as immutable JSON artifacts conforming to the standardized v1 schema (`opportunity, dimension, stage, variants, metrics, gates, decision, environment`).

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, then converts automatically to Apache 2.0.

# AI Wedge Harness

**The same statistical discipline applied across every dimension of an agent system, with real deployment decisions forced from the results.**

That sentence is the novel part. Most AI evaluation tools either record traces (LangSmith, Langfuse, Phoenix) or test one axis (Inspect AI, Pydantic Evals). This repo runs paired-bootstrap CIs, LORD++ online FDR, and calibrated UC gates across model, prompt, tools, memory, policy, and recovery, then converts the joint result into a specific recommendation a team can deploy this week.

## Who this is for

You run an agent system in production. Memory grows unboundedly. Retrieval is getting noisy. The team picks between Mem0, Graphiti, or Cognee but cannot defend the choice with numbers. Cost is creeping up. Your engineering org wants a measured, reproducible answer, not a vendor pitch.

Concretely, this is for:
- A staff or principal engineer on an AI platform team
- A CTO or eng lead at a series-A to series-C agent startup
- An innovation team in a larger company piloting an agent

If you only need traces or per-axis tests, the tools above are simpler. If you need to defend "we will ship X and not Y" to a skeptical audience, this is what that looks like.

## What this has produced so far

Two case studies have run all four stages, and the second is now backed by a real deployable bundle with measured numbers from this week's runs.

### Case study 1: Agent Memory Lifecycle Management (the production-ready bundle)

I built the `Mem0GCMiddleware` + `gc-v0.1.8-comprehensive-tuned` stack and benchmarked it against real Mem0 (Ollama phi3:mini + all-minilm + Qdrant) on two workloads:

| Workload | What it measures | Result |
|---|---|---|
| 2,000 SQuAD-style inputs, sweep every 100 adds | **Steady-state store reduction** | Mem0 LLM extracted 3,363 memories; v0.1.8 collected 3,308 -> **98.4% reduction**, 0 failures over 2-hour run |
| 50-pair + 200-pair SQuAD F1 benchmark | **Retrieval-quality preservation** | **81.6% F1 preservation at 52% reduction (n=50); 81.8% at 44% reduction (n=200).** Both PASS the >= 80% UC-GC-RETRIEVAL gate. Replicated across two sample sizes; 0.2pp delta is within bootstrap noise. |

**The deployable bundle is real.** Eleven lines of code drop the middleware in front of an existing Mem0 v2 instance. The runbook ([`docs/runbook-mem0-v0.1.8-deploy.md`](docs/runbook-mem0-v0.1.8-deploy.md)) covers prereqs, sweep cadence by workload, rollback signals tied to UC gates, and a first-week operational rhythm.

**Business outcome translation** (estimates pending a customer pilot):
- **Storage**: 98% smaller memory store = 50x cheaper vector-store bill at the same agent quality
- **Retrieval cost**: smaller context window assembled per query = ~20% token-spend reduction at typical RAG ratios
- **Eng time saved**: replaces ad-hoc cleanup scripts at ~16-32 eng-hours/year per deployment

What's missing from the business case: **a customer who runs this in production for 30 days and reports their actual savings.** That's the next gap (see "Honest gaps" below).

### Case study 2: Entity-normalization proxy (the self-correction)

The first opportunity I ran through the framework. The Stage 3 headline at N=227 was "free local 3B model beats every frontier API at entity normalization (p < 0.0001)." It was wrong at scale.

Stage 4 expanded the alias map to 416 aliases over 125 entities and pulled 836 real tweets. Smaller models dropped 9-11 pp; frontier models dropped 5-6. The correct claim collapsed to "free local 7B ties gpt-4o at 0.773 with ~1000x lower cost," and the original ranking flipped.

The framework catching its own overclaim before it shipped to a customer is the single most credibility-bearing thing this project produced. Full self-correction: [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md).

### Cross-dimension result that changed a recommendation

A 72-config matrix across all six agent dimensions showed **75% of "obvious" variant combinations LOSE vs baseline.** Top-10 by completion all use baseline tools (the fancier tools variants underperformed under joint testing). The framework's current deployment recommendation: `prompt-v0.1.4-cot-plus-structured + b-allow-all-tools + recovery-v0.1.1-fallback-chain`, ~59.6% completion at CI [55.0-63.6], +23pp over baseline. Top-1 and top-2 by completion are statistically indistinguishable, so the cheaper one wins. See [`docs/finding-cross-dim-cost-weighted.md`](docs/finding-cross-dim-cost-weighted.md).

## How to deploy the recommendations today

### Bundle A: Memory Lifecycle Management (Mem0 + gc-v0.1.8)

```python
from mem0 import Memory
from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import Mem0GCMiddleware

memory = Memory.from_config(your_config)
variant = build("gc-v0.1.8-comprehensive-tuned")
mw = Mem0GCMiddleware(memory)

# Anywhere you called memory.add(...), call mw.add(...) instead
mw.add("User likes oat milk", user_id="alice")
results = mw.search("dietary preferences", user_id="alice")

# Schedule a periodic sweep (every 4 hours is a safe default)
mw.sweep(variant, current_time=time.time())
```

Configure `min_age_seconds`, `min_query_count`, tombstone TTL per the runbook. The middleware degrades to pass-through if you stop calling `sweep()`, so rollback is one line.

### Bundles B-D

Same shape for [Graphiti](docs/runbook-mem0-v0.1.8-deploy.md#bundles-b-d) (graph-native, async) and [Cognee](docs/runbook-mem0-v0.1.8-deploy.md#bundles-b-d) (module-level API). All three pass identical contract tests (`tests/test_cross_adapter_consistency.py`).

### Cross-dimension recommendation

Wire `prompt-v0.1.4-cot-plus-structured` into your prompt path, leave tools at baseline, layer `recovery-v0.1.1-fallback-chain` for error handling. The full deployment spec: [`docs/finding-cross-dim-cost-weighted.md`](docs/finding-cross-dim-cost-weighted.md).

## What's NOT here (deliberately)

The analyst feedback that produced this README rewrite called out that the framework was running ahead of its empirical depth. The response is to stop adding things, not add more.

- **No new dimensions.** Six are already enough.
- **No new variants.** The current 10 GC variants + 4 entity-norm variants + the prompt/tools/policy/recovery variants are enough.
- **No new statistical machinery.** Paired bootstrap, LORD++, CUPED, UC gates do the work.

What does get added: **proof that the framework's recommendations get followed by real teams and produce measurable business outcomes.** Currently zero customer pilots. That is the gating constraint, not engineering capacity.

## How the framework arrives at recommendations

Compressed (full version in [`FRAMEWORK.md`](FRAMEWORK.md)):

```
Stage 1 (theoretical)  ->  Stage 2 (synthetic)  ->  Stage 3 (real, small N)  ->  Stage 4 (real, substantial N)
landscape scan +           variant iteration       integration shim +           5-10x scale-up
wedge selection            against UC gates        multi-model ladder           confirms or corrects Stage 3
```

Each stage catches errors the previous one missed. The Stage 3-to-Stage 4 catch on the entity-normalization headline is the canonical example.

Statistical machinery used at each stage:

| Layer | Purpose | Implementation |
|---|---|---|
| Per-sweep gates | "Did this variant cross a red line?" | `runner/gc_runner.py:compute_uc_gates` + `compute_retrieval_gate` (6 gates total) |
| Per-variant effect detection | "Is the effect real or noise?" | `runner/metrics/stats.py:paired_bootstrap` (10k resamples, percentile CI) |
| Cross-variant FDR control | "Across N variants tested over time, are my p-values honest?" | `runner/fdr.py` (LORD++, Ramdas et al. 2017) |
| Variance reduction | "Do I need N=300 or N=500 to detect this effect?" | `runner/cuped.py` (CUPED, Deng et al. 2013) |

## How to apply the framework to your own opportunity

1. **Stage 1** (1-3 days): landscape scan, wedge pick, kill anything already taken
2. **Stage 2** (1-2 weeks): variant iteration on synthetic workloads against UC gates
3. **Stage 3** (3-5 days): real-data integration shim + multi-model ladder
4. **Stage 4** (2-5 days): 5-10x scale-up; confirm or correct Stage 3

Total: 4-6 weeks per opportunity. Output: go or no-go answer with cited data.

The reusable pieces: `runner/fdr.py`, `runner/cuped.py`, `runner/metrics/stats.py`, the integration-shim ABC (`runner/dimensions/memory/lifecycle/integrations/base.py`), the variant factory pattern (`runner/dimensions/memory/lifecycle/__init__.py`), and the finding-doc structure (`docs/finding-*.md`, 30+ examples).

## Honest gaps

What this repo does NOT have, in priority order:

1. **A customer pilot.** Until a real team runs the recommended bundle in production for 30 days and reports their actual storage savings, latency change, and any incidents, the business-outcome claims are estimates. This is the gating constraint between "research asset" and "product."
2. **Real-calendar-time long-running data.** The 30/60/90-day projections come from a compressed-time simulator (`experiments/gc_long_running_simulation.py`). They are not the same as 8 weeks of real production traffic.
3. **More vertical corpora.** Twitter Financial News (entity-norm) and SQuAD (F1) are two corpora. A pharma alias map, a legal corpus, or a customer-support corpus would each tighten one of the deployment recommendations.
4. **A second-language test.** All current corpora are English. The proxy and the GC framework should both work on other languages; that has not been measured.

## Status

Active. **473 tests passing.** 30+ documented findings. 6 dimensions evaluated, 3 with strong evidence (model, memory, recovery). 3 memory-framework adapters (Mem0, Graphiti, Cognee) with cross-adapter consistency tests. CI on every PR runs the F1 regression gate (`.github/workflows/ci.yml`).

The framework is the durable asset. The Memory Lifecycle Management bundle is the most production-ready deployable. The proxy is the first case study tested through it. The next deliverable is one customer pilot, not more engineering.

## Install

```sh
pip install -e .
pip install -e .[dev]                # to run the test suite
pip install -e .[neural]             # entity-norm hybrid + multi-tenant variants
pip install -e .[ann]                # ANN scaling variant (hnswlib + numpy)
```

## Running the headline benchmarks

```sh
# Memory Lifecycle: Mem0 + gc-v0.1.8 reduction smoke (~2 hours at N=2000)
.venv/bin/python experiments/mem0_smoke_test_real_llm.py --n-memories 2000 --sweep-every 100

# Memory Lifecycle: retrieval F1 preservation (~6 min at N=50, ~30 min at N=200)
.venv/bin/python experiments/mem0_retrieval_f1_benchmark.py --n-pairs 50 --aged-fraction 0.4

# Entity-norm: the substantial-N case study (125 entities, 416 aliases, 836 tweets)
.venv/bin/python experiments/case_study_expanded.py --per-entity 1000

# Cross-dimension 72-config matrix (the recommendation source)
.venv/bin/python experiments/cross_dim_full_matrix.py
```

Outputs land in `runs/` as immutable JSON artifacts. The CI regression gate runs the F1 benchmark on every PR and fails the build if any variant drops below 75% F1 preservation.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, then converts automatically to Apache 2.0.

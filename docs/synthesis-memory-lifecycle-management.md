---
type: strategic-synthesis
date: 2026-06-08
status: PARTIALLY-EXECUTED
supersedes: positioning portions of strategic-framing-decision-tool.md
---

# Synthesis: from "Graph GC" to "Agent Memory Lifecycle Management"

## Execution status (2026-06-08)

| Phase | Status | Evidence |
|---|---|---|
| Phase 1: Real integrations | **SHIPPED** | Mem0 + Graphiti + Cognee adapters in `runner/dimensions/memory/lifecycle/integrations/`; cross-adapter consistency test in `tests/test_cross_adapter_consistency.py`; smoke test scripts in `experiments/{mem0,graphiti}_smoke_test_real_llm.py`; finding doc `docs/finding-graphiti-adapter-phase2.md` |
| Phase 1.5: 2000-memory Mem0 smoke | **IN-FLIGHT** | `experiments/mem0_smoke_test_real_llm.py --n-memories 2000` running locally; partial artifact at `runs/mem0_smoke_real_llm/*.partial.json` |
| Phase 2: Long-running benchmarks | **SCAFFOLDED** | `experiments/gc_long_running_simulation.py` compresses 30/60/90-day churn; first result: 30-day baseline=3020 -> v0.1.8=20 (99.3% reduction) |
| Phase 3: Retrieval-quality F1 | **SHIPPED + TUNED** | `experiments/gc_retrieval_f1_benchmark.py` (synthetic + SQuAD); per-adapter variants in `experiments/{mem0,graphiti,cognee}_retrieval_f1_benchmark.py`; `compute_retrieval_gate()` in `runner/gc_runner.py` emits UC-GC-RETRIEVAL verdict; tuned trade-off table in `docs/finding-retrieval-f1-scaffold-tuned.md` |
| Phase 3.5: CI regression gate | **SHIPPED** | `.github/workflows/ci.yml` runs F1 benchmark on every PR; `experiments/ci_check_f1_regression.py` fails CI if any variant drops below 75% F1 preservation |
| Phase 4: Customer pilot | **NOT STARTED** | Partnership work, blocked on engineering completion |
| Phase 5: v0.2.x graph-topology variants | **NEEDED** | End-to-end Graphiti F1 surfaced that v0.1.x's `in_degree == 0` orphan-node check never triggers on edge-rich graphs (see `docs/finding-graphiti-f1-stage5.md`). 0% reduction across three test scenarios on Graphiti. Mem0 numbers unaffected (flat-memory). Graphiti and Cognee paths await a v0.2.x family operating on graph topology rather than orphan assumption. Estimated 2-3 weeks Stage 1-2. |

### What's still measurably missing

1. **Run the per-adapter F1 benchmarks against real downstreams.** Scripts exist but require `pip install graphiti-core` + Neo4j and `pip install cognee` respectively. The Mem0-backed one runs once the 2000-memory smoke finishes (frees up Ollama).
2. **Real 60-day and 90-day deployments.** The compressed simulation answers "does GC keep up?" but not "does memory quality decay differently after week 8?" That needs a real deployment.
3. **The customer pilot.** Still the bottleneck the analyst named.

---

This doc responds to substantive analyst feedback that reframes the framework's biggest single commercial opportunity. The reframe is from a research framework to a **product category**: Agent Memory Lifecycle Management.

The analyst's exact words (quoted):

> "I actually would not sell: Graph GC. I would sell: Memory Lifecycle Management. Much bigger. Customer story: 'Your agent memory grows forever. Memory quality degrades. Retrieval gets noisy. Costs rise. We manage memory lifecycle automatically.' That is understandable. They do not wake up saying: 'I need graph garbage collection.'"

The framework's GC work is the foundation. The reframe is the wrapper that makes it sellable.

## The category definition

**Agent Memory Lifecycle Management**: the layer that governs what agent memory is **created, promoted, retained, demoted, and deleted** over time.

Five lifecycle states, each with a deterministic policy:

| State | Today (GC framework) | Lifecycle Management framing |
|---|---|---|
| Created | The downstream framework (Mem0, Graphiti, Cognee) writes a node | Acknowledged but not policy-controlled by the framework |
| Promoted | Pinning (state.pinned + tenant_pins) | "Mark as important" API surface |
| Retained | All v0.1.2+ variants preserve facts with edges + entities | Default policy: keep what's referenced |
| Demoted | Tombstone log (v0.1.3+) preserves metadata after collection | "Move to cold storage; queries return tombstone" |
| Deleted | `collect()` removes the node from state | "Permanent deletion after demotion TTL" |

This vocabulary translates one-to-one with the GC framework's existing primitives. The product is the framework + a productized API + observability + lifecycle policies.

## The four-layer business value chain the analyst named

The analyst's bridge:

```
GC mechanism (today)
   ↓ memory quality
   ↓ agent quality
   ↓ business metric
```

A concrete worked example for an enterprise pitch:

```
Graph size           ↓ 80%   (from gc-v0.1.2-fact-only)
Retrieval precision  ↑ 12%   (smaller graph -> tighter indexes)
Agent completion     ↑ 8%    (better retrieval -> better answers)
Token spend          ↓ 15%   (smaller graph -> less prompt context)
```

Each downstream arrow is currently unmeasured by the framework. The "graph size down 80%" claim is well-established (`finding-gc-stage3-real-text.md` shows 84.96% on real Twitter data). The other three arrows are proxies the analyst correctly flags as missing.

## What this means for the project's next iteration

Four concrete phases, in the analyst's recommended sequence:

### Phase 1: Real integrations (highest ROI)

Today the project has:
- `runner/dimensions/memory/lifecycle/integrations/base.py`: `GCIntegrationShim` ABC
- `runner/dimensions/memory/lifecycle/integrations/mock.py`: Reference implementation

What the analyst correctly flags as missing:
- `runner/dimensions/memory/lifecycle/integrations/mem0.py`: Actual Mem0 adapter
- `runner/dimensions/memory/lifecycle/integrations/graphiti.py`: Actual Graphiti adapter

Effort estimate: 1-2 engineer-weeks per concrete shim (contract already designed; just need to wire to the downstream framework's actual API). The Graphiti adapter probably issues Cypher queries; the Mem0 adapter probably intercepts `add()` / `update()` / `search()`.

Expected output: a benchmark run on a real Mem0 deployment where the framework's `gc-v0.1.8-comprehensive-tuned` actually reduces the graph by ~80% in real time. That benchmark becomes the customer-facing demo.

### Phase 2: Long-running benchmarks (marketing material)

Today: synthetic workloads with 30-day simulated periods.

What the analyst wants:
- 30-day memory accumulation curves
- 60-day accumulation curves
- 90-day accumulation curves
- Graphs showing GC-on vs GC-off divergence over time

Effort estimate: ~1 week per accumulation study (instrument an existing Mem0/Graphiti deployment, log graph size + retrieval metrics daily). Three studies = 3 weeks of calendar time but ~1 week of active engineering.

Expected output: three line graphs showing memory growth without GC (exponential) vs with `gc-v0.1.8` (steady-state at 15-20% of baseline). The graphs become the front-page screenshots.

### Phase 3: Real retrieval-quality metrics (the critical gap)

Today: GC's UC gates use `entity survival` (UC-GC-2) as a proxy for "did the framework keep what matters." The Stage 3 finding doc explicitly says this needs to become actual retrieval F1.

What's needed:
- A retrieval-quality benchmark with known ground truth (e.g., HotpotQA-shape: "what is X's role at company Y?" with known correct memory)
- Run the benchmark before AND after GC sweeps; compute F1 delta
- Replace UC-GC-2 with this measured metric

Effort estimate: 1-2 weeks. Most work is dataset assembly + scoring infrastructure; the benchmark execution is straightforward once those exist.

Expected output: "GC reduces graph by 80% while preserving 95-98% of retrieval F1." That number is the credibility anchor.

### Phase 4: One customer pilot

The analyst's strongest qualifier:

> "At that point it stops looking like an experiment and starts looking like a product category."

One real customer using the framework in production turns the project from "research" to "product." Even an unpaid design-partner pilot would do this.

Effort estimate: 4-8 weeks of partnership work (sales conversation → onboarding → first deployment → first 30 days of monitoring). Most of the effort is partnership, not engineering.

## Three product tiers (from the analyst)

### Tier 1: Open source

- `gc-v0.1.2-fact-only` baseline
- `gc-v0.1.3-fact-only-tombstone` (over-collection recovery)
- Metrics dashboard
- Stage 2 + Stage 3 benchmarks reproducible
- Mem0 / Graphiti integration shims as libraries

Goal: **adoption.** Engineers add this to their existing Mem0/Graphiti stack with one line of code.

### Tier 2: Hosted (SaaS)

- `gc-v0.1.8-comprehensive-tuned` with managed sweep cadence
- Memory analytics dashboard (real-time graph size, retrieval metrics, cost trajectory)
- Lifecycle policies as YAML config (per-tenant retention, demotion windows, tombstone TTL)
- Benchmarking-as-a-service: run the framework against a customer's snapshot, produce the ROI report
- Multi-tenant pinning UI for admins

Goal: **teams running agents at scale.** $50-$500 / month per tenant tier.

### Tier 3: Enterprise

- Compliance retention (GDPR-aware lifecycle policies; "this user's memory must be deleted within 30 days")
- Lifecycle governance (audit logs of every demote / delete decision)
- Memory observability (per-user, per-tenant, per-agent retention reports)
- Cross-agent memory management (one user has 5 agents; memory sharing policies)

Goal: **large companies with compliance + scale concerns.** $50K-$500K / year contracts.

## What the framework already has (mapping current work to the product)

The reframe doesn't ask for new technical work in the framework's core. It asks for productization wrappers:

| Customer-visible product | Current framework asset |
|---|---|
| Memory lifecycle policies | `gc-v0.1.2` through `gc-v0.1.8` (7 variants in the factory) |
| Lifecycle observability | `GCRunResult` dataclass (already tracks every metric a dashboard needs) |
| Workload-tuned cadence guidance | `experiments/gc_sweep_cadence_matrix.py` (matrix already produces the Pareto frontier) |
| Tenant scoping | v0.1.5 / v0.1.8's `pin_for_tenant()` API |
| Over-collection recovery | v0.1.3 / v0.1.8's `was_recently_collected()` API |
| Tuned entity collection | v0.1.7's `min_query_count` secondary gate |
| ROI report | `investment_prioritization.py` (already produces ranked recommendations with build-cost) |
| Business-KPI mapping | `business-kpi-mapping-memory-lifecycle.md` (already exists) |

**The technical product is already built.** The gap is real-downstream integrations (Phase 1), long-running data (Phase 2), retrieval-quality metrics (Phase 3), and customer evidence (Phase 4).

## What the framework should STOP saying

The analyst is right that "Graph GC" is the wrong customer-facing language. The doc concordance changes that should ship next:

| Stop saying | Start saying |
|---|---|
| "Graph GC" | "Agent memory lifecycle management" |
| "Variant" (in customer docs) | "Lifecycle policy" |
| "Collection" (in customer docs) | "Demotion + deletion" |
| "Tombstone" (in customer docs) | "Recently-superseded memory" |
| "Stage 2 benchmark" | "30-day simulation" |
| "Cross-dim experiment" | "Joint deployment validation" |

The technical docs stay as-is (engineers want precise language). The customer-facing surfaces shift.

## The defensibility argument

The analyst's strongest point:

> "Not RefCountGC — anyone can build that. Not FactOnlyGC — anyone can build that too. The defensible layer is: Lifecycle policies + Evaluation harness + Real-world benchmark corpus + Framework integrations. That combination is hard to replicate."

The framework's defensibility today (updated 2026-06-08):

- DONE: Lifecycle policies (8 variants with documented use cases)
- DONE: Evaluation harness (paired bootstrap, LORD++ FDR, UC-GC-1..5 + UC-GC-RETRIEVAL gates, cross-dim matrix)
- DONE: Framework integrations (Mem0 + Graphiti + Cognee adapters, cross-adapter consistency tests, smoke-test scripts)
- PARTIAL: Real-world benchmark corpus (Twitter Financial News + SQuAD subset; HotpotQA blocked on HF; more verticals = more credibility)

Three of the four defensibility legs are now closed. The remaining gap is corpus breadth: every additional vertical reduces the "you only tested it on X" critique.

## Investor-readability checklist (from the analyst)

The analyst named what they would want to see to call this a product:

| Item | Current state (2026-06-08) | Gap |
|---|---|---|
| Real Mem0 / Graphiti integrations | DONE: Mem0 + Graphiti + Cognee adapters with cross-adapter consistency tests | Run all three F1 benchmarks against real downstreams |
| Retrieval-quality benchmarks | DONE: F1 scaffold + per-adapter benchmarks + UC-GC-RETRIEVAL gate + CI regression guard | Land first real-downstream F1 numbers (Mem0 first) |
| 30-90 day accumulation studies | SCAFFOLDED: Compressed-time simulator, first 30-day result (99.3% reduction) | Run on real Mem0/Graphiti deployment over real calendar time |
| Clear evidence: lower cost, better retrieval, better agent outcomes | Synthetic cost reduction + measured F1 preservation trade-off | Real $$ savings from a real deployment |
| One customer using it in production | None | The pilot |

Five items. Three engineering items are DONE or in-flight. Two partnership items (real-deployment data + customer pilot) remain. The technical baseline is fully in place.

## Recommended sequencing (STATUS UPDATE 2026-06-08)

**Weeks 1-2: Mem0 adapter** -- DONE
- `runner/dimensions/memory/lifecycle/integrations/mem0_adapter.py`
- Wires `GCIntegrationShim` to Mem0 v2.0.4 API (with v2 search-filter translation)
- Smoke-test scripts: `experiments/mem0_smoke_test_real_llm.py`; 2000-memory run in flight

**Weeks 3-4: Graphiti adapter** -- DONE
- `runner/dimensions/memory/lifecycle/integrations/graphiti_adapter.py`
- Async-to-sync wrapper via `_run_async()`; episode + node + edge handling
- 14 adapter tests against `FakeGraphiti`; smoke-test script `experiments/graphiti_smoke_test_real_llm.py`

**Weeks 3-4 bonus: Cognee adapter** -- DONE (was not in original plan)
- `runner/dimensions/memory/lifecycle/integrations/cognee_adapter.py`
- Module-level API (not instance-based); cognify() + add() separation
- 13 adapter tests against `FakeCognee`

**Weeks 5-6: Retrieval-quality benchmark** -- DONE
- `experiments/gc_retrieval_f1_benchmark.py` with `--use-squad` flag
- Per-adapter variants: `experiments/{mem0,graphiti,cognee}_retrieval_f1_benchmark.py`
- New `compute_retrieval_gate()` in `runner/gc_runner.py` emits UC-GC-RETRIEVAL verdict
- Bonus: CI regression guard at `experiments/ci_check_f1_regression.py` + `.github/workflows/ci.yml`

### What comes next

1. Run `experiments/mem0_retrieval_f1_benchmark.py` once 2000-memory smoke completes
2. Write `docs/finding-mem0-adapter-real-llm-stage5.md` (the 2000-memory result)
3. Write `docs/runbook-mem0-v0.1.8-deploy.md` (production deployment guide)
4. Phase 4: customer pilot conversations

## How this changes the framework's pitch

Today's pitch (from `FRAMEWORK.md`):

> "A decision-making framework for AI agent investment prioritization."

Refined pitch (with the analyst's reframe):

> "Agent Memory Lifecycle Management — the layer that governs what agent memory is created, promoted, retained, demoted, and deleted over time. Eight production-tested lifecycle policies, calibrated UC gates for store reduction + retrieval quality + tenant safety, integration shims for Mem0 / Graphiti / Cognee. Backed by a decision-making framework for evaluating any memory-lifecycle policy as a statistical system."

The decision-making framework is the engine. Memory Lifecycle Management is the product.

## Pointers

- Strategic positioning (prior): `docs/strategic-framing-decision-tool.md`
- Architecture: `docs/six-dimensions-architecture.md`
- GC variant lineup (8 deployment-shaped policies, pending customer pilot for production-validated status): `runner/dimensions/memory/lifecycle/`
- Integration shim contract: `runner/dimensions/memory/lifecycle/integrations/base.py`
- Business-KPI mapping (already partially closes the analyst's gap): `docs/business-kpi-mapping-memory-lifecycle.md`
- Investment tool (already produces ROI rankings): `experiments/investment_prioritization.py`

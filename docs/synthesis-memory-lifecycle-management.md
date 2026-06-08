---
type: strategic-synthesis
date: 2026-06-08
status: PROPOSAL
supersedes: positioning portions of strategic-framing-decision-tool.md
---

# Synthesis: from "Graph GC" to "Agent Memory Lifecycle Management"

This doc responds to substantive analyst feedback that reframes the framework's biggest single commercial opportunity. The reframe is from a research framework to a **product category**: Agent Memory Lifecycle Management.

The analyst's exact words (quoted):

> "I actually would not sell: Graph GC. I would sell: Memory Lifecycle Management. Much bigger. Customer story: 'Your agent memory grows forever. Memory quality degrades. Retrieval gets noisy. Costs rise. We manage memory lifecycle automatically.' That is understandable. They do not wake up saying: 'I need graph garbage collection.'"

The framework's GC work is the foundation. The reframe is the wrapper that makes it sellable.

## The category definition

**Agent Memory Lifecycle Management**: the layer that governs what agent memory is **created, promoted, retained, demoted, and deleted** over time.

Five lifecycle states, each with a deterministic policy:

| State | Today (GC framework) | Lifecycle Management framing |
|---|---|---|
| Created | The downstream framework (Mem0, Graphiti, Cognee) writes a node | Acknowledged but not policy-controlled by us |
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
- `runner/dimensions/memory/lifecycle/integrations/base.py` — `GCIntegrationShim` ABC
- `runner/dimensions/memory/lifecycle/integrations/mock.py` — Reference implementation

What the analyst correctly flags as missing:
- `runner/dimensions/memory/lifecycle/integrations/mem0.py` — Actual Mem0 adapter
- `runner/dimensions/memory/lifecycle/integrations/graphiti.py` — Actual Graphiti adapter

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

Today: GC's UC gates use `entity survival` (UC-GC-2) as a proxy for "did we keep what matters." The Stage 3 finding doc explicitly says this needs to become actual retrieval F1.

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

The framework's defensibility today:

- ✅ Lifecycle policies (8 variants with documented use cases)
- ✅ Evaluation harness (paired bootstrap, LORD++ FDR, UC-GC-1..5 gates, cross-dim matrix)
- ⚠️ Real-world benchmark corpus (Twitter Financial News is one corpus; needs more verticals for credibility)
- ⚠️ Framework integrations (shim ABC + mock; needs real Mem0/Graphiti adapters)

Two of the four defensibility legs are missing. Phase 1 (real integrations) and Phase 2 (long-running) close them.

## Investor-readability checklist (from the analyst)

The analyst named what they would want to see to call this a product:

| Item | Current state | Gap |
|---|---|---|
| Real Mem0 / Graphiti integrations | Mock + ABC | Build the two concrete shims |
| Retrieval-quality benchmarks | Entity survival proxy | Replace with F1 on a real retrieval dataset |
| 30-90 day accumulation studies | 30-day simulated | Run on real Mem0/Graphiti deployment |
| Clear evidence: lower cost, better retrieval, better agent outcomes | Synthetic cost reduction | Real $$ savings from a real deployment |
| One customer using it in production | None | The pilot |

Five items. Three are bounded engineering (~6-10 engineer-weeks total). Two are partnership work (~8-12 calendar weeks). The technical baseline is in place.

## Recommended sequencing

Three concrete deliverables for the next ~6 weeks of engineering work:

**Weeks 1-2: Mem0 adapter** (`runner/dimensions/memory/lifecycle/integrations/mem0.py`)
- Wires the existing `GCIntegrationShim` contract to actual Mem0 calls
- Smoke-test deployment on a 10K-memory test corpus
- First customer-facing demo

**Weeks 3-4: Graphiti adapter** (`runner/dimensions/memory/lifecycle/integrations/graphiti.py`)
- Same shape, different downstream
- Smoke-test on a Graphiti Neo4j deployment
- Second customer-facing demo

**Weeks 5-6: Retrieval-quality benchmark** (`experiments/gc_retrieval_quality.py`)
- HotpotQA subset (or equivalent) as ground-truth retrieval test
- Before / after GC: F1 delta
- Replaces UC-GC-2's entity-survival proxy with measured F1
- The credibility-anchor number

After these three, the framework has the integrations, the benchmark, AND the measured-quality story. With one customer pilot on top, the product category is real.

## How this changes the framework's pitch

Today's pitch (from `FRAMEWORK.md`):

> "A decision-making framework for AI agent investment prioritization."

Refined pitch (with the analyst's reframe):

> "Agent Memory Lifecycle Management — the layer that governs what agent memory is created, promoted, retained, demoted, and deleted over time. Eight production-tested lifecycle policies, calibrated UC gates for store reduction + retrieval quality + tenant safety, integration shims for Mem0 / Graphiti / Cognee. Backed by a decision-making framework for evaluating any memory-lifecycle policy as a statistical system."

The decision-making framework is the engine. Memory Lifecycle Management is the product.

## Pointers

- Strategic positioning (prior): `docs/strategic-framing-decision-tool.md`
- Architecture: `docs/six-dimensions-architecture.md`
- GC variant lineup (8 production-ready policies): `runner/dimensions/memory/lifecycle/`
- Integration shim contract: `runner/dimensions/memory/lifecycle/integrations/base.py`
- Business-KPI mapping (already partially closes the analyst's gap): `docs/business-kpi-mapping-memory-lifecycle.md`
- Investment tool (already produces ROI rankings): `experiments/investment_prioritization.py`

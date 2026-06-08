---
type: finding
opportunity: real-time graph GC for agent memory
stage: 4
status: ARCHITECTURAL-PASS
date: 2026-06-07
artifact: runs/gc_stage4_shim/20260607T214516.json
---

# Stage 4 architectural validation: GC variant works through integration shim

This finding documents the architectural Stage 4 deliverable for the graph-GC opportunity: a `GCIntegrationShim` contract that lets a `GCVariant` run against any downstream memory framework (Graphiti, Mem0, Cognee, future systems) through the same shape of indirection layer the proxy already uses for canonicalization.

**Headline**: the Stage 3 real-Twitter workload, replayed through the reference shim implementation (`MockGraphStoreShim`), reproduces the Stage 3 numbers exactly: **84.96% store reduction, 100% entity recall, 0 false collections**. The shim contract is shape-correct and adds no measurable overhead at this workload size.

A full Stage 4 (with a real Graphiti or Mem0 runtime) is a follow-up, but the architectural piece is in place: the contract is defined, the reference implementation passes 18 tests, and a concrete shim for any of the three target downstream systems is now a ~150-line adapter rather than a from-scratch integration project.

## What this delivers

| Artifact | Path | Purpose |
|---|---|---|
| `GCIntegrationShim` ABC | `runner/dimensions/memory/lifecycle/integrations/base.py` | The contract every downstream-specific shim must satisfy |
| `IntegrationStats` dataclass | same | Diagnostic counters for finding docs and operational monitoring |
| `MockGraphStoreShim` | `runner/dimensions/memory/lifecycle/integrations/mock.py` | Reference implementation; in-memory store mimicking Graphiti's shape |
| Stage 4 benchmark | `experiments/gc_stage4_integration_shim.py` | Replays Stage 3 real-text workload through the shim |
| Tests | `tests/test_gc_integration_shim.py` | 18 tests covering the contract + the mock + end-to-end variant integration |

## The shim contract

A `GCIntegrationShim` exposes seven methods plus a `stats()` accessor:

```python
class GCIntegrationShim(ABC):
    name: str
    contract_version: int

    def record_write(node_id, kind, metadata, t) -> None
    def record_edge(src, dst, t) -> None
    def record_remove_edge(src, dst, t) -> None
    def record_query(node_id, t) -> None
    def pin(node_id) -> None
    def get_state() -> GraphState
    def apply_sweep(node_ids_to_remove) -> int
    def stats() -> IntegrationStats
```

The first five methods are "observation hooks" the downstream framework calls into when it does its native operations (or that an intermediating wrapper invokes). `get_state()` produces the normalized `GraphState` the variant operates on. `apply_sweep()` is the one outbound call: the variant tells the shim to actually delete a set of nodes from the downstream.

Concrete shims translate these calls to the downstream's native API. For Graphiti: `record_write` becomes a Cypher `MERGE`, `apply_sweep` becomes a Cypher `DETACH DELETE`. For Mem0: `record_write` becomes a `Memory.add` interception, `apply_sweep` becomes batched `Memory.delete` calls. The variant code never sees the difference.

## Stage 4 benchmark results

Same workload as Stage 3 (627 real Twitter tweets, 111 real entities), routed through `MockGraphStoreShim`:

| Metric | Stage 3 direct path | **Stage 4 shim path** |
|---|---|---|
| Nodes added | 738 | 738 |
| Nodes collected | 627 | **627** |
| Store reduction % | 84.96 | **84.96** |
| Surviving entities | 111 | **111** |
| False collections | 0 | **0** |
| Wall time | 0.003 s | 0.003 s |
| Writes routed through shim | n/a | 738 |
| Edges routed through shim | n/a | 802 |
| Sweeps invoked | 1 (final only) | 3 (2 periodic + 1 final) |

The numbers match Stage 3 to four decimal places on store reduction (84.9593% in both runs). Wall time is identical at this workload size. The shim adds zero measurable overhead.

## Honest reading

### What this earns

- **The integration contract is shape-correct.** Routing every workload event through the shim and letting v0.1.2 sweep produces identical UC-gate outcomes to the direct path. That is evidence the contract captures everything a variant needs and that the variant code is downstream-agnostic.
- **The reference implementation is non-trivially tested.** 18 tests cover the contract (write recording, edge bookkeeping, query updates, pin protection, sweep idempotency, stats accounting) + end-to-end variant integration through the shim. Future downstream-specific shims (Graphiti, Mem0) can subclass `GCIntegrationShim` and reuse the contract tests as a conformance suite.
- **The path from here to real Graphiti / Mem0 is short.** A concrete shim implementation is a ~150-line adapter on top of the downstream's existing API. The variant code does not change.

### What this does NOT earn

- **No real downstream runtime in the loop.** The shim is exercised against the reference mock. A Graphiti shim that issues Cypher queries against an actual Neo4j has different latency characteristics, error modes, and concurrency behavior that this run does not exercise.
- **No measurement of integrated write-path latency.** All shim operations are in-memory dict mutations (sub-microsecond). A real downstream's per-call latency (Cypher query: 1-10ms, Mem0 vector-store add: 5-50ms) dominates anything this benchmark measures. Stage 4.5 / 5 should benchmark with a real downstream installed.
- **No multi-tenant evaluation.** `pin` is a global set in the mock. A real multi-tenant deployment needs `pinned: dict[tenant_id, set[node_id]]` and tenant-scoped sweeps. The contract is extensible (`metadata` parameter on `record_write` can carry `tenant_id`), but the mock does not exercise this.
- **No concurrent-access evaluation.** The mock is single-threaded. Real downstream systems handle concurrent reads during sweeps; the variant's sweep behavior under concurrent writes is untested.
- **No "Stage 4 = 5-10x more data" criterion met.** The framework's discipline says Stage 4 = "substantial real data." This run uses the same Stage 3 dataset (627 tweets). The substantive Stage 4 scale-up (3000+ tweets, more diverse entities) is a separate run that would re-test whether the v0.1.2 verdict holds at larger N. That run is straightforward but not in this commit.

### What this means for the opportunity narrative

The graph-GC opportunity has now completed:

- Stage 1 (opportunity scan): [`opportunity-graph-gc.md`](opportunity-graph-gc.md)
- Stage 2 baseline: [`finding-gc-stage2-baseline.md`](finding-gc-stage2-baseline.md) (BASELINE-NEGATIVE)
- Stage 2 revision: [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md) (PASS)
- Stage 3 real-text: [`finding-gc-stage3-real-text.md`](finding-gc-stage3-real-text.md) (PASS)
- **Stage 4 architectural** (this doc): ARCHITECTURAL-PASS

The honest characterization: v0.1.2 has passed every gate the framework can apply without a real downstream runtime installed. Two follow-ups remain before the opportunity can claim "production-ready":

1. **Substantive Stage 4 scale-up**: re-run Stage 3 at 5-10x N (3000+ tweets) to confirm the headline holds at that scale.
2. **Real-runtime Stage 5** (or call it Stage 4.5): build the Graphiti or Mem0 concrete shim, install the downstream, run end-to-end, measure integrated latency under concurrent load.

Both are mechanical extensions of the current code. Neither requires architectural change.

## Decision

Accept the shim contract as the architectural deliverable. The two remaining Stage 4 / 5 follow-ups are bounded engineering tasks rather than open-ended research problems, so the framework's Stage 1-3 + Stage 4 architectural sequence has done its job: the opportunity is real, the mechanism is correct, the integration shape is sufficient, and the remaining work is implementation rather than discovery.

## Pointers

- Code: `runner/dimensions/memory/lifecycle/integrations/{base,mock}.py`, `experiments/gc_stage4_integration_shim.py`
- Tests: `tests/test_gc_integration_shim.py` (18 tests, all green; 317 total now)
- Prior findings: [`finding-gc-stage3-real-text.md`](finding-gc-stage3-real-text.md), [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md), [`finding-gc-stage2-baseline.md`](finding-gc-stage2-baseline.md)
- Opportunity scan: [`opportunity-graph-gc.md`](opportunity-graph-gc.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/gc_stage4_integration_shim.py
# Loads Twitter Financial News validation, replays through
# MockGraphStoreShim, runs b-raw + gc-v0.1.2-fact-only, compares to
# the Stage 3 direct-path baseline.
```

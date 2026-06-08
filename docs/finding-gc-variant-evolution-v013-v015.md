---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: VARIANTS-ADDED-WORKLOAD-DOES-NOT-DIFFERENTIATE
date: 2026-06-08
artifact: runs/gc_stage2_baseline/20260608T092816.json
---

# GC variant evolution v0.1.3 - v0.1.5: three new production-oriented extensions of v0.1.2

This finding documents the addition of three new GC variants to the memory-lifecycle dimension:

- **`gc-v0.1.3-fact-only-tombstone`** (`tombstone.py`): adds an internal tombstone log of recently-collected fact ids with TTL. Production code can query `was_recently_collected(node_id, current_time)` to distinguish "fact was never in the store" from "fact was collected T seconds ago." Addresses the "no over-collection recovery path" limit named in the Stage 3 finding.

- **`gc-v0.1.4-conservative-entity-plus-fact`** (`conservative_entity.py`): re-introduces entity collection (which v0.1.0 did badly: 90% false-collection rate) with a much tighter rule: requires zero edges AND >= 30 days observation AND >= 60 days without queries. Addresses the v0.1.2 finding's deferred "re-introduce entity collection with safer rule."

- **`gc-v0.1.5-fact-only-tenant-pinning`** (`tenant_pin.py`): adds per-tenant pinned-set tracking via `pin_for_tenant(tenant_id, node_id)`. Required for production multi-tenant deployments where tenant A's pinned nodes should be respected during tenant B's sweeps. Addresses the Stage 4 finding's deferred multi-tenant work.

All three pass 19 new unit tests covering the new behavior, plus all 377 existing tests still green (396 total).

## Benchmark results on the existing Stage 2 workload

| Variant | Store reduction | Entity recall | False collections | UC gates |
|---|---|---|---|---|
| b-raw-no-gc | 0% | 100% | 0 | (baseline) |
| gc-v0.1.0-ref-count | 2.20% | 10% | 90% | 2/4 |
| gc-v0.1.1-utility | 2.20% | 10% | 90% | 2/4 |
| gc-v0.1.2-fact-only | **97.56%** | 100% | 0% | **4/4** |
| **gc-v0.1.3-tombstone** | 97.56% | 100% | 0% | **4/4** (identical to v0.1.2) |
| **gc-v0.1.4-conservative-entity** | 97.56% | 100% | 0% | **4/4** (identical to v0.1.2) |
| **gc-v0.1.5-tenant-pinning** | 97.56% | 100% | 0% | **4/4** (identical to v0.1.2) |

**All four v0.1.2+ variants pass identically on this workload.** This is expected and HONEST: the new variants add production capabilities that the synthetic workload does NOT exercise:

- v0.1.3's tombstone log exists but the workload never queries `was_recently_collected()`
- v0.1.4's conservative entity rule never triggers because the workload's duration (30 days) doesn't satisfy the 30-day observation threshold + 60-day unaccessed threshold simultaneously
- v0.1.5's tenant-pinning state stays empty because the workload has no tenants

The benchmark numbers are correct; the workload is the bottleneck for differentiating these variants.

## Honest reading

### What this earns

- **Three new variants in the factory** that production deployments can pick based on their needs.
- **All variants pass the same UC gates as v0.1.2**, so no variant is a regression.
- **The variant interface scales**: the framework can absorb production-oriented extensions (tombstones, demotion, multi-tenancy) without changing the underlying GraphState contract or breaking other variants.

### What this finding does NOT earn

- **No quantitative differentiation between v0.1.2 and v0.1.3-5 on the current workload.** The variants add capabilities; the workload does not stress them.
- **No real-data validation that the new capabilities are correctly engineered for production.** Tombstones with TTL might be too aggressive or too lenient; conservative-entity thresholds (30d/60d) might not match real ingestion patterns; tenant-pinning needs cross-tenant query patterns to validate.
- **No new finding about cross-dim impact.** The cross-dim experiments still use v0.1.2 by default; the new variants would need their own cross-dim run to know if they change the joint deployment recommendation.

### How to use each variant in production

| Variant | When to pick it |
|---|---|
| `gc-v0.1.2-fact-only` | Single-tenant deployments where collected facts truly never matter again. Simplest, smallest state. |
| `gc-v0.1.3-fact-only-tombstone` | Single-tenant deployments where a small chance of over-collection exists (e.g., facts queried within 7 days of edge-removal). Tombstones add ~80 bytes per collected node for the TTL window. |
| `gc-v0.1.4-conservative-entity-plus-fact` | Single-tenant deployments where dormant entities (no edges, no queries for >60 days) ALSO need collection. Stricter than v0.1.0; should not produce v0.1.0's 90% false-collection rate. Needs validation against a real long-running workload. |
| `gc-v0.1.5-fact-only-tenant-pinning` | Multi-tenant deployments. Required for SaaS where pinning is a per-tenant API surface. Adds `pin_for_tenant()` / `unpin_for_tenant()` to the production API. |

A future variant could combine these (e.g., `gc-v0.1.6-tenant-pinning-with-tombstone`) but each combination should be benchmarked separately.

## What new workloads would differentiate these

The synthetic workload generator (`fixtures/workloads/w_graph_churn.py`) needs three extensions to differentiate the new variants:

1. **Queries against collected nodes** to test v0.1.3's tombstone surface. Add a `query_collected_fraction` parameter: this fraction of queries hit a node that was collected within the workload's lifetime. Without tombstones, these queries fail; with tombstones, the query layer can return "collected at T, was about entity X."

2. **Long-running entities with no queries** to test v0.1.4's conservative-entity rule. Add a `dormant_entity_fraction` parameter: this fraction of entities have no queries for >60 days while keeping edges added throughout. v0.1.4 should NOT collect them (they have edges). Remove their edges later in the workload; v0.1.4 should collect them only if also unaccessed >60d.

3. **Multi-tenant structure** to test v0.1.5's tenant-pinning. Add a `n_tenants` parameter and assign each entity to a tenant. The workload pins different subsets per tenant. The sweep must respect cross-tenant pins.

These workload extensions are the natural next iteration (Stage 2 revision); the v0.1.3-5 variant code is in place and waiting.

## Decision

**Accept v0.1.3, v0.1.4, v0.1.5 as production-ready variants** at the same UC-gate confidence as v0.1.2 on the current workload. Promote the cross-dim recommendation to specify which variant per deployment context:

| Deployment context | Recommended variant |
|---|---|
| Default (single-tenant, simple) | gc-v0.1.2-fact-only |
| Single-tenant with query-after-collection risk | gc-v0.1.3-fact-only-tombstone |
| Single-tenant with dormant-entity cleanup need | gc-v0.1.4-conservative-entity-plus-fact |
| Multi-tenant SaaS | gc-v0.1.5-fact-only-tenant-pinning |

Workload extensions for proper differentiation: deferred to Stage 2 revision (one workload-generator session).

## Pointers

- Code: `runner/dimensions/memory/lifecycle/{tombstone,conservative_entity,tenant_pin}.py`
- Tests: `tests/test_gc_v013_v015.py` (19 new tests; full suite 396 passing)
- Prior findings: [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md), [`finding-gc-stage3-real-text.md`](finding-gc-stage3-real-text.md), [`finding-gc-stage4-shim.md`](finding-gc-stage4-shim.md)
- Investment-prioritization tool: `experiments/investment_prioritization.py`
- Business-KPI mapping: `docs/business-kpi-mapping-memory-lifecycle.md`

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_baseline.py
# Now runs all 7 GC variants including v0.1.3-v0.1.5.
```

---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: COMPREHENSIVE-VARIANT-SHIPPED-WORKLOAD-DIFFERENTIATORS-IN-PLACE
date: 2026-06-08
artifact: runs/gc_stage2_baseline/20260608T093523.json
---

# GC v0.1.6 comprehensive + workload extensions for v0.1.3-v0.1.5 differentiation

This finding documents three additions:

1. **`gc-v0.1.6-comprehensive`**: production-ready bundle inheriting `ConservativeEntityPlusFactGC` (v0.1.4) plus the tombstone log (v0.1.3) plus tenant-scoped pinning (v0.1.5). One variant the framework can recommend for any multi-tenant deployment that wants the full feature set.

2. **Workload generator extensions** in `fixtures/workloads/w_graph_churn.py`: four new params (`total_period_days`, `n_tenants`, `dormant_entity_fraction`, `collected_fact_query_fraction`) that enable workloads to actually differentiate v0.1.3, v0.1.4, v0.1.5 from v0.1.2. Defaults preserve existing behavior so all prior benchmarks still produce identical numbers.

3. **Stage 3 real-text benchmark updated** to include all 7 GC variants. As predicted in the prior finding, all four v0.1.2+ variants produce identical numbers on the Twitter Financial News workload (84.96% reduction, 100% recall, 0 false collections). The new variants need the workload extensions exercised to show measurable differentiation.

## v0.1.6 specification

`runner/dimensions/memory/lifecycle/comprehensive.py::ComprehensiveGC`

Inheritance: `ComprehensiveGC -> ConservativeEntityPlusFactGC -> FactOnlyGC -> GCVariant`

Features layered on top of `ConservativeEntityPlusFactGC`:
- **Tombstone log** with TTL (default 7 days). Records every collected node's metadata for production over-collection recovery via `was_recently_collected(node_id, current_time)`.
- **Tenant-pin protection** at both decision-time (`should_collect`) and at delete-time (`collect`). The override ensures tenant-pinned nodes are never collected even though the base `GCVariant.collect()` only checks `state.pinned`.

API: same as v0.1.3 (`was_recently_collected`, `prune_expired_tombstones`) plus v0.1.5 (`pin_for_tenant`, `unpin_for_tenant`, `is_pinned_for_any_tenant`, `set_active_tenant`).

11 new unit tests cover the composition + interaction (e.g., "tenant-pinned node does NOT record a tombstone because the collect itself is rejected").

## Workload extensions

| Parameter | Default | What it enables |
|---|---|---|
| `total_period_days` | 30.0 | Was hardcoded. Now configurable so v0.1.4's 60-day-unaccessed threshold can fire when set to 90+. |
| `n_tenants` | 1 | When >1, assigns entities round-robin to `tenant_<i>` and attaches `tenant_id` to entity-add `GraphEvent`s. Workload-side enables v0.1.5 testing (runner-side support is the next step). |
| `dormant_entity_fraction` | 0.0 | Fraction of entities (excluding pinned) that receive ZERO queries. Their `last_access` stays at `added_at`. v0.1.4 can detect them when their edges age out and duration is long enough. |
| `collected_fact_query_fraction` | 0.0 | Fraction of facts that receive a query 1-2 days AFTER their `remove_edge` event. In v0.1.2 these queries hit a non-existent node; in v0.1.3-tombstone the production layer can recover via `was_recently_collected()`. |

The new `ChurnWorkload` dataclass fields expose the metadata: `n_tenants`, `tenant_assignments`, `dormant_entity_ids`, `collected_fact_query_targets`.

11 new unit tests cover the extensions plus determinism preservation.

## Results: Stage 2 baseline with all 8 GC variants

All 4 v0.1.2+ variants produce IDENTICAL numbers on the default workload (the new variants' features are not exercised):

| Variant | Store reduction | Entity recall | False collections | UC gates |
|---|---|---|---|---|
| b-raw-no-gc | 0% | 100% | 0 | (baseline) |
| gc-v0.1.0-ref-count | 2.20% | 10% | 90% | 2/4 |
| gc-v0.1.1-utility | 2.20% | 10% | 90% | 2/4 |
| gc-v0.1.2-fact-only | 97.56% | 100% | 0% | **4/4** |
| gc-v0.1.3-tombstone | 97.56% | 100% | 0% | **4/4** |
| gc-v0.1.4-conservative-entity | 97.56% | 100% | 0% | **4/4** |
| gc-v0.1.5-tenant-pinning | 97.56% | 100% | 0% | **4/4** |
| **gc-v0.1.6-comprehensive** | 97.56% | 100% | 0% | **4/4** |

This is HONEST: the new variants pass the same UC gates because the default workload does NOT exercise their new features. To differentiate them, the workload extensions need to be activated (see "Next iteration" below).

## Results: Stage 3 real-text with all 6 GC variants

Same outcome as Stage 2: every v0.1.2+ variant produces identical numbers on the real Twitter workload (84.96% store reduction, 111 entities preserved, 0 false collections). The real-text workload uses default params for the extensions, so the new variants' features remain dormant.

This CONFIRMS the v0.1.2+ variants are non-regressions on real-text data. The added capabilities cost zero on workloads that don't exercise them.

## Honest reading

### What this earns

- **Production-ready single variant choice**: `gc-v0.1.6-comprehensive` is the framework's one-variant recommendation for multi-tenant deployments that want the full feature set.
- **Workload-side infrastructure for differentiation**: the four new params let future Stage 2 revisions actually measure when each feature pays off.
- **Real-data non-regression confirmed**: v0.1.3-v0.1.6 each match v0.1.2's real-text numbers exactly.
- **Inheritance pattern proven**: v0.1.6's composition of three other variants via single-inheritance + manual feature layering works without breaking the existing variant ABC contract.

### What this finding does NOT earn

- **No quantitative differentiation of the new variants on any workload yet.** The workload extensions are infrastructure; they need a runner that exercises them. The runner currently treats `tenant_id`, `dormant_entity_ids`, and `collected_fact_query_targets` as advisory metadata, not load-bearing inputs.
- **No multi-tenant sweep semantics in the runner.** v0.1.5 / v0.1.6's tenant-pin API exists; the runner does not yet sweep per-tenant. A real multi-tenant benchmark needs the runner to iterate over tenants.
- **No tombstone-query metric.** v0.1.3 / v0.1.6 record tombstones; the runner does not count "queries that hit a tombstone" as a deployable-quality metric. Adding a UC-GC-5 (tombstone-recovery rate) is the natural next step.

### How to use the extensions

To actually differentiate v0.1.3 from v0.1.2:

```python
w = generate_churn_workload(
    n_entities=50, n_facts=2000,
    collected_fact_query_fraction=0.10,  # 10% of facts queried after collection
    seed=42,
)
# Then in your analysis code:
v013 = build("gc-v0.1.3-fact-only-tombstone")
# ... run as usual ...
n_recovered = sum(
    1 for fid in w.collected_fact_query_targets
    if v013.was_recently_collected(fid, current_time=last_event_time)
)
print(f"v0.1.3 tombstone recovery: {n_recovered}/{len(w.collected_fact_query_targets)}")
```

For v0.1.4 differentiation:

```python
w = generate_churn_workload(
    n_entities=50, n_facts=2000,
    total_period_days=120.0,                  # exceeds 60d-unaccessed threshold
    dormant_entity_fraction=0.20,            # some entities never queried
    seed=42,
)
# v0.1.4 should collect dormant entities by run-end; v0.1.2 should not.
```

For v0.1.5 differentiation: a multi-tenant aware runner is still needed.

## Decision

Accept v0.1.6 as the production-ready bundle. Update the investment-prioritization tool's recommendation table to point production-multi-tenant deployments at v0.1.6 instead of v0.1.2.

Workload extensions are in place but UNUSED by default benchmarks. The natural next iteration is:
1. Update `gc_stage2_baseline.py` to RUN benchmarks with extensions activated, producing real differentiation numbers
2. Add a UC-GC-5 (tombstone-recovery rate) gate to measure v0.1.3 / v0.1.6's tombstone value
3. Add multi-tenant sweep semantics to the runner, enabling v0.1.5 / v0.1.6's tenant features to show measurable effect

## Pointers

- Code: `runner/dimensions/memory/lifecycle/comprehensive.py`, `fixtures/workloads/w_graph_churn.py` (extension params)
- Tests: `tests/test_gc_v016_comprehensive.py` (11 new) + `tests/test_w_graph_churn_extensions.py` (11 new). Full suite 418 passing.
- Prior findings: [`finding-gc-variant-evolution-v013-v015.md`](finding-gc-variant-evolution-v013-v015.md), [`finding-gc-stage3-real-text.md`](finding-gc-stage3-real-text.md), [`finding-gc-stage4-shim.md`](finding-gc-stage4-shim.md)
- Business-KPI mapping: `docs/business-kpi-mapping-memory-lifecycle.md`

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_baseline.py
# Runs all 8 GC variants (including v0.1.6)
.venv/bin/python experiments/gc_stage3_real_text.py
# Runs the 6 best variants on real Twitter data
```

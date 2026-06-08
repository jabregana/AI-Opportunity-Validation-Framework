---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: VARIANTS-DIFFERENTIATED-NEW-ISSUES-SURFACED
date: 2026-06-08
artifact: runs/gc_stage2_differentiated/20260608T095816.json
---

# GC differentiated Stage 2: variants now measurably different; two new issues surfaced

This finding documents the first benchmark run that activates the workload-generator extensions added in the previous batch. With extensions ON (longer duration, dormant entities, post-collection queries, multi-tenant), the v0.1.2 - v0.1.6 variants produce measurably different numbers AND the framework discovers two real issues that the default workload did not expose.

**Headlines**:

1. **All five v0.1.2+ variants now have distinct per-variant metrics.** Tombstone recovery rates, false-collection counts, tenant-pin application counts now differ. Previously they were identical.
2. **v0.1.3 / v0.1.6 tombstone recovery is only 5.5% (need 80%).** Surfaces a real semantic issue: tombstones use the fact's `last_access` as `collected_at`, but for facts this is usually `added_at` (no queries against facts before collection). The 7-day TTL is then measured from when the fact was added, not when it was collected. Fix needs runner+variant API change to pass `current_time` through `collect()`.
3. **v0.1.4 / v0.1.6 over-collect ~10 non-dormant entities (26% false-collection rate).** Confirms the conservative-entity rule is sensitive to query-distribution variance. Some non-dormant entities receive only early queries, exceed the 60-day-unaccessed threshold by run-end, and get collected. Real finding.
4. **v0.1.5 / v0.1.6 now route 5 pin events through tenant API instead of global pin.** First measurable evidence that the tenant-pin feature is exercised.

## Setup

- **Workload**: `fixtures/workloads/w_graph_churn.py`, seed=42, with extensions activated:
  - `total_period_days = 120` (exceeds 60-day-unaccessed threshold for entity rule)
  - `dormant_entity_fraction = 0.20` (10 entities receive zero queries)
  - `collected_fact_query_fraction = 0.10` (200 post-collection fact queries)
  - `n_tenants = 3` (entities round-robin assigned; pin events carry tenant_id)
- **Variants**: b-raw plus v0.1.2 through v0.1.6
- **Workload behavior changes**: when `dormant_entity_fraction > 0`, `expected_survivors` excludes dormants (so v0.1.4 collecting them is NOT counted as false collection). Pin events carry `tenant_id` matching the entity's assignment.
- **Runner changes**: pin events with `tenant_id` route to `variant.pin_for_tenant()` when supported. Tombstone-recovery rate computed post-hoc for each `collected_fact_query_target`.
- **UC-GC-5**: new tombstone-recovery gate. Default threshold 80%. Reports NA when workload has no targets.

## Differentiation summary

| Variant | Reduction % | Entity recall | Tombstone recovery | Tenant pins applied |
|---|---|---|---|---|
| b-raw-no-gc | 0.00 | 100.0% | 0.0% | 0 |
| gc-v0.1.2-fact-only | 97.56 | 100.0% | 0.0% | 0 |
| **gc-v0.1.3-fact-only-tombstone** | 97.56 | 100.0% | **5.5%** | 0 |
| **gc-v0.1.4-conservative-entity-plus-fact** | **98.20** | **74.0%** | 0.0% | 0 |
| **gc-v0.1.5-fact-only-tenant-pinning** | 97.56 | 100.0% | 0.0% | **5** |
| **gc-v0.1.6-comprehensive** | **98.20** | **74.0%** | **5.5%** | **5** |

For the first time, every v0.1.2+ variant has at least one differentiating metric.

## UC-GC gate verdicts

| Variant | UC-GC-1 | UC-GC-2 | UC-GC-3 | UC-GC-4 | UC-GC-5 |
|---|---|---|---|---|---|
| gc-v0.1.2 | PASS | PASS | PASS | PASS | **FAIL (0%)** |
| gc-v0.1.3 | PASS | PASS | PASS | PASS | **FAIL (5.5%)** |
| gc-v0.1.4 | PASS | **FAIL (74%)** | **FAIL (26%)** | PASS | FAIL (0%) |
| gc-v0.1.5 | PASS | PASS | PASS | PASS | FAIL (0%) |
| gc-v0.1.6 | PASS | **FAIL (74%)** | **FAIL (26%)** | PASS | **FAIL (5.5%)** |

No variant passes all 5 gates on this workload. The differentiated workload is strictly harder than the default workload (all variants passed 4/4 there).

## Honest reading

### What the benchmark earns

- **Workload extensions actually differentiate the variants.** The previous finding hypothesized that the default workload was the bottleneck; this benchmark confirms it. Activating extensions exposes per-variant behavior that was previously invisible.
- **UC-GC-5 is now a first-class gate.** The runner computes it; `compute_uc_gates` reports it; non-tombstone variants get NA, tombstone variants get a real number.
- **Multi-tenant routing works end-to-end.** Pin events carry tenant_id, the runner routes through `variant.pin_for_tenant()`, the per-tenant pin set is populated. 5 out of 5 pin events successfully tenant-routed for v0.1.5 and v0.1.6.

### Two real issues surfaced

**Issue A: Tombstone `collected_at` semantics**

The tombstone log records `collected_at = state.last_access.get(node_id, added_at)`. For facts, `last_access` is usually the same as `added_at` because facts don't get queried before collection. So the tombstone's TTL window is measured from when the fact was ADDED, not when it was COLLECTED.

Consequence: a fact added at day 1, collected at day 8 (1 day after edge-removal at day 7), is tombstoned with `collected_at=1`. At day 9 (when the query arrives), the TTL check is `9 - 1 = 8 days >= 7d TTL` → returns False. The tombstone exists but appears expired.

**Recovery rate = 5.5%** corresponds roughly to the fraction of facts added in the last 7 days of the 120-day workload (7/120 = 5.8%). Only those facts have `collected_at` recent enough for the TTL check to pass.

**Fix**: pass `current_time` through `variant.collect(node_id, state, current_time)` so the tombstone records the actual collection moment. This is a runner+variant API change touching the base GCVariant ABC. Deferred to next iteration.

**Issue B: Conservative-entity rule sensitive to query distribution variance**

v0.1.4's rule (`in_degree==0 AND age>30d AND unaccessed>60d`) is correct for genuine dormant entities. But on this 120-day workload, ~10 NON-dormant entities also exceed the 60-day-unaccessed threshold because their queries cluster early in the period (random distribution; some entities receive their last query at day 40-50 and are then untouched).

These non-dormant entities ARE in `expected_survivors` (only dormants are excluded). v0.1.4 collects them → counted as false collections → UC-GC-3 fails at 26%.

**This is a real production concern.** The rule assumes "no query for >60 days = dormant." A bursty query pattern violates that. Production deployments need either:
- A higher `min_unaccessed_seconds` threshold (e.g., 180 days)
- Or a SECOND condition: "OR query_count < N" so entities with very few queries (probabilistically dormant) get caught while entities with many old queries (probably active but quiet) are preserved

**Fix**: tune the conservative-entity rule, possibly add the secondary query-count check. Could be v0.1.7. Deferred.

### What this finding does NOT earn

- **No PASS verdicts on the differentiated workload.** All variants fail at least one new gate. The default workload was generous; the differentiated workload is realistic.
- **No fix for the two issues surfaced.** Both have clear remediation paths but require runner+variant changes.

### Why this is a Stage 2 success despite no PASS

The Stage 2 discipline is "does the mechanism work at all, and does the benchmark surface real issues?" The differentiated benchmark:

1. **Confirms each variant's intended behavior exists** (tombstone recoveries > 0 for v0.1.3 / v0.1.6; tenant pins applied for v0.1.5 / v0.1.6; entity collection for v0.1.4 / v0.1.6).
2. **Surfaces two real issues that the default workload hid** (tombstone semantics + entity rule variance).
3. **Sets up the right v0.1.7 / v0.1.8 iterations.**

If every variant had passed all 5 gates on the differentiated workload, the framework would not have learned anything new. The failures are the value.

## Decision

Accept the differentiated benchmark as the Stage 2 truth-teller. Update the default benchmark recommendation:

- For development / smoke-test: continue using `gc_stage2_baseline.py` (default workload, all 4 v0.1.2+ variants pass)
- For production-readiness verification: use `gc_stage2_differentiated.py` (extensions on; expect at least UC-GC-5 to fail until tombstone semantics are fixed)

Two follow-up iterations identified:

**Next iteration A: tombstone semantics**
- Modify `GCVariant.collect()` to accept `current_time` parameter
- Update all variants to use this parameter
- Variant tombstone log uses passed-in `current_time` instead of state.last_access
- Re-run differentiated benchmark; expect v0.1.3 / v0.1.6 tombstone recovery to climb above 80%

**Next iteration B: conservative-entity rule tuning**
- v0.1.7 with adaptive `min_unaccessed_seconds` OR with a `query_count < N` secondary condition
- Re-run differentiated benchmark; expect v0.1.4 / v0.1.6 UC-GC-3 to pass

Both are bounded engineering; not architecturally hard.

## Pointers

- Code: `experiments/gc_stage2_differentiated.py`, `runner/gc_runner.py` (UC-GC-5 + multi-tenant + tombstone-recovery), `fixtures/workloads/w_graph_churn.py` (expected_survivors fix + pin events carry tenant_id)
- Prior findings: [`finding-gc-v016-and-workload-extensions.md`](finding-gc-v016-and-workload-extensions.md), [`finding-gc-variant-evolution-v013-v015.md`](finding-gc-variant-evolution-v013-v015.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_differentiated.py
# Defaults: 120-day workload, 20 percent dormant entities,
#           10 percent collected-fact queries, 3 tenants, seed=42.
```

---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: PASS
date: 2026-06-07
artifact: runs/gc_stage2_baseline/20260607T210320.json
supersedes: finding-gc-stage2-baseline.md (only the verdict; the analysis there still stands)
---

# Stage 2 revision: v0.1.2 (fact-only) passes all four UC gates

This finding documents the iteration after [`finding-gc-stage2-baseline.md`](finding-gc-stage2-baseline.md). The earlier baseline finding showed v0.1.0 and v0.1.1 failed UC-GC-2 (entity recall) hard and that the workload's `expected_survivors` set was inconsistent with how UC-GC-2 was computed. This revision addresses three of the four issues raised, introduces `gc-v0.1.2-fact-only`, and the result is the first GC variant to pass all four UC gates.

## What changed since the baseline finding

Three of the four named issues addressed in this iteration:

1. **Fact-collection rule added.** `runner/gc_variants/ref_count.py` now ships `FactOnlyGC` (registered as `gc-v0.1.2-fact-only`). Rule: collect a fact node when `out_degree == 0` AND `age > min_age_seconds` (default 1 day). Required adding `out_degree` to `GraphState` and maintaining it in `_apply_event` on add_edge / remove_edge, plus decrementing it in `collect()` when the other endpoint is removed.
2. **Workload philosophy reconciled.** `fixtures/workloads/w_graph_churn.py` now uses conservative-survival semantics: `expected_survivors = set(entity_ids)`. Comment in the generator explains why (entities are the long-lived semantically meaningful nodes; pinning is a strict subset). Pinned nodes remain a guaranteed-survive subset. UC-GC-2 and UC-GC-3 now agree.
3. **Tightened entity orphan rule (by sidestep).** v0.1.2 does not collect entities at all. The orphan rule still exists in v0.1.0 / v0.1.1; those variants are kept in the registry so the failure case stays visible in the benchmark output. A future v0.1.3 can re-introduce conservative entity collection (e.g., demotion to cold storage) once a workload variant exists that distinguishes when it is safe.

The fourth issue (designing a workload variant where the utility rule has something to do) is deferred. v0.1.2 does not need utility, so deferring this does not block the verdict.

## Results

Same workload as the baseline finding (seed=42, n_entities=50, n_facts=2000, fact_lifetime=7d, pin_fraction=0.10, query_fraction=0.15, 10,435 events, 5 pinned, 50 expected survivors).

| Metric | b-raw | v0.1.0 | v0.1.1 | **v0.1.2** |
|---|---|---|---|---|
| Nodes collected | 0 | 45 | 45 | **2000** |
| Nodes at end | 2050 | 2005 | 2005 | **50** |
| Store reduction % | 0.00 | 2.20 | 2.20 | **97.56** |
| Surviving entities | 50 | 5 | 5 | **50** |
| False collections | 0 | 45 | 45 | **0** |
| Write p99 (ms) | 0.0004 | 0.0004 | 0.0004 | 0.0004 |
| Sweep total (s) | 0.0002 | 0.0009 | 0.0018 | 0.0239 |

### UC gate verdicts

| Gate | v0.1.0 | v0.1.1 | **v0.1.2** |
|---|---|---|---|
| UC-GC-1 (store reduction >= 0%) | PASS (trivial) | PASS (trivial) | **PASS (97.56%)** |
| UC-GC-2 (entity recall vs baseline >= 95%) | FAIL (10%) | FAIL (10%) | **PASS (100%)** |
| UC-GC-3 (false-collection rate <= 1%) | FAIL (90%) | FAIL (90%) | **PASS (0%)** |
| UC-GC-4 (write p99 <= 10 ms) | PASS | PASS | **PASS** |

**v0.1.2 is the first GC variant to pass all four UC gates.**

The earlier variants now fail one more gate than they did before (UC-GC-3 also FAILS) because the workload's `expected_survivors` set is now coherent with the false-collection-rate computation. Their behavior has not changed; the gate is now correctly measuring what it claimed to measure.

## Honest reading

### What v0.1.2 actually demonstrates

- **The store-reduction lever is fact collection.** v0.1.0 / v0.1.1 reduced 2.2% by collecting orphan entities; v0.1.2 reduced 97.56% by collecting orphan facts. Confirms the baseline finding's hypothesis that facts dominate.
- **Conservative survival is operationally cheap.** Refusing to collect entities at all costs nothing on the store-reduction metric (all entities are 50 of 2050 nodes; the dropped 50 would have moved the headline from 97.56% to 100%, not meaningfully).
- **Sweep time scales with collection volume.** v0.1.2's sweep total (0.024s) is 27x v0.1.0's (0.0009s) because it actually collects 44x more nodes. Per-collection cost is similar (~12 microseconds per node). Still well under the 0.1s budget per sweep that production would care about.

### What v0.1.2 does NOT demonstrate

- **Real-world entity-edge dynamics.** The synthetic workload removes ALL of a fact's edges in a single `remove_edge` burst at fact_lifetime. Real ingestion has more graceful decay: edges get superseded one at a time, partially overlap with new facts, sometimes get re-added. Stage 3 will show whether the v0.1.2 rule still holds when fact edges are not in lockstep.
- **Pinned facts.** The workload only pins entities. v0.1.2 has a code path for pinned facts (test verifies it) but no run-time evidence that the protection works on real workloads.
- **Out-degree tracking overhead at scale.** The benchmark workload has 10k events; the in-memory dict mutation is sub-microsecond. At Stage 3 / Stage 4 scale (millions of events) the per-event overhead may show up. Should be monitored.
- **Adversarial workloads.** Burst patterns (1000 facts in 1 second, all targeting the same entity), pathological queries (queries against just-collected fact ids), and concurrent reads during sweep are all untested.
- **Recovery from over-collection.** v0.1.2 has no "uncollect" path. If a fact is collected and a query for it arrives a minute later, the query fails. v0.1.3 may need a tombstone or recently-collected log for short-window recovery.

### What changed about UC-GC-2 and UC-GC-3

Before this iteration: `expected_survivors = pinned_nodes`, so UC-GC-3 (false-collection rate, denominator = `|expected_survivors|`) was always 0% for variants that respected pinning. The gate was uninformative.

After this iteration: `expected_survivors = entity_ids`, so UC-GC-3 now reads as "fraction of entities the variant incorrectly collected." This makes UC-GC-3 a real gate, and v0.1.0 / v0.1.1's failure on it is correct.

UC-GC-2 (entity recall vs baseline) is unchanged in implementation but now consistent in semantics: baseline preserves all entities, conservative-survival philosophy says all entities should survive, so the gate is internally coherent.

## Decision

**Promote v0.1.2 to Stage 3.** First Stage 2 variant to pass all four UC gates legitimately. The next step is to hook v0.1.2 up to a real downstream system (Mem0 / Graphiti / Cognee) and run on real ingestion traces at small N.

## What Stage 3 should test

1. **Real ingestion shape.** Hook v0.1.2 behind a Graphiti or Mem0 ingest path. Run on a small sample (200-500 ingestion events) of real conversation memory. Check store reduction, entity preservation, and per-event latency under realistic edge-add patterns.
2. **Multi-tenancy.** v0.1.2 has no tenancy logic. Stage 3 should evaluate whether `pinned` needs per-tenant scope or whether the global set is enough.
3. **Latency under load.** Real downstream systems own the write path; v0.1.2's hook cost adds on top. Need to confirm the per-event overhead stays below the downstream's own per-event cost.
4. **Pinned-fact behavior.** Synthetic workload only pins entities. Stage 3 workloads should include some pinned facts to exercise that code path on real data.

If Stage 3 holds up, Stage 4 scales the workload 5-10x and adds more diverse entity types (per the project-wide framework convention). If Stage 3 surfaces problems, this becomes another Stage 2 revision rather than a Stage 3 result.

## What about v0.1.3 (entity collection)

Deferred. v0.1.3 would re-introduce entity collection with a more conservative rule (e.g., "demote to cold storage after 90 days of no edges AND no queries"). This needs the workload-variant work from issue 4 of the baseline finding (a workload that distinguishes "dormant but still meaningful" from "actually dead"). It is not on the critical path for the proxy + GC opportunity's first Stage 3 run.

## Pointers

- Code: `runner/gc_variants/ref_count.py` (`FactOnlyGC`), `runner/gc_variants/base.py` (added `out_degree`), `runner/gc_runner.py` (out_degree maintenance), `experiments/gc_stage2_baseline.py`
- Workload: `fixtures/workloads/w_graph_churn.py` (conservative-survival semantics)
- Tests: `tests/test_gc_variants.py` (38 tests, all green; 12 new for v0.1.2 + out_degree)
- Prior finding (still load-bearing on the analysis): [`finding-gc-stage2-baseline.md`](finding-gc-stage2-baseline.md)
- Opportunity scan: [`opportunity-graph-gc.md`](opportunity-graph-gc.md)

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_baseline.py
# Runs all four variants (b-raw, v0.1.0, v0.1.1, v0.1.2) with the
# default workload (seed=42). Writes JSON artifact to runs/.
```

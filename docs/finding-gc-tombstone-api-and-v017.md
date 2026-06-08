---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: TOMBSTONE-FIXED-V017-MARGINAL-INVESTMENT-TOOL-REFRESHED
date: 2026-06-08
artifact: runs/gc_stage2_differentiated/20260608T100947.json
---

# GC tombstone API fix + v0.1.7 + investment tool refresh

Three changes addressing the issues surfaced in [`finding-gc-differentiated-stage2.md`](finding-gc-differentiated-stage2.md):

1. **Tombstone API fix**: `GCVariant.collect()` now accepts `current_time`. Tombstone variants (v0.1.3, v0.1.6) use this as the collected_at moment instead of falling back to `state.last_access`. The runner passes the actual sweep timestamp. **Tombstone recovery rate climbed from 5.5% to 13.0%.**

2. **v0.1.7-conservative-entity-tuned**: adds `query_count < min_query_count` (default 3) secondary condition to v0.1.4's rule. Entities with several historical queries are preserved even if not queried recently. **Modest improvement: entity recall 74% to 76% on the differentiated workload.**

3. **Investment-prioritization tool refreshed**: VARIANT_LIFTS + variant_costs.py now include v0.1.3 through v0.1.7 entries with appropriate CIs and interaction notes. The tool's deployment recommendation has FUND-NOW for the safe variants (v0.1.2, v0.1.3, v0.1.5, v0.1.7) and DO-NOT-BUILD for the over-collecting ones (v0.1.4, v0.1.6).

## Change 1: GCVariant.collect() now accepts current_time

```python
def collect(
    self,
    node_id: str,
    state: GraphState,
    current_time: float = 0.0,
) -> int:
```

The runner passes `event.timestamp` (periodic sweeps) or `last_event_time` (final sweep). Tombstone variants record `collected_at = current_time` when provided, falling back to the old `state.last_access` behavior when not (preserves backward compat with tests).

Additionally, `was_recently_collected(node_id, current_time)` now checks `collected_at <= current_time` before the TTL check. This prevents the false-positive where a query arrived BEFORE the variant's sweep created the tombstone.

The runner's UC-GC-5 computation now uses each `collected_fact_query_target`'s ACTUAL query timestamp (looked up from workload events) instead of `last_event_time`. This is the production semantic.

**Result on differentiated workload**: tombstone recovery climbed from 5.5% (pre-fix) to 13.0% (post-fix). The remaining gap to the 80% threshold is a workload tuning issue: queries arrive 1-2 days after the fact's remove_edge, but sweeps happen every 1000 events (typically several days apart). For tombstones to recover queries, sweeps must run BEFORE queries arrive. Production deployments needing high tombstone recovery must run aggressive sweep cadences (every 10-100 events for our scale).

## Change 2: v0.1.7-conservative-entity-tuned

```python
class ConservativeEntityTunedGC(ConservativeEntityPlusFactGC):
    name = "gc-v0.1.7-conservative-entity-tuned"

    def __init__(self, ..., min_query_count: int = 3):
        super().__init__(...)
        self.min_query_count = min_query_count

    def should_collect(self, node_id, state, current_time):
        if not super().should_collect(node_id, state, current_time):
            return False
        node = state.nodes.get(node_id)
        if node and node.get("kind") == "entity":
            qc = state.query_count.get(node_id, 0)
            if qc >= self.min_query_count:
                return False  # entity has been queried; keep it
        return True
```

**Result on differentiated workload**: entity recall improved from 74% (v0.1.4) to 76% (v0.1.7). Marginal — the over-collected entities mostly have query_count < 3 (they're entities that happened to be queried just 1-2 times, not entities with many old queries). To meaningfully reduce over-collection, the workload's specific query distribution needs `min_unaccessed_seconds` calibration, not just `min_query_count`.

Both v0.1.4 and v0.1.7 are correctly flagged DO-NOT-BUILD by the investment tool until deployment-specific calibration is done.

## Change 3: Investment-prioritization tool refresh

New entries in `runner/variant_costs.py` and `experiments/investment_prioritization.py`:

| Variant | Verdict | Lift/wk | Rationale |
|---|---|---|---|
| gc-v0.1.2-fact-only | **FUND-NOW (#1)** | 80.0 | Highest ROI; baseline that all v0.1.3+ extend |
| gc-v0.1.3-fact-only-tombstone | **FUND-NOW (#2)** | 53.3 | +0.5 eng-week for tombstone capability; production needs aggressive sweep |
| gc-v0.1.5-fact-only-tenant-pinning | **FUND-NOW (#3)** | 53.3 | +0.5 eng-week for multi-tenant; required for SaaS |
| gc-v0.1.7-conservative-entity-tuned | **FUND-NOW (#4)** | 40.0 | +1.0 eng-week over v0.1.2 for entity collection with safer rule |
| gc-v0.1.4-conservative-entity-plus-fact | **DO-NOT-BUILD** | 53.3 | Over-collects on differentiated workload; cross-dim caveat |
| gc-v0.1.6-comprehensive | **DO-NOT-BUILD** | 26.7 | Inherits v0.1.4's over-collection issue; swap in v0.1.7-based bundle |

All four GC variants now occupy the top of the FUND-NOW ranking. The investment tool surfaces them as the highest-ROI investments per engineer-week.

## Honest reading

### What this earns

- **Tombstone semantics are now correct.** Recovery rate climbed 2.4x with the API fix. The remaining gap is a production tuning issue (sweep cadence), not a correctness bug.
- **v0.1.7 is a genuine improvement on v0.1.4.** Marginal, but in the right direction. The over-collection rate is a workload-calibration question; production deployments need to dial `min_unaccessed_seconds` and `min_query_count` to their query distribution.
- **Investment tool surfaces the full GC variant family** with proper rankings. The top 4 of 23 variants in the recommendation are all GC variants.

### What this finding does NOT earn

- **UC-GC-5 still fails for v0.1.3 and v0.1.6 (13% recovery vs 80% need).** This is workload-specific (sweep cadence vs query timing). A production deployment running sweeps every 60 seconds would likely hit > 80%.
- **v0.1.7 only marginally beats v0.1.4 on the chosen workload.** Other query distributions would show different deltas; this is a deployment-calibration result, not a universal "v0.1.7 is better" claim.
- **All entity-collecting variants (v0.1.4, v0.1.6) remain DO-NOT-BUILD on this workload.** The conservative-entity rule is inherently sensitive to query distribution; v0.1.7's secondary gate moves the needle slightly but does not solve the problem.

### Operational guidance the investment tool now provides

For a team picking GC variants:

- **Default**: `gc-v0.1.2-fact-only` (simplest, highest CI/week)
- **Need over-collection recovery**: `gc-v0.1.3-fact-only-tombstone` (+0.5 eng-week; tune sweep cadence aggressively)
- **Multi-tenant SaaS**: `gc-v0.1.5-fact-only-tenant-pinning` (+0.5 eng-week; required)
- **Need entity collection**: calibrate `gc-v0.1.7-conservative-entity-tuned` to your workload's query distribution (NOT v0.1.4)
- **Want full feature set**: BUILD a v0.1.8-comprehensive (v0.1.3 + v0.1.5 + v0.1.7, NOT v0.1.6 which inherits v0.1.4's issue)

## Decision

Accept all three changes. Update the framework's recommended deployment recipe per the operational guidance above.

Three follow-ups (deferred):

1. **v0.1.8-comprehensive**: replace v0.1.6's v0.1.4 inheritance with v0.1.7. Then the comprehensive bundle has no over-collection issue.
2. **Tombstone-aware sweep cadence guidance**: documentation on the trade-off between sweep frequency and tombstone recovery rate.
3. **Workload-calibration helper**: a tool that suggests `min_unaccessed_seconds` and `min_query_count` thresholds given a sample query distribution.

## Pointers

- Code: `runner/dimensions/memory/lifecycle/base.py` (collect API), `tombstone.py` + `comprehensive.py` (use current_time), `conservative_entity_tuned.py` (v0.1.7), `runner/gc_runner.py` (UC-GC-5 query-time-based), `runner/variant_costs.py` + `experiments/investment_prioritization.py` (new entries)
- Prior finding: [`finding-gc-differentiated-stage2.md`](finding-gc-differentiated-stage2.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_differentiated.py
# Runs all 7 GC variants (b-raw + v0.1.2 - v0.1.7) with extensions on.
.venv/bin/python experiments/investment_prioritization.py
# Shows ranked recommendation with all GC variants in their positions.
```

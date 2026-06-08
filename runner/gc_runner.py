"""Runner for GC variants against a graph-churn workload.

Applies the event stream to a GraphState, calls the variant's hooks at
the right moments, sweeps at end (and optionally on a cadence during),
and computes the four UC gates:

  UC-GC-1: store-size reduction vs no-GC baseline (higher is better)
  UC-GC-2: retrieval F1 preservation (must not regress vs baseline)
  UC-GC-3: false-collection rate (must stay below 1%)
  UC-GC-4: write-path latency p99 (must stay under 10 ms)

UC-GC-2 needs a baseline run for the comparison; this runner emits
the raw inputs (per-canonical retrieval counts) so the harness can do
the paired comparison upstream.

This is Stage 2 code: synthetic workload, baseline mechanism check.
Real-data integration (Stage 3) and substantial-N benchmarks (Stage 4)
land in separate scripts.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from statistics import median

from fixtures.workloads.w_graph_churn import ChurnWorkload, GraphEvent
from .gc_variants import GCVariant, GraphState


@dataclass
class GCRunResult:
    """One variant's outcome on one workload."""

    variant: str
    n_events: int
    n_nodes_added: int
    n_nodes_collected: int
    n_nodes_at_end: int
    # UC-GC-1: store-size reduction percent vs n_nodes_added
    store_size_reduction_pct: float
    # UC-GC-3: false collections (pinned nodes or expected survivors
    # that got collected); percent of total expected survivors
    n_false_collections: int = 0
    false_collection_rate_pct: float = 0.0
    falsely_collected_ids: list[str] = field(default_factory=list)
    # UC-GC-4: per-event write latency in ms (only add_edge/remove_edge
    # contribute meaningfully; query/pin/add_node are also recorded)
    write_latencies_ms: list[float] = field(default_factory=list)
    write_p50_ms: float = 0.0
    write_p99_ms: float = 0.0
    # Sweep timing
    sweep_seconds: float = 0.0
    # End-of-run retrieval support: count of nodes still present per
    # original entity id; downstream can compute UC-GC-2 by comparing
    # against the b-raw baseline.
    surviving_entity_ids: list[str] = field(default_factory=list)
    # UC-GC-5: tombstone-recovery rate. For workloads with
    # collected_fact_query_targets, what fraction does the variant's
    # was_recently_collected() correctly identify? Non-tombstone
    # variants report 0.
    n_tombstone_query_targets: int = 0
    n_tombstone_recoveries: int = 0
    tombstone_recovery_rate_pct: float = 0.0
    # Multi-tenant accounting (when workload n_tenants > 1)
    n_tenant_pins_applied: int = 0
    n_tenants_swept: int = 0


def _apply_event(event: GraphEvent, state: GraphState) -> None:
    """Mutate `state` according to a single workload event.

    Pure data-mutation. Does NOT call any variant hooks; the runner
    invokes those separately so it can time the hook overhead.
    """
    if event.op == "add_node":
        state.nodes[event.node_id] = {
            "kind": event.node_kind,
            "added_at": event.timestamp,
        }
        state.in_degree.setdefault(event.node_id, 0)
        state.out_degree.setdefault(event.node_id, 0)
        state.last_access.setdefault(event.node_id, event.timestamp)
        state.query_count.setdefault(event.node_id, 0)
    elif event.op == "add_edge":
        key = (event.edge_src, event.edge_dst)
        state.edges[key] = state.edges.get(key, 0) + 1
        # Only count degree on existing nodes (the endpoints may have
        # been collected earlier in the run)
        if event.edge_dst in state.nodes:
            state.in_degree[event.edge_dst] = state.in_degree.get(
                event.edge_dst, 0) + 1
        if event.edge_src in state.nodes:
            state.out_degree[event.edge_src] = state.out_degree.get(
                event.edge_src, 0) + 1
    elif event.op == "remove_edge":
        key = (event.edge_src, event.edge_dst)
        if key in state.edges:
            state.edges[key] = state.edges[key] - 1
            if state.edges[key] <= 0:
                state.edges.pop(key)
                if event.edge_dst in state.in_degree:
                    state.in_degree[event.edge_dst] = max(
                        0, state.in_degree[event.edge_dst] - 1)
                if event.edge_src in state.out_degree:
                    state.out_degree[event.edge_src] = max(
                        0, state.out_degree[event.edge_src] - 1)
    elif event.op == "query":
        if event.node_id in state.nodes:
            state.last_access[event.node_id] = event.timestamp
            state.query_count[event.node_id] = state.query_count.get(
                event.node_id, 0) + 1
    elif event.op == "pin":
        state.pinned.add(event.node_id)
    # query and pin handled above; tenant-aware pin routing happens in
    # run_gc, not here, because it requires the variant reference


def run_gc(
    variant: GCVariant,
    workload: ChurnWorkload,
    sweep_every_n_events: int = 1000,
) -> GCRunResult:
    """Execute the variant on the workload.

    Sweeps happen on a cadence (every sweep_every_n_events) and once at
    the end. The cadence-based sweep is what makes this a "real-time"
    GC; a pure end-only sweep would be a batch collector.

    Multi-tenant support: when the workload has n_tenants > 1 AND the
    variant exposes pin_for_tenant(), pin events with a tenant_id route
    to the variant's tenant-pin API instead of state.pinned. This lets
    v0.1.5 / v0.1.6 demonstrate measurable tenant-scoped behavior.

    Tombstone-recovery (UC-GC-5): for workloads with
    collected_fact_query_targets AND variants with
    was_recently_collected(), the runner counts how many of those
    targets the variant can recover via the tombstone API. Non-
    tombstone variants report 0.
    """
    state = GraphState()
    write_latencies: list[float] = []
    n_nodes_added = 0
    n_nodes_collected = 0
    n_false_collections = 0
    falsely_collected: list[str] = []
    sweep_seconds = 0.0
    last_event_time = 0.0
    n_tenant_pins_applied = 0

    # Detect variant capabilities
    has_tenant_pin = hasattr(variant, "pin_for_tenant")
    has_tombstone = hasattr(variant, "was_recently_collected")

    for i, event in enumerate(workload.events):
        last_event_time = event.timestamp
        t0 = time.perf_counter()
        # Route pin events: if tenant_id is set AND variant supports
        # tenant pinning, use the variant's API instead of state.pinned
        if (event.op == "pin"
                and event.tenant_id is not None
                and has_tenant_pin):
            variant.pin_for_tenant(event.tenant_id, event.node_id)
            n_tenant_pins_applied += 1
        else:
            _apply_event(event, state)
        # Trigger variant hooks
        if event.op == "add_edge":
            variant.on_write_edge(
                event.edge_src, event.edge_dst, state, event.timestamp)
        elif event.op == "remove_edge":
            variant.on_remove_edge(
                event.edge_src, event.edge_dst, state, event.timestamp)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        write_latencies.append(elapsed_ms)
        if event.op == "add_node":
            n_nodes_added += 1

        # Periodic sweep
        if (i + 1) % sweep_every_n_events == 0:
            ts = time.perf_counter()
            for cand_id in variant.collect_candidates(state, event.timestamp):
                if cand_id in workload.expected_survivors:
                    falsely_collected.append(cand_id)
                    n_false_collections += 1
                removed_edges = variant.collect(cand_id, state)
                if cand_id not in state.nodes:
                    n_nodes_collected += 1
            sweep_seconds += time.perf_counter() - ts

    # Final sweep at end
    ts = time.perf_counter()
    for cand_id in variant.collect_candidates(state, last_event_time):
        if cand_id in workload.expected_survivors:
            falsely_collected.append(cand_id)
            n_false_collections += 1
        variant.collect(cand_id, state)
        if cand_id not in state.nodes:
            n_nodes_collected += 1
    sweep_seconds += time.perf_counter() - ts

    write_latencies.sort()
    n = len(write_latencies)
    p50 = write_latencies[n // 2] if n else 0.0
    p99 = write_latencies[min(n - 1, max(0, int(0.99 * n)))] if n else 0.0

    expected_count = len(workload.expected_survivors)
    false_rate = (
        100.0 * n_false_collections / expected_count if expected_count else 0.0
    )

    surviving_entities = sorted(
        nid for nid, n in state.nodes.items() if n.get("kind") == "entity"
    )

    n_added_safe = max(1, n_nodes_added)
    reduction_pct = 100.0 * n_nodes_collected / n_added_safe

    # UC-GC-5: tombstone recovery for collected_fact_query_targets
    n_tombstone_targets = len(workload.collected_fact_query_targets)
    n_tombstone_recoveries = 0
    if has_tombstone and n_tombstone_targets > 0:
        for fid in workload.collected_fact_query_targets:
            # Query at the last_event_time; production code would
            # query at the actual query timestamp
            if variant.was_recently_collected(fid, last_event_time):
                n_tombstone_recoveries += 1
    tombstone_recovery_rate_pct = (
        100.0 * n_tombstone_recoveries / n_tombstone_targets
        if n_tombstone_targets > 0 else 0.0
    )

    # Multi-tenant accounting
    n_tenants_swept = 0
    if has_tenant_pin:
        n_tenants_swept = len(getattr(variant, "tenant_pins", {}))

    return GCRunResult(
        variant=variant.name,
        n_events=len(workload.events),
        n_nodes_added=n_nodes_added,
        n_nodes_collected=n_nodes_collected,
        n_nodes_at_end=len(state.nodes),
        store_size_reduction_pct=reduction_pct,
        n_false_collections=n_false_collections,
        false_collection_rate_pct=false_rate,
        falsely_collected_ids=falsely_collected,
        write_latencies_ms=write_latencies,
        write_p50_ms=p50,
        write_p99_ms=p99,
        sweep_seconds=sweep_seconds,
        surviving_entity_ids=surviving_entities,
        n_tombstone_query_targets=n_tombstone_targets,
        n_tombstone_recoveries=n_tombstone_recoveries,
        tombstone_recovery_rate_pct=tombstone_recovery_rate_pct,
        n_tenant_pins_applied=n_tenant_pins_applied,
        n_tenants_swept=n_tenants_swept,
    )


def compute_uc_gates(
    variant_result: GCRunResult,
    baseline_result: GCRunResult,
    *,
    uc_gc_1_min_reduction_pct: float = 0.0,
    uc_gc_2_min_recall_vs_baseline: float = 0.95,
    uc_gc_3_max_false_rate_pct: float = 1.0,
    uc_gc_4_max_p99_ms: float = 10.0,
    uc_gc_5_min_tombstone_recovery_pct: float = 80.0,
) -> dict[str, dict]:
    """Compute the GC UC gates for a variant vs the no-GC baseline.

    UC-GC-5 (tombstone recovery) only applies when the workload
    activated collected_fact_query_targets. When n_tombstone_query_targets
    is zero, UC-GC-5 reports N/A (status NA).

    Returns dict with one entry per applicable UC: status (PASS/FAIL/NA),
    measured value, threshold, and a brief reason.
    """
    # UC-GC-1: store size reduction
    delta_size_pct = variant_result.store_size_reduction_pct
    uc1_pass = delta_size_pct >= uc_gc_1_min_reduction_pct

    # UC-GC-2: retrieval F1 preservation. Proxy here: surviving-entity
    # recall vs baseline's surviving entities. A more refined Stage 3
    # gate will substitute actual query F1.
    baseline_set = set(baseline_result.surviving_entity_ids)
    variant_set = set(variant_result.surviving_entity_ids)
    if baseline_set:
        recall_vs_baseline = len(variant_set & baseline_set) / len(baseline_set)
    else:
        recall_vs_baseline = 1.0
    uc2_pass = recall_vs_baseline >= uc_gc_2_min_recall_vs_baseline

    # UC-GC-3: false collection rate
    fc_rate = variant_result.false_collection_rate_pct
    uc3_pass = fc_rate <= uc_gc_3_max_false_rate_pct

    # UC-GC-4: write-path latency
    p99 = variant_result.write_p99_ms
    uc4_pass = p99 <= uc_gc_4_max_p99_ms

    # UC-GC-5: tombstone recovery rate (only when workload activated
    # collected_fact_query_targets; otherwise status NA)
    n_targets = variant_result.n_tombstone_query_targets
    tomb_rate = variant_result.tombstone_recovery_rate_pct
    if n_targets == 0:
        uc5_status = "NA"
        uc5_reason = "workload did not activate collected_fact_query_targets"
    else:
        uc5_status = "PASS" if tomb_rate >= uc_gc_5_min_tombstone_recovery_pct else "FAIL"
        uc5_reason = (
            f"recovered {variant_result.n_tombstone_recoveries}/"
            f"{n_targets} ({tomb_rate:.1f}%) via tombstones "
            f"(need >= {uc_gc_5_min_tombstone_recovery_pct}%)"
        )

    return {
        "UC-GC-1": {
            "name": "store-size reduction",
            "value": round(delta_size_pct, 3),
            "threshold": uc_gc_1_min_reduction_pct,
            "status": "PASS" if uc1_pass else "FAIL",
            "reason": f"reduced store by {delta_size_pct:.2f}% (need >= {uc_gc_1_min_reduction_pct}%)",
        },
        "UC-GC-2": {
            "name": "surviving-entity recall vs baseline",
            "value": round(recall_vs_baseline, 4),
            "threshold": uc_gc_2_min_recall_vs_baseline,
            "status": "PASS" if uc2_pass else "FAIL",
            "reason": f"variant kept {recall_vs_baseline:.1%} of baseline's surviving entities (need >= {uc_gc_2_min_recall_vs_baseline:.1%})",
        },
        "UC-GC-3": {
            "name": "false-collection rate",
            "value": round(fc_rate, 3),
            "threshold": uc_gc_3_max_false_rate_pct,
            "status": "PASS" if uc3_pass else "FAIL",
            "reason": f"falsely collected {fc_rate:.2f}% of expected survivors (need <= {uc_gc_3_max_false_rate_pct}%)",
        },
        "UC-GC-4": {
            "name": "write-path p99 latency",
            "value": round(p99, 4),
            "threshold": uc_gc_4_max_p99_ms,
            "status": "PASS" if uc4_pass else "FAIL",
            "reason": f"write p99 {p99:.3f}ms (need <= {uc_gc_4_max_p99_ms}ms)",
        },
        "UC-GC-5": {
            "name": "tombstone recovery rate",
            "value": round(tomb_rate, 3),
            "threshold": uc_gc_5_min_tombstone_recovery_pct,
            "status": uc5_status,
            "reason": uc5_reason,
        },
    }

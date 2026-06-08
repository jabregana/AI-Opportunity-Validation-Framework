"""Stage 4 architectural validation: GC variant through an integration shim.

Replays the Stage 3 real-text workload through the MockGraphStoreShim
(the reference implementation of GCIntegrationShim) instead of running
the variant directly against an in-memory GraphState. Goal: verify
the shim contract is sufficient to host a GCVariant end-to-end, and
that the same UC-GC gate outcomes hold when the variant runs through
the indirection layer.

This is the architectural Stage 4 deliverable. A real Stage 4 (with
Graphiti or Mem0 as the downstream) requires those frameworks to be
installed and configured. The architectural deliverable is the shim
contract being shape-correct and the same numbers reproducing through
the shim path.

A concrete Graphiti or Mem0 shim subclasses GCIntegrationShim and
translates the abstract calls into the downstream's native API
(Cypher queries for Graphiti, vector-store operations for Mem0).
The contract is designed so the variant code does not change at all
between mock and real downstream.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.gc_stage3_real_text import (
    build_alias_map,
    build_workload,
    load_tweets_and_extract,
)
from runner.dimensions.memory.lifecycle import build as build_variant
from runner.dimensions.memory.lifecycle.integrations import (
    MockGraphStoreShim,
)


def run_through_shim(
    variant_id: str,
    workload,
    shim: MockGraphStoreShim,
    *,
    sweep_every_n_events: int = 1000,
) -> dict:
    """Replay the workload through the shim, then have the variant
    sweep the shim's state on a cadence + at the end."""
    variant = build_variant(variant_id)
    events = workload.events
    n_nodes_added = 0
    last_event_t = 0.0

    # Phase 1: pre-pinning. The workload may have pin events; record
    # them through the shim ahead of time so the variant respects them.
    for ev in events:
        if ev.op == "pin":
            shim.pin(ev.node_id)

    # Phase 2: replay the actual events
    sweep_count = 0
    for i, ev in enumerate(events):
        last_event_t = ev.timestamp
        if ev.op == "add_node":
            shim.record_write(ev.node_id, ev.node_kind, None, ev.timestamp)
            n_nodes_added += 1
        elif ev.op == "add_edge":
            shim.record_edge(ev.edge_src, ev.edge_dst, ev.timestamp)
        elif ev.op == "remove_edge":
            shim.record_remove_edge(ev.edge_src, ev.edge_dst, ev.timestamp)
        elif ev.op == "query":
            shim.record_query(ev.node_id, ev.timestamp)
        elif ev.op == "pin":
            pass  # already handled in Phase 1

        # Periodic sweep
        if (i + 1) % sweep_every_n_events == 0:
            state = shim.get_state()
            candidates = variant.collect_candidates(state, ev.timestamp)
            shim.apply_sweep(candidates)
            sweep_count += 1

    # Final sweep
    state = shim.get_state()
    candidates = variant.collect_candidates(state, last_event_t)
    shim.apply_sweep(candidates)
    sweep_count += 1

    final_state = shim.get_state()
    surviving_entities = sorted(
        nid for nid, n in final_state.nodes.items()
        if n.get("kind") == "entity"
    )
    falsely_collected = sorted(
        nid for nid in workload.expected_survivors
        if nid not in final_state.nodes
    )

    stats = shim.stats()
    return {
        "variant": variant_id,
        "shim": shim.name,
        "contract_version": shim.contract_version,
        "n_events": len(events),
        "n_nodes_added": n_nodes_added,
        "n_nodes_at_end": len(final_state.nodes),
        "n_nodes_collected": stats.n_nodes_actually_removed,
        "store_size_reduction_pct": (
            100.0 * stats.n_nodes_actually_removed / max(1, n_nodes_added)
        ),
        "n_surviving_entities": len(surviving_entities),
        "n_falsely_collected": len(falsely_collected),
        "false_collection_rate_pct": (
            100.0 * len(falsely_collected) / max(1, len(workload.expected_survivors))
        ),
        "n_sweeps_invoked": stats.n_sweeps_invoked,
        "n_writes_routed": stats.n_writes,
        "n_edges_added_routed": stats.n_edges_added,
        "n_edges_removed_routed": stats.n_edges_removed,
        "n_queries_routed": stats.n_queries,
    }


def main():
    p = argparse.ArgumentParser(prog="gc-stage4-integration-shim")
    p.add_argument("--per-entity-cap", type=int, default=20)
    p.add_argument("--tick-seconds", type=float, default=600.0)
    p.add_argument("--fact-lifetime-days", type=float, default=7.0)
    p.add_argument("--pin-top-k", type=int, default=5)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    # Build the Stage 3 real-text workload
    alias_map = build_alias_map()
    print(f"Alias map: {len(alias_map)} aliases -> "
          f"{len(set(alias_map.values()))} canonicals")
    print("Loading Twitter Financial News validation split...")
    tweets, entity_freq = load_tweets_and_extract(
        per_entity_cap=args.per_entity_cap, alias_map=alias_map,
    )
    print(f"Loaded {len(tweets)} tweets across "
          f"{sum(1 for v in entity_freq.values() if v > 0)} entities")
    workload = build_workload(
        tweets, entity_freq,
        tick_seconds=args.tick_seconds,
        fact_lifetime_seconds=args.fact_lifetime_days * 86400,
        pin_top_k=args.pin_top_k,
    )
    print(f"Workload: {len(workload.events)} events, "
          f"{workload.n_entities} entities, "
          f"{workload.n_facts} facts, "
          f"{len(workload.pinned_nodes)} pinned, "
          f"{len(workload.expected_survivors)} expected survivors")
    print()

    # Run b-raw-no-gc through the shim (sanity)
    print("--- b-raw-no-gc through MockGraphStoreShim ---")
    b_raw_shim = MockGraphStoreShim()
    t0 = time.perf_counter()
    b_raw_result = run_through_shim("b-raw-no-gc", workload, b_raw_shim)
    print(f"  wall time:          {(time.perf_counter() - t0):.3f} s")
    for k, v in b_raw_result.items():
        if isinstance(v, float):
            print(f"  {k:30} {v:.4f}")
        else:
            print(f"  {k:30} {v}")
    print()

    # Run v0.1.2 through the shim
    print("--- gc-v0.1.2-fact-only through MockGraphStoreShim ---")
    v012_shim = MockGraphStoreShim()
    t0 = time.perf_counter()
    v012_result = run_through_shim("gc-v0.1.2-fact-only", workload, v012_shim)
    print(f"  wall time:          {(time.perf_counter() - t0):.3f} s")
    for k, v in v012_result.items():
        if isinstance(v, float):
            print(f"  {k:30} {v:.4f}")
        else:
            print(f"  {k:30} {v}")
    print()

    # Compare against the Stage 3 direct-path numbers
    print("=" * 72)
    print("Comparison to Stage 3 (direct path, no shim)")
    print("=" * 72)
    print(f"Stage 3 (direct):           store_reduction=84.96%, "
          f"surviving_entities=111, false_collections=0")
    print(f"Stage 4 (through shim):     "
          f"store_reduction={v012_result['store_size_reduction_pct']:.2f}%, "
          f"surviving_entities={v012_result['n_surviving_entities']}, "
          f"false_collections={v012_result['n_falsely_collected']}")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_stage4_shim"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 4 architectural validation (shim contract)",
        "opportunity": "real-time graph GC",
        "downstream_shim": "MockGraphStoreShim (in-memory reference impl)",
        "data_source": "zeroshot/twitter-financial-news-topic (validation split)",
        "workload_params": {
            "per_entity_cap": args.per_entity_cap,
            "tick_seconds": args.tick_seconds,
            "fact_lifetime_days": args.fact_lifetime_days,
            "pin_top_k": args.pin_top_k,
        },
        "workload": {
            "n_events": len(workload.events),
            "n_entities": workload.n_entities,
            "n_facts": workload.n_facts,
            "n_pinned": len(workload.pinned_nodes),
            "n_expected_survivors": len(workload.expected_survivors),
        },
        "variants": {
            "b-raw-no-gc": b_raw_result,
            "gc-v0.1.2-fact-only": v012_result,
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

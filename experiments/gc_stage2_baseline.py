"""Stage 2 baseline benchmark for the graph-GC opportunity.

Runs the three pilot variants (b-raw-no-gc, gc-v0.1.0-ref-count,
gc-v0.1.1-ref-count-utility) on a synthetic graph-churn workload.
Computes UC-GC-1..4 per non-baseline variant against b-raw.

Day 5 of the Stage 2 plan in docs/opportunity-graph-gc.md.

Output: per-variant table on stdout + JSON artifact in
runs/gc_stage2_baseline/<timestamp>.json for the finding doc.
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

from fixtures.workloads.w_graph_churn import generate_churn_workload
from runner.gc_runner import compute_uc_gates, run_gc
from runner.gc_variants import build


VARIANT_IDS = [
    "b-raw-no-gc",
    "gc-v0.1.0-ref-count",
    "gc-v0.1.1-ref-count-utility",
    "gc-v0.1.2-fact-only",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n-entities", type=int, default=50)
    p.add_argument("--n-facts", type=int, default=2000)
    p.add_argument("--fact-lifetime-days", type=float, default=7.0)
    p.add_argument("--pin-fraction", type=float, default=0.10)
    p.add_argument("--query-fraction", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None,
                   help="JSON artifact path (default: runs/gc_stage2_baseline/<ts>.json)")
    args = p.parse_args()

    print("=" * 72)
    print("GC Stage 2 baseline benchmark")
    print("=" * 72)
    print(f"Workload: n_entities={args.n_entities}, n_facts={args.n_facts}, "
          f"fact_lifetime={args.fact_lifetime_days}d, "
          f"pin_fraction={args.pin_fraction}, "
          f"query_fraction={args.query_fraction}, seed={args.seed}")

    workload = generate_churn_workload(
        n_entities=args.n_entities,
        n_facts=args.n_facts,
        fact_lifetime_seconds=args.fact_lifetime_days * 86400,
        pin_fraction=args.pin_fraction,
        query_fraction=args.query_fraction,
        seed=args.seed,
    )
    print(f"Generated {len(workload.events)} events, "
          f"{len(workload.pinned_nodes)} pinned, "
          f"{len(workload.expected_survivors)} expected survivors")
    print()

    results = {}
    timings = {}
    for vid in VARIANT_IDS:
        v = build(vid)
        t0 = time.perf_counter()
        result = run_gc(v, workload)
        elapsed = time.perf_counter() - t0
        results[vid] = result
        timings[vid] = elapsed
        print(f"--- {vid} ---")
        print(f"  events:            {result.n_events}")
        print(f"  nodes added:       {result.n_nodes_added}")
        print(f"  nodes collected:   {result.n_nodes_collected}")
        print(f"  nodes at end:      {result.n_nodes_at_end}")
        print(f"  store reduction:   {result.store_size_reduction_pct:.2f}%")
        print(f"  false collections: {result.n_false_collections} "
              f"({result.false_collection_rate_pct:.3f}% of expected survivors)")
        print(f"  surviving entities:{len(result.surviving_entity_ids)}")
        print(f"  write p50:         {result.write_p50_ms:.4f} ms")
        print(f"  write p99:         {result.write_p99_ms:.4f} ms")
        print(f"  sweep total:       {result.sweep_seconds:.4f} s")
        print(f"  wall time:         {elapsed:.3f} s")
        print()

    baseline = results["b-raw-no-gc"]
    print("=" * 72)
    print("UC gates (vs b-raw-no-gc baseline)")
    print("=" * 72)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_gates(results[vid], baseline)
        gate_results[vid] = gates
        print(f"\n{vid}")
        for uc, info in gates.items():
            mark = "PASS" if info["status"] == "PASS" else "FAIL"
            print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_stage2_baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 baseline",
        "opportunity": "real-time graph GC",
        "workload": {
            "n_entities": args.n_entities,
            "n_facts": args.n_facts,
            "fact_lifetime_days": args.fact_lifetime_days,
            "pin_fraction": args.pin_fraction,
            "query_fraction": args.query_fraction,
            "seed": args.seed,
            "n_events": len(workload.events),
            "n_pinned": len(workload.pinned_nodes),
            "n_expected_survivors": len(workload.expected_survivors),
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_events": r.n_events,
                "n_nodes_added": r.n_nodes_added,
                "n_nodes_collected": r.n_nodes_collected,
                "n_nodes_at_end": r.n_nodes_at_end,
                "store_size_reduction_pct": r.store_size_reduction_pct,
                "n_false_collections": r.n_false_collections,
                "false_collection_rate_pct": r.false_collection_rate_pct,
                "falsely_collected_ids": r.falsely_collected_ids,
                "write_p50_ms": r.write_p50_ms,
                "write_p99_ms": r.write_p99_ms,
                "sweep_seconds": r.sweep_seconds,
                "n_surviving_entities": len(r.surviving_entity_ids),
                "wall_time_seconds": timings[vid],
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

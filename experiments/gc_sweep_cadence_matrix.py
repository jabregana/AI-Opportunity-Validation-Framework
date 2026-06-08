"""Sweep-cadence sensitivity x variant matrix.

Tests how varying sweep_every_n_events affects each GC variant's
metrics, particularly tombstone recovery rate. The hypothesis from
finding-gc-tombstone-api-and-v017.md: tombstone recovery rate (UC-GC-5)
is dominated by the gap between when a query arrives and when the next
sweep creates the tombstone. Smaller cadence = more sweeps = more
tombstones available when queries arrive.

Tests cadences: {10, 50, 100, 500, 1000} events per sweep. Reports
per-(variant, cadence) the store reduction, entity recall, tombstone
recovery, and sweep wall-time.

Goal: find the cadence at which v0.1.3 / v0.1.6 / v0.1.8 hit the
UC-GC-5 80% threshold, and how much extra sweep cost that buys.
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
from runner.gc_runner import run_gc
from runner.gc_variants import build


VARIANT_IDS = [
    "gc-v0.1.2-fact-only",
    "gc-v0.1.3-fact-only-tombstone",
    "gc-v0.1.6-comprehensive",
    "gc-v0.1.8-comprehensive-tuned",
]

CADENCES = [10, 50, 100, 500, 1000]


def main():
    p = argparse.ArgumentParser(prog="gc-sweep-cadence-matrix")
    p.add_argument("--n-entities", type=int, default=50)
    p.add_argument("--n-facts", type=int, default=2000)
    p.add_argument("--total-period-days", type=float, default=120.0)
    p.add_argument("--fact-lifetime-days", type=float, default=7.0)
    p.add_argument("--pin-fraction", type=float, default=0.10)
    p.add_argument("--query-fraction", type=float, default=0.15)
    p.add_argument("--dormant-entity-fraction", type=float, default=0.20)
    p.add_argument("--collected-fact-query-fraction", type=float, default=0.10)
    p.add_argument("--n-tenants", type=int, default=3)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 96)
    print("GC sweep-cadence sensitivity x variant matrix")
    print("=" * 96)
    print(f"Workload: n_entities={args.n_entities}, n_facts={args.n_facts}, "
          f"total_period_days={args.total_period_days}")
    print(f"Extensions: dormant={args.dormant_entity_fraction}, "
          f"post-collection queries={args.collected_fact_query_fraction}, "
          f"tenants={args.n_tenants}")

    workload = generate_churn_workload(
        n_entities=args.n_entities,
        n_facts=args.n_facts,
        fact_lifetime_seconds=args.fact_lifetime_days * 86400,
        pin_fraction=args.pin_fraction,
        query_fraction=args.query_fraction,
        seed=args.seed,
        total_period_days=args.total_period_days,
        n_tenants=args.n_tenants,
        dormant_entity_fraction=args.dormant_entity_fraction,
        collected_fact_query_fraction=args.collected_fact_query_fraction,
    )
    print(f"Generated {len(workload.events)} events, "
          f"{len(workload.collected_fact_query_targets)} tombstone targets")
    print()

    # Matrix: (variant, cadence) -> result summary
    results: dict[tuple[str, int], dict] = {}
    for vid in VARIANT_IDS:
        for cadence in CADENCES:
            v = build(vid)
            t0 = time.perf_counter()
            r = run_gc(v, workload, sweep_every_n_events=cadence)
            elapsed = time.perf_counter() - t0
            results[(vid, cadence)] = {
                "store_reduction_pct": r.store_size_reduction_pct,
                "n_surviving_entities": len(r.surviving_entity_ids),
                "n_false_collections": r.n_false_collections,
                "tombstone_recovery_rate_pct": r.tombstone_recovery_rate_pct,
                "n_tombstone_recoveries": r.n_tombstone_recoveries,
                "sweep_seconds": r.sweep_seconds,
                "wall_time_seconds": elapsed,
            }

    # Print: tombstone recovery rate matrix (the headline)
    print("=" * 96)
    print("UC-GC-5 tombstone recovery rate by (variant, cadence)")
    print("(threshold: 80%; goal: find cadence where each tombstone variant passes)")
    print("=" * 96)
    print(f"{'variant':<40} " + " ".join(f"cad={c:>4}" for c in CADENCES))
    for vid in VARIANT_IDS:
        row = [
            f"{results[(vid, c)]['tombstone_recovery_rate_pct']:>6.1f}%"
            for c in CADENCES
        ]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # Sweep wall-time matrix (the cost of finer cadence)
    print("=" * 96)
    print("Sweep total wall-time (seconds) by (variant, cadence)")
    print("=" * 96)
    print(f"{'variant':<40} " + " ".join(f"cad={c:>4}" for c in CADENCES))
    for vid in VARIANT_IDS:
        row = [
            f"{results[(vid, c)]['sweep_seconds']:>6.3f}"
            for c in CADENCES
        ]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # Store reduction matrix (should be roughly constant per variant)
    print("=" * 96)
    print("Store reduction % by (variant, cadence)")
    print("=" * 96)
    print(f"{'variant':<40} " + " ".join(f"cad={c:>4}" for c in CADENCES))
    for vid in VARIANT_IDS:
        row = [
            f"{results[(vid, c)]['store_reduction_pct']:>6.2f}%"
            for c in CADENCES
        ]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # Surviving entities (v0.1.4 / v0.1.6 vs others)
    print("=" * 96)
    print("Surviving entities by (variant, cadence)")
    print("=" * 96)
    print(f"{'variant':<40} " + " ".join(f"cad={c:>4}" for c in CADENCES))
    for vid in VARIANT_IDS:
        row = [
            f"{results[(vid, c)]['n_surviving_entities']:>6d}"
            for c in CADENCES
        ]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # Findings: cadences at which each tombstone variant first hits 80%
    print("=" * 96)
    print("Lowest cadence achieving UC-GC-5 threshold (80%) per variant")
    print("=" * 96)
    for vid in VARIANT_IDS:
        passing = [
            c for c in CADENCES
            if results[(vid, c)]["tombstone_recovery_rate_pct"] >= 80.0
        ]
        if passing:
            best_c = max(passing)  # largest cadence that still passes
            print(f"  {vid}: passes at cadence <= {best_c}")
        else:
            best_rate = max(
                results[(vid, c)]["tombstone_recovery_rate_pct"]
                for c in CADENCES
            )
            print(f"  {vid}: does NOT pass at any tested cadence; best {best_rate:.1f}%")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_sweep_cadence_matrix"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "GC sweep-cadence sensitivity x variant matrix",
        "cadences_tested": CADENCES,
        "workload_params": {
            "n_entities": args.n_entities,
            "n_facts": args.n_facts,
            "total_period_days": args.total_period_days,
            "fact_lifetime_days": args.fact_lifetime_days,
            "pin_fraction": args.pin_fraction,
            "query_fraction": args.query_fraction,
            "dormant_entity_fraction": args.dormant_entity_fraction,
            "collected_fact_query_fraction": args.collected_fact_query_fraction,
            "n_tenants": args.n_tenants,
            "seed": args.seed,
        },
        "results": {
            f"{vid}|{c}": r
            for (vid, c), r in results.items()
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

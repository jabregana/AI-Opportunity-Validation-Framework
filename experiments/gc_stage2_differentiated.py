"""Differentiated Stage 2 benchmark for GC variant evolution.

Same shape as gc_stage2_baseline.py but with the workload extensions
ACTIVATED so v0.1.3 / v0.1.4 / v0.1.5 / v0.1.6 show measurable
differentiation from v0.1.2.

Activated extensions:
  total_period_days = 120                  (v0.1.4's 60-day-unaccessed
                                            threshold can fire)
  dormant_entity_fraction = 0.20           (some entities receive zero
                                            queries; v0.1.4 should
                                            collect them after dormancy)
  collected_fact_query_fraction = 0.10     (10% of facts queried after
                                            collection; v0.1.3 / v0.1.6
                                            tombstones should recover)
  n_tenants = 3                            (some pin events carry
                                            tenant_id; v0.1.5 / v0.1.6
                                            route them to per-tenant
                                            pin sets)

This is the natural Stage 2 revision proposed in
finding-gc-v016-and-workload-extensions.md.
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
    "gc-v0.1.2-fact-only",
    "gc-v0.1.3-fact-only-tombstone",
    "gc-v0.1.4-conservative-entity-plus-fact",
    "gc-v0.1.5-fact-only-tenant-pinning",
    "gc-v0.1.6-comprehensive",
    "gc-v0.1.7-conservative-entity-tuned",
]


def main():
    p = argparse.ArgumentParser(prog="gc-stage2-differentiated")
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

    print("=" * 78)
    print("GC Stage 2 DIFFERENTIATED benchmark (extensions activated)")
    print("=" * 78)
    print(f"Workload: n_entities={args.n_entities}, n_facts={args.n_facts}, "
          f"total_period_days={args.total_period_days}, "
          f"fact_lifetime={args.fact_lifetime_days}d")
    print(f"Extensions: n_tenants={args.n_tenants}, "
          f"dormant_entity_fraction={args.dormant_entity_fraction}, "
          f"collected_fact_query_fraction={args.collected_fact_query_fraction}")

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
          f"{len(workload.pinned_nodes)} global-pinned, "
          f"{len(workload.dormant_entity_ids)} dormant entities, "
          f"{len(workload.collected_fact_query_targets)} collected-fact-query targets, "
          f"{len(workload.tenant_assignments)} tenant assignments")
    print()

    results = {}
    for vid in VARIANT_IDS:
        v = build(vid)
        t0 = time.perf_counter()
        r = run_gc(v, workload)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        print(f"--- {vid} ---")
        print(f"  nodes added:           {r.n_nodes_added}")
        print(f"  nodes collected:       {r.n_nodes_collected}")
        print(f"  store reduction:       {r.store_size_reduction_pct:.2f}%")
        print(f"  surviving entities:    {len(r.surviving_entity_ids)}")
        print(f"  false collections:     {r.n_false_collections}")
        print(f"  tombstone targets:     {r.n_tombstone_query_targets}")
        print(f"  tombstone recoveries:  {r.n_tombstone_recoveries}")
        print(f"  tombstone rec rate:    {r.tombstone_recovery_rate_pct:.1f}%")
        print(f"  tenant pins applied:   {r.n_tenant_pins_applied}")
        print(f"  tenants swept:         {r.n_tenants_swept}")
        print(f"  wall time:             {elapsed:.3f} s")
        print()

    baseline = results["b-raw-no-gc"]
    print("=" * 78)
    print("UC-GC gates (vs b-raw-no-gc baseline; UC-GC-5 NEW for tombstone)")
    print("=" * 78)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_gates(results[vid], baseline)
        gate_results[vid] = gates
        n_pass = sum(1 for g in gates.values() if g["status"] == "PASS")
        n_na = sum(1 for g in gates.values() if g["status"] == "NA")
        n_fail = sum(1 for g in gates.values() if g["status"] == "FAIL")
        print(f"\n{vid}  ({n_pass} PASS, {n_fail} FAIL, {n_na} NA)")
        for uc, info in gates.items():
            mark = info["status"]
            print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    # Differentiation summary
    print()
    print("=" * 78)
    print("DIFFERENTIATION SUMMARY")
    print("=" * 78)
    print(f"{'variant':<42} {'reduction%':>10} {'recall%':>9} "
          f"{'tomb-rec%':>10} {'tenant-pins':>11}")
    for vid in VARIANT_IDS:
        r = results[vid]
        # Entity recall against baseline
        b_entities = set(baseline.surviving_entity_ids)
        v_entities = set(r.surviving_entity_ids)
        recall = (100.0 * len(v_entities & b_entities) / len(b_entities)
                  if b_entities else 100.0)
        print(f"{vid:<42} {r.store_size_reduction_pct:>9.2f}% "
              f"{recall:>8.1f}% "
              f"{r.tombstone_recovery_rate_pct:>9.1f}% "
              f"{r.n_tenant_pins_applied:>11d}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_stage2_differentiated"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 differentiated",
        "opportunity": "real-time graph GC",
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
            "n_events": len(workload.events),
            "n_dormant_entities": len(workload.dormant_entity_ids),
            "n_collected_fact_query_targets": len(workload.collected_fact_query_targets),
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_nodes_added": r.n_nodes_added,
                "n_nodes_collected": r.n_nodes_collected,
                "n_nodes_at_end": r.n_nodes_at_end,
                "store_size_reduction_pct": r.store_size_reduction_pct,
                "n_false_collections": r.n_false_collections,
                "n_surviving_entities": len(r.surviving_entity_ids),
                "tombstone_recovery_rate_pct": r.tombstone_recovery_rate_pct,
                "n_tombstone_query_targets": r.n_tombstone_query_targets,
                "n_tombstone_recoveries": r.n_tombstone_recoveries,
                "n_tenant_pins_applied": r.n_tenant_pins_applied,
                "n_tenants_swept": r.n_tenants_swept,
                "write_p99_ms": r.write_p99_ms,
                "sweep_seconds": r.sweep_seconds,
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

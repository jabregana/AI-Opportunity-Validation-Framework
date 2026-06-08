"""Long-running GC simulation: compressed 30/60/90-day accumulation.

Phase 2 deliverable of the synthesis plan: produce the marketing-grade
growth curves the analyst named ("How fast does memory grow? How much
does GC reduce growth? How much retrieval quality changes?").

A real 30/60/90 day deployment requires waiting 30/60/90 calendar days
on a real workload. This script COMPRESSES that into wall-clock minutes
by simulating realistic daily memory churn.

Output: time-series data + (optionally) ASCII / matplotlib plots showing
memory growth without GC vs with v0.1.8 GC across the simulated period.

Plug into a real Mem0 / Graphiti / Cognee deployment via the
mem0_smoke_test_real_llm.py / graphiti_smoke_test_real_llm.py scripts
for ACTUAL 30-day data once you have a deployment to instrument.
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
from runner.dimensions.memory.lifecycle import FACTORIES
from runner.gc_runner import run_gc


# Realistic per-day rates (tuned to a B2B SaaS-shaped product)
DEFAULT_MEMORIES_PER_DAY = 100
DEFAULT_QUERIES_PER_DAY = 30
DEFAULT_PINNED_FRACTION = 0.05


def _sample_growth_curve(
    n_days: int,
    memories_per_day: int,
    variant_id: str | None,
    seed: int = 42,
) -> list[dict]:
    """Run the simulation. Returns one row per day with the metrics.

    variant_id=None means "no GC" (baseline). When set, runs with the
    named variant + sweep every day.
    """
    n_total_facts = memories_per_day * n_days
    workload = generate_churn_workload(
        n_entities=int(memories_per_day * 0.2),  # 20% of daily memories are entity-shaped
        n_facts=n_total_facts,
        fact_lifetime_seconds=7 * 86400,  # facts age out after 1 week
        pin_fraction=DEFAULT_PINNED_FRACTION,
        query_fraction=DEFAULT_QUERIES_PER_DAY / memories_per_day,
        seed=seed,
        total_period_days=float(n_days),
        n_tenants=3,
        dormant_entity_fraction=0.10,
        collected_fact_query_fraction=0.05,
    )

    # If no variant (baseline = no-GC), just count nodes at end of each day
    if variant_id is None:
        variant_id = "b-raw-no-gc"

    variant_cls = FACTORIES[variant_id]
    try:
        variant = variant_cls(min_age_seconds=86400.0)  # 1 day for realism
    except TypeError:
        variant = variant_cls()

    # Synthesize per-day snapshots by truncating events to that day
    rows: list[dict] = []
    for day in range(1, n_days + 1):
        cutoff = day * 86400.0
        events_so_far = [e for e in workload.events if e.timestamp <= cutoff]
        # Build a tiny workload snapshot for run_gc to consume
        from fixtures.workloads.w_graph_churn import ChurnWorkload
        snapshot = ChurnWorkload(
            events=events_so_far,
            pinned_nodes=workload.pinned_nodes,
            expected_survivors=workload.expected_survivors,
            n_entities=workload.n_entities,
            n_facts=workload.n_facts,
            n_tenants=workload.n_tenants,
            tenant_assignments=workload.tenant_assignments,
            dormant_entity_ids=workload.dormant_entity_ids,
            collected_fact_query_targets=workload.collected_fact_query_targets,
        )
        # Fresh variant per day (the simulator runs the full history each day;
        # in production, the variant maintains state continuously, which is
        # more efficient. This simulation overcounts wall-time but the
        # per-day node counts are correct).
        try:
            v = variant_cls(min_age_seconds=86400.0)
        except TypeError:
            v = variant_cls()
        result = run_gc(v, snapshot, sweep_every_n_events=100)
        rows.append({
            "day": day,
            "variant": variant.name,
            "n_events_so_far": len(events_so_far),
            "n_nodes_added_cumulative": result.n_nodes_added,
            "n_nodes_collected_cumulative": result.n_nodes_collected,
            "n_nodes_at_end_of_day": result.n_nodes_at_end,
            "store_reduction_pct": result.store_size_reduction_pct,
            "surviving_entities": len(result.surviving_entity_ids),
        })
    return rows


def main():
    p = argparse.ArgumentParser(prog="gc-long-running-simulation")
    p.add_argument("--n-days", type=int, default=30,
                   help="Simulated period in days (default 30)")
    p.add_argument("--memories-per-day", type=int,
                   default=DEFAULT_MEMORIES_PER_DAY,
                   help="Synthetic memory creation rate (default 100/day)")
    p.add_argument("--variants", default="b-raw-no-gc,gc-v0.1.2-fact-only,gc-v0.1.8-comprehensive-tuned",
                   help="Comma-separated variants to compare")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print(f"GC long-running simulation ({args.n_days} simulated days)")
    print("=" * 78)
    print(f"Memories/day:  {args.memories_per_day}")
    print(f"Variants:      {args.variants}")
    print()

    variant_ids = [v.strip() for v in args.variants.split(",") if v.strip()]
    series: dict[str, list[dict]] = {}
    for vid in variant_ids:
        print(f"  Running {vid}...")
        t0 = time.time()
        series[vid] = _sample_growth_curve(
            n_days=args.n_days,
            memories_per_day=args.memories_per_day,
            variant_id=vid if vid != "b-raw-no-gc" else None,
            seed=args.seed,
        )
        print(f"    done in {time.time()-t0:.1f}s")
    print()

    # ASCII growth curve at key days
    print("=" * 78)
    print("Memory store size by day (no-GC vs with-GC)")
    print("=" * 78)
    headers = ["day"] + variant_ids
    print(" | ".join(h[:30] for h in headers))
    for day in [1, 7, 14, 21, args.n_days]:
        if day > args.n_days:
            continue
        row = [str(day)]
        for vid in variant_ids:
            v_rows = series.get(vid, [])
            v_data = next((r for r in v_rows if r["day"] == day), None)
            row.append(str(v_data["n_nodes_at_end_of_day"]) if v_data else "?")
        print(" | ".join(c[:30] for c in row))
    print()

    # Reductions vs baseline
    if "b-raw-no-gc" in series:
        baseline_final = series["b-raw-no-gc"][-1]["n_nodes_at_end_of_day"]
        print(f"Baseline ({args.n_days}-day no-GC store size): {baseline_final}")
        for vid in variant_ids:
            if vid == "b-raw-no-gc":
                continue
            final = series[vid][-1]["n_nodes_at_end_of_day"]
            reduction = 100 * (baseline_final - final) / max(1, baseline_final)
            print(f"  {vid}: final size {final} ({reduction:.1f}% reduction)")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_long_running_simulation"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": f"GC long-running simulation ({args.n_days} days)",
        "n_days": args.n_days,
        "memories_per_day": args.memories_per_day,
        "variants": variant_ids,
        "seed": args.seed,
        "series": series,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

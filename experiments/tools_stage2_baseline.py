"""Stage 2 baseline benchmark for the tools dimension.

Runs the three pilot variants on the synthetic tool-selection workload.
Computes UC-TOOL-1..4 for each non-baseline variant against b-allow-all.

Day 5 of the Tools Stage 2 plan in docs/opportunity-tools.md.
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

from fixtures.workloads.w_tool_selection import (
    generate_tool_selection_workload,
)
from runner.dimensions.tools import build as build_tool_variant
from runner.tool_runner import compute_uc_tool_gates, run_tools


VARIANT_IDS = [
    "b-allow-all-tools",
    "tool-v0.1.0-budget-bucketed",
    "tool-v0.1.1-intent-classified",
    "tool-v0.1.2-intent-plus-helper",
]


def main():
    p = argparse.ArgumentParser(prog="tools-stage2-baseline")
    p.add_argument("--n-tasks", type=int, default=300)
    p.add_argument("--cross-category-chance", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 72)
    print("Tools Stage 2 baseline benchmark")
    print("=" * 72)
    print(f"Workload: n_tasks={args.n_tasks}, "
          f"cross_category_chance={args.cross_category_chance}, "
          f"seed={args.seed}")

    workload = generate_tool_selection_workload(
        n_tasks=args.n_tasks,
        cross_category_chance=args.cross_category_chance,
        seed=args.seed,
    )
    print(f"Generated {workload.n_tasks} tasks, "
          f"tool_universe={len(workload.tool_universe)}, "
          f"avg_required_per_task={workload.avg_required_per_task:.2f}")
    print()

    results = {}
    for vid in VARIANT_IDS:
        v = build_tool_variant(vid)
        t0 = time.perf_counter()
        r = run_tools(v, workload, seed=args.seed)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        print(f"--- {vid} ---")
        print(f"  tasks:                 {r.n_tasks}")
        print(f"  completed:             {r.n_completed}")
        print(f"  missing required:      {r.n_missing_required}")
        print(f"  selection failed:      {r.n_selection_failed}")
        print(f"  completion rate:       {r.completion_rate_pct:.2f}%")
        print(f"  avg exposed/task:      {r.avg_exposed_per_task:.2f}")
        print(f"  avg required/task:     {r.avg_required_per_task:.2f}")
        print(f"  selection precision:   {r.selection_precision_pct:.2f}%")
        print(f"  selection recall:      {r.selection_recall_pct:.2f}%")
        print(f"  cost/completion:       {r.cost_per_completion:.1f}")
        print(f"  latency p50/p99:       {r.latency_p50:.3f}/{r.latency_p99:.3f}")
        print(f"  wall time:             {elapsed:.3f} s")
        print()

    baseline = results["b-allow-all-tools"]
    print("=" * 72)
    print("UC-TOOL gates (vs b-allow-all-tools baseline)")
    print("=" * 72)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_tool_gates(results[vid], baseline)
        gate_results[vid] = gates
        print(f"\n{vid}")
        for uc, info in gates.items():
            mark = "PASS" if info["status"] == "PASS" else "FAIL"
            print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "tools_stage2_baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 baseline",
        "opportunity": "agent tool-set composition benchmark",
        "workload_params": {
            "n_tasks": args.n_tasks,
            "cross_category_chance": args.cross_category_chance,
            "seed": args.seed,
            "tool_universe_size": len(workload.tool_universe),
            "avg_required_per_task": workload.avg_required_per_task,
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_tasks": r.n_tasks,
                "n_completed": r.n_completed,
                "n_missing_required": r.n_missing_required,
                "n_selection_failed": r.n_selection_failed,
                "completion_rate_pct": r.completion_rate_pct,
                "avg_exposed_per_task": r.avg_exposed_per_task,
                "avg_required_per_task": r.avg_required_per_task,
                "selection_precision_pct": r.selection_precision_pct,
                "selection_recall_pct": r.selection_recall_pct,
                "total_cost": r.total_cost,
                "cost_per_completion": r.cost_per_completion,
                "latency_p50": r.latency_p50,
                "latency_p99": r.latency_p99,
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

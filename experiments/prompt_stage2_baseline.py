"""Stage 2 baseline benchmark for the prompt dimension.

Runs all six prompt strategy variants on the synthetic prompt-task
workload. Computes UC-PROMPT-1..4 for each non-baseline variant
against b-default-prompt.

Day 5 of the Prompt Stage 2 plan in docs/opportunity-prompt.md.
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

from fixtures.workloads.w_prompt_tasks import (
    generate_prompt_task_workload,
)
from runner.dimensions.prompt import build as build_prompt_variant
from runner.prompt_runner import compute_uc_prompt_gates, run_prompt


VARIANT_IDS = [
    "b-default-prompt",
    "prompt-v0.1.0-cot",
    "prompt-v0.1.1-direct-structured",
    "prompt-v0.1.2-few-shot-1",
    "prompt-v0.1.3-few-shot-3",
    "prompt-v0.1.4-cot-plus-structured",
]


def main():
    p = argparse.ArgumentParser(prog="prompt-stage2-baseline")
    p.add_argument("--n-tasks", type=int, default=400)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 72)
    print("Prompt Stage 2 baseline benchmark")
    print("=" * 72)
    print(f"Workload: n_tasks={args.n_tasks}, seed={args.seed}")

    workload = generate_prompt_task_workload(
        n_tasks=args.n_tasks, seed=args.seed,
    )
    print(f"Generated {workload.n_tasks} tasks")
    print(f"By category: {workload.by_category}")
    print(f"By difficulty: {workload.by_difficulty}")
    print()

    results = {}
    for vid in VARIANT_IDS:
        v = build_prompt_variant(vid)
        t0 = time.perf_counter()
        r = run_prompt(v, workload, seed=args.seed)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        print(f"--- {vid} ---")
        print(f"  completion rate:      {r.completion_rate_pct:.2f}%")
        print(f"  avg prompt tokens:    {r.avg_prompt_tokens:.1f}")
        print(f"  cost/completion:      {r.cost_per_completion:.1f}")
        print(f"  latency p50/p99:      {r.latency_p50:.1f}/{r.latency_p99:.1f}")
        print(f"  category completion:")
        for cat in sorted(r.by_category_completion_pct):
            print(f"    {cat:<15} {r.by_category_completion_pct[cat]:.1f}%")
        print(f"  cat variance:         {r.category_completion_variance:.2f}")
        print(f"  wall time:            {elapsed:.3f} s")
        print()

    baseline = results["b-default-prompt"]
    print("=" * 72)
    print("UC-PROMPT gates (vs b-default-prompt baseline)")
    print("=" * 72)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_prompt_gates(results[vid], baseline)
        gate_results[vid] = gates
        n_pass = sum(1 for g in gates.values() if g["status"] == "PASS")
        print(f"\n{vid}  ({n_pass}/4 PASS)")
        for uc, info in gates.items():
            mark = "PASS" if info["status"] == "PASS" else "FAIL"
            print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "prompt_stage2_baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 baseline",
        "opportunity": "agent prompt strategy benchmark",
        "workload_params": {
            "n_tasks": args.n_tasks,
            "seed": args.seed,
            "by_category": workload.by_category,
            "by_difficulty": workload.by_difficulty,
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_tasks": r.n_tasks,
                "n_completed": r.n_completed,
                "completion_rate_pct": r.completion_rate_pct,
                "by_category_completion_pct": r.by_category_completion_pct,
                "by_difficulty_completion_pct": r.by_difficulty_completion_pct,
                "total_cost": r.total_cost,
                "cost_per_completion": r.cost_per_completion,
                "avg_prompt_tokens": r.avg_prompt_tokens,
                "latency_p50": r.latency_p50,
                "latency_p99": r.latency_p99,
                "category_completion_variance": r.category_completion_variance,
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

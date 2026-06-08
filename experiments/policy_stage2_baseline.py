"""Stage 2 baseline benchmark for the execution-policy dimension.

Runs all five policy variants on the synthetic policy-task workload.
Computes UC-POLICY-1..4 for each non-baseline variant against
b-single-shot-policy.

Day 5 of the Policy Stage 2 plan in docs/opportunity-policy.md.
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

from fixtures.workloads.w_policy_tasks import generate_policy_task_workload
from runner.dimensions.policy import build as build_policy_variant
from runner.policy_runner import compute_uc_policy_gates, run_policy


VARIANT_IDS = [
    "b-single-shot-policy",
    "policy-v0.1.0-react",
    "policy-v0.1.1-plan-execute",
    "policy-v0.1.2-reflect-loop",
    "policy-v0.1.3-handoff",
]


def main():
    p = argparse.ArgumentParser(prog="policy-stage2-baseline")
    p.add_argument("--n-tasks", type=int, default=400)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 72)
    print("Policy Stage 2 baseline benchmark")
    print("=" * 72)
    print(f"Workload: n_tasks={args.n_tasks}, seed={args.seed}")

    workload = generate_policy_task_workload(
        n_tasks=args.n_tasks, seed=args.seed,
    )
    print(f"Generated {workload.n_tasks} tasks")
    print(f"By class: {workload.by_class}")
    print(f"By difficulty: {workload.by_difficulty}")
    print()

    results = {}
    for vid in VARIANT_IDS:
        v = build_policy_variant(vid)
        t0 = time.perf_counter()
        r = run_policy(v, workload, seed=args.seed)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        print(f"--- {vid} ---")
        print(f"  completion rate:      {r.completion_rate_pct:.2f}%")
        print(f"  avg steps/task:       {r.avg_steps_per_task:.2f}")
        print(f"  max steps:            {r.max_steps_seen}")
        print(f"  cost/completion:      {r.cost_per_completion:.2f}")
        print(f"  latency p50/p99:      {r.latency_p50:.1f}/{r.latency_p99:.1f}")
        print(f"  by class completion:")
        for c in sorted(r.by_class_completion_pct):
            print(f"    {c:<20} {r.by_class_completion_pct[c]:.1f}%")
        print(f"  wall time:            {elapsed:.3f} s")
        print()

    baseline = results["b-single-shot-policy"]
    print("=" * 72)
    print("UC-POLICY gates (vs b-single-shot-policy baseline)")
    print("=" * 72)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_policy_gates(results[vid], baseline)
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
        out_dir = ROOT / "runs" / "policy_stage2_baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 baseline",
        "opportunity": "agent execution-policy benchmark",
        "workload_params": {
            "n_tasks": args.n_tasks,
            "seed": args.seed,
            "by_class": workload.by_class,
            "by_difficulty": workload.by_difficulty,
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_tasks": r.n_tasks,
                "n_completed": r.n_completed,
                "completion_rate_pct": r.completion_rate_pct,
                "avg_steps_per_task": r.avg_steps_per_task,
                "max_steps_seen": r.max_steps_seen,
                "total_cost": r.total_cost,
                "cost_per_completion": r.cost_per_completion,
                "latency_p50": r.latency_p50,
                "latency_p99": r.latency_p99,
                "by_class_completion_pct": r.by_class_completion_pct,
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

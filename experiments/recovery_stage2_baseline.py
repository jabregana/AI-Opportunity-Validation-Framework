"""Stage 2 baseline benchmark for the recovery dimension.

Runs the three pilot variants (b-abort, retry-with-backoff,
fallback-chain) on the synthetic failure-injection workload. Computes
UC-REC-1..4 for each non-baseline variant against b-abort.

Day 5 of the Stage 2 plan in docs/opportunity-recovery.md.

Output: per-variant table on stdout + JSON artifact in
runs/recovery_stage2_baseline/<timestamp>.json.
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

from fixtures.workloads.w_failure_injection import (
    generate_failure_injection_workload,
)
from runner.dimensions.recovery import build as build_recovery_variant
from runner.recovery_runner import compute_uc_rec_gates, run_recovery


VARIANT_IDS = [
    "b-abort-on-failure",
    "recovery-v0.1.0-retry-with-backoff",
    "recovery-v0.1.1-fallback-chain",
]


def main():
    p = argparse.ArgumentParser(prog="recovery-stage2-baseline")
    p.add_argument("--n-scenarios", type=int, default=500)
    p.add_argument("--failure-rate", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 72)
    print("Recovery Stage 2 baseline benchmark")
    print("=" * 72)
    print(f"Workload: n_scenarios={args.n_scenarios}, "
          f"failure_rate={args.failure_rate}, seed={args.seed}")

    workload = generate_failure_injection_workload(
        n_scenarios=args.n_scenarios,
        failure_rate=args.failure_rate,
        seed=args.seed,
    )
    print(f"Generated {workload.n_scenarios} scenarios, "
          f"{workload.n_scenarios_with_failure} with injected failures")
    print(f"Failure distribution: {workload.failure_distribution}")
    print()

    results = {}
    for vid in VARIANT_IDS:
        v = build_recovery_variant(vid)
        t0 = time.perf_counter()
        r = run_recovery(v, workload, seed=args.seed)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        print(f"--- {vid} ---")
        print(f"  scenarios:        {r.n_scenarios}")
        print(f"  completed:        {r.n_completed}")
        print(f"  aborted:          {r.n_aborted}")
        print(f"  completion rate:  {r.completion_rate_pct:.2f}%")
        print(f"  total cost:       {r.total_cost:.1f}")
        print(f"  cost/completion:  {r.cost_per_completion:.3f}")
        print(f"  latency p50:      {r.latency_p50_steps:.1f} steps")
        print(f"  latency p99:      {r.latency_p99_steps:.1f} steps")
        print(f"  max attempts:     {r.max_attempts_seen}")
        print(f"  action counts:    {r.action_kind_counts}")
        print(f"  by kind:")
        for kind, info in sorted(r.completion_by_failure_kind.items()):
            rate = 100.0 * info["n_completed"] / max(1, info["n_scenarios"])
            print(f"    {kind:22} {info['n_completed']:4d}/{info['n_scenarios']:4d} "
                  f"({rate:.1f}%)")
        print(f"  wall time:        {elapsed:.3f} s")
        print()

    baseline = results["b-abort-on-failure"]
    print("=" * 72)
    print("UC-REC gates (vs b-abort-on-failure baseline)")
    print("=" * 72)
    gate_results = {}
    for vid in VARIANT_IDS[1:]:
        gates = compute_uc_rec_gates(results[vid], baseline)
        gate_results[vid] = gates
        print(f"\n{vid}")
        for uc, info in gates.items():
            mark = "PASS" if info["status"] == "PASS" else "FAIL"
            print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "recovery_stage2_baseline"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 2 baseline",
        "opportunity": "agent recovery policy benchmark",
        "workload_params": {
            "n_scenarios": args.n_scenarios,
            "failure_rate": args.failure_rate,
            "seed": args.seed,
            "n_scenarios_with_failure": workload.n_scenarios_with_failure,
            "failure_distribution": workload.failure_distribution,
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_scenarios": r.n_scenarios,
                "n_completed": r.n_completed,
                "n_aborted": r.n_aborted,
                "completion_rate_pct": r.completion_rate_pct,
                "total_cost": r.total_cost,
                "cost_per_completion": r.cost_per_completion,
                "latency_p50_steps": r.latency_p50_steps,
                "latency_p99_steps": r.latency_p99_steps,
                "max_attempts_seen": r.max_attempts_seen,
                "action_kind_counts": r.action_kind_counts,
                "completion_by_failure_kind": r.completion_by_failure_kind,
            }
            for vid, r in results.items()
        },
        "uc_gates": gate_results,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

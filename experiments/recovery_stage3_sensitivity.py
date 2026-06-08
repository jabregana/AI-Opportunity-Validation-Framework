"""Stage 3 sensitivity analysis for the recovery dimension.

Runs the Stage 2 benchmark under five plausible probability tables
(optimistic, pessimistic, small-model, large-model, hostile) and
reports whether the UC-REC verdicts hold across all of them. The
goal: show whether the Stage 2 PASS verdicts are robust to the hard-
coded simulation choices or whether they depend on a specific table.

This is Stage 3-lite: same synthetic workload, different probability
parameterizations. Real-LLM-trace Stage 3 is deferred until LLM-trace
collection infrastructure exists; see the finding doc for what that
would change.
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
from runner.recovery_runner import (
    P_RESOLVE_TABLES,
    compute_uc_rec_gates,
    run_recovery,
)


VARIANT_IDS = [
    "b-abort-on-failure",
    "recovery-v0.1.0-retry-with-backoff",
    "recovery-v0.1.1-fallback-chain",
]


def main():
    p = argparse.ArgumentParser(prog="recovery-stage3-sensitivity")
    p.add_argument("--n-scenarios", type=int, default=500)
    p.add_argument("--failure-rate", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Recovery Stage 3 sensitivity analysis")
    print("=" * 78)
    print(f"Workload: n_scenarios={args.n_scenarios}, "
          f"failure_rate={args.failure_rate}, seed={args.seed}")
    print(f"Probability tables: {sorted(P_RESOLVE_TABLES.keys())}")

    workload = generate_failure_injection_workload(
        n_scenarios=args.n_scenarios,
        failure_rate=args.failure_rate,
        seed=args.seed,
    )
    print(f"Generated {workload.n_scenarios} scenarios, "
          f"{workload.n_scenarios_with_failure} with injected failures")
    print()

    # Per-table results: table_name -> variant_id -> RecoveryRunResult
    all_results: dict[str, dict] = {}
    for table_name, p_table in P_RESOLVE_TABLES.items():
        all_results[table_name] = {}
        for vid in VARIANT_IDS:
            v = build_recovery_variant(vid)
            r = run_recovery(v, workload, seed=args.seed,
                             p_resolve_table=p_table)
            all_results[table_name][vid] = r

    # Sensitivity matrix: completion rate per variant per table
    print("=" * 78)
    print("Completion rate by variant x probability table")
    print("=" * 78)
    table_names = sorted(P_RESOLVE_TABLES.keys())
    print(f"{'variant':<40} " + " ".join(f"{t:>12}" for t in table_names))
    for vid in VARIANT_IDS:
        row = [f"{all_results[t][vid].completion_rate_pct:>11.2f}%"
               for t in table_names]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # Cost per completion sensitivity
    print("=" * 78)
    print("Cost per completion by variant x probability table")
    print("=" * 78)
    print(f"{'variant':<40} " + " ".join(f"{t:>12}" for t in table_names))
    for vid in VARIANT_IDS:
        row = [f"{all_results[t][vid].cost_per_completion:>12.3f}"
               for t in table_names]
        print(f"{vid:<40} " + " ".join(row))
    print()

    # UC-REC gate outcomes per table for non-baseline variants
    print("=" * 78)
    print("UC-REC gate verdicts per table (vs b-abort baseline)")
    print("=" * 78)
    sensitivity_summary: dict[str, dict] = {}
    for table_name in table_names:
        baseline = all_results[table_name]["b-abort-on-failure"]
        sensitivity_summary[table_name] = {}
        for vid in VARIANT_IDS[1:]:
            gates = compute_uc_rec_gates(all_results[table_name][vid],
                                         baseline)
            statuses = {uc: info["status"] for uc, info in gates.items()}
            n_pass = sum(1 for s in statuses.values() if s == "PASS")
            sensitivity_summary[table_name][vid] = {
                "gates": gates,
                "n_pass": n_pass,
                "n_gates": len(gates),
                "all_pass": n_pass == len(gates),
            }
            print(f"  table={table_name:>12} variant={vid:<40} "
                  f"{n_pass}/{len(gates)} PASS")
            for uc, info in gates.items():
                mark = "PASS" if info["status"] == "PASS" else "FAIL"
                print(f"    [{mark}] {uc}: {info['reason']}")
        print()

    # Verdict summary: did each variant pass all gates across all tables?
    print("=" * 78)
    print("Verdict: robust across all probability tables?")
    print("=" * 78)
    for vid in VARIANT_IDS[1:]:
        pass_tables = [t for t in table_names
                       if sensitivity_summary[t][vid]["all_pass"]]
        fail_tables = [t for t in table_names
                       if not sensitivity_summary[t][vid]["all_pass"]]
        if fail_tables:
            print(f"  {vid}: PASS on {len(pass_tables)}/{len(table_names)} tables; "
                  f"FAILS on: {fail_tables}")
        else:
            print(f"  {vid}: PASS on all {len(table_names)} tables (ROBUST)")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "recovery_stage3_sensitivity"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 3 sensitivity analysis",
        "opportunity": "agent recovery policy benchmark",
        "workload_params": {
            "n_scenarios": args.n_scenarios,
            "failure_rate": args.failure_rate,
            "seed": args.seed,
            "n_scenarios_with_failure": workload.n_scenarios_with_failure,
            "failure_distribution": workload.failure_distribution,
        },
        "results_by_table": {
            t: {
                vid: {
                    "completion_rate_pct": all_results[t][vid].completion_rate_pct,
                    "n_completed": all_results[t][vid].n_completed,
                    "cost_per_completion": all_results[t][vid].cost_per_completion,
                    "latency_p99_steps": all_results[t][vid].latency_p99_steps,
                    "max_attempts_seen": all_results[t][vid].max_attempts_seen,
                    "action_kind_counts": all_results[t][vid].action_kind_counts,
                    "completion_by_failure_kind": all_results[t][vid].completion_by_failure_kind,
                }
                for vid in VARIANT_IDS
            }
            for t in table_names
        },
        "uc_gates_by_table": {
            t: {
                vid: sensitivity_summary[t][vid]["gates"]
                for vid in VARIANT_IDS[1:]
            }
            for t in table_names
        },
        "verdict": {
            vid: {
                "tables_pass": [t for t in table_names
                                if sensitivity_summary[t][vid]["all_pass"]],
                "tables_fail": [t for t in table_names
                                if not sensitivity_summary[t][vid]["all_pass"]],
                "robust": all(sensitivity_summary[t][vid]["all_pass"]
                              for t in table_names),
            }
            for vid in VARIANT_IDS[1:]
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

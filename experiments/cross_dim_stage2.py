"""Cross-dimension orchestration experiment.

Runs five configurations on the cross-dimension workload to surface
whether dimension lifts ADD linearly or INTERACT:

  1. (b-default-prompt, b-allow-all-tools, b-abort-on-failure)       all baselines
  2. (best-prompt, b-allow-all-tools, b-abort-on-failure)             prompt only
  3. (b-default-prompt, best-tools, b-abort-on-failure)               tools only
  4. (b-default-prompt, b-allow-all-tools, best-recovery)             recovery only
  5. (best-prompt, best-tools, best-recovery)                         all three

If lifts add linearly, config 5's lift should equal (2's lift + 3's
lift + 4's lift). If they interact, config 5 will differ.

This is the framework's first cross-dimension experiment. It is what
distinguishes the six-dimension architecture from six independent
benchmarks.
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

from fixtures.workloads.w_cross_dim_scenarios import (
    generate_cross_dim_workload,
)
from fixtures.workloads.w_tool_selection import (
    TOOL_CATEGORIES,
    TOOL_UNIVERSE,
)
from runner.cross_dim_runner import run_cross_dim
from runner.dimensions.prompt import build as build_prompt
from runner.dimensions.recovery import build as build_recovery
from runner.dimensions.tools import build as build_tool


BEST_PROMPT = "prompt-v0.1.4-cot-plus-structured"
BEST_TOOLS = "tool-v0.1.1-intent-classified"
BEST_RECOVERY = "recovery-v0.1.1-fallback-chain"

BASE_PROMPT = "b-default-prompt"
BASE_TOOLS = "b-allow-all-tools"
BASE_RECOVERY = "b-abort-on-failure"


CONFIGS = [
    ("all-baselines", BASE_PROMPT, BASE_TOOLS, BASE_RECOVERY),
    ("prompt-only", BEST_PROMPT, BASE_TOOLS, BASE_RECOVERY),
    ("tools-only", BASE_PROMPT, BEST_TOOLS, BASE_RECOVERY),
    ("recovery-only", BASE_PROMPT, BASE_TOOLS, BEST_RECOVERY),
    ("all-three", BEST_PROMPT, BEST_TOOLS, BEST_RECOVERY),
]


def main():
    p = argparse.ArgumentParser(prog="cross-dim-stage2")
    p.add_argument("--n-scenarios", type=int, default=500)
    p.add_argument("--failure-rate", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Cross-dimension orchestration experiment")
    print("=" * 78)
    print(f"Workload: n_scenarios={args.n_scenarios}, "
          f"failure_rate={args.failure_rate}, seed={args.seed}")

    workload = generate_cross_dim_workload(
        n_scenarios=args.n_scenarios,
        failure_rate=args.failure_rate,
        seed=args.seed,
    )
    print(f"Generated {workload.n_scenarios} scenarios, "
          f"{workload.n_scenarios_with_failure} with injected failures")
    print(f"By category: {workload.by_category}")
    print(f"Failure dist: {workload.failure_distribution}")
    print()

    results = {}
    for label, p_id, t_id, r_id in CONFIGS:
        prompt_v = build_prompt(p_id)
        tool_v = build_tool(t_id)
        recovery_v = build_recovery(r_id)
        t0 = time.perf_counter()
        r = run_cross_dim(
            prompt_v, tool_v, recovery_v,
            workload,
            tool_universe=list(TOOL_UNIVERSE),
            categories_map=TOOL_CATEGORIES,
            seed=args.seed,
        )
        elapsed = time.perf_counter() - t0
        results[label] = r
        print(f"--- {label}: {r.config_label} ---")
        print(f"  completion rate:      {r.completion_rate_pct:.2f}%")
        print(f"  blocked by tools:     {r.n_scenarios_blocked_by_tools}")
        print(f"  blocked by recovery:  {r.n_scenarios_blocked_by_recovery}")
        print(f"  avg P_prompt:         {r.avg_p_prompt:.3f}")
        print(f"  avg P_tools:          {r.avg_p_tools:.3f}")
        print(f"  avg P_recovery:       {r.avg_p_recovery:.3f}")
        print(f"  wall time:            {elapsed:.3f} s")
        print()

    # Interaction analysis
    baseline_pct = results["all-baselines"].completion_rate_pct
    prompt_only_pct = results["prompt-only"].completion_rate_pct
    tools_only_pct = results["tools-only"].completion_rate_pct
    recovery_only_pct = results["recovery-only"].completion_rate_pct
    all_three_pct = results["all-three"].completion_rate_pct

    delta_prompt = prompt_only_pct - baseline_pct
    delta_tools = tools_only_pct - baseline_pct
    delta_recovery = recovery_only_pct - baseline_pct
    additive_predicted = baseline_pct + delta_prompt + delta_tools + delta_recovery
    actual_all_three = all_three_pct
    interaction_term = actual_all_three - additive_predicted

    print("=" * 78)
    print("Interaction analysis")
    print("=" * 78)
    print(f"baseline                  : {baseline_pct:.2f}%")
    print(f"+ prompt only delta       : {delta_prompt:+.2f}pp -> {prompt_only_pct:.2f}%")
    print(f"+ tools only delta        : {delta_tools:+.2f}pp -> {tools_only_pct:.2f}%")
    print(f"+ recovery only delta     : {delta_recovery:+.2f}pp -> {recovery_only_pct:.2f}%")
    print(f"Additive prediction       : {additive_predicted:.2f}% (sum of deltas)")
    print(f"Actual all-three          : {actual_all_three:.2f}%")
    print(f"Interaction term          : {interaction_term:+.2f}pp")
    print()

    if abs(interaction_term) < 1.0:
        verdict = "near-linear: dimensions are roughly independent"
    elif interaction_term > 1.0:
        verdict = "super-additive: dimensions REINFORCE each other (combining lifts more than sum)"
    else:
        verdict = "sub-additive: dimensions COMPETE or saturate (weakest dimension caps combined lift)"
    print(f"Verdict: {verdict}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "cross_dim_stage2"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "cross-dimension orchestration Stage 2",
        "workload_params": {
            "n_scenarios": args.n_scenarios,
            "failure_rate": args.failure_rate,
            "seed": args.seed,
            "n_with_failure": workload.n_scenarios_with_failure,
            "by_category": workload.by_category,
            "failure_distribution": workload.failure_distribution,
        },
        "configurations": {
            label: {
                "config_label": r.config_label,
                "prompt_variant": r.prompt_variant,
                "tool_variant": r.tool_variant,
                "recovery_variant": r.recovery_variant,
                "completion_rate_pct": r.completion_rate_pct,
                "n_completed": r.n_completed,
                "n_blocked_by_tools": r.n_scenarios_blocked_by_tools,
                "n_blocked_by_recovery": r.n_scenarios_blocked_by_recovery,
                "avg_p_prompt": r.avg_p_prompt,
                "avg_p_tools": r.avg_p_tools,
                "avg_p_recovery": r.avg_p_recovery,
            }
            for label, r in results.items()
        },
        "interaction_analysis": {
            "baseline_pct": baseline_pct,
            "delta_prompt_only_pp": delta_prompt,
            "delta_tools_only_pp": delta_tools,
            "delta_recovery_only_pp": delta_recovery,
            "additive_prediction_pct": additive_predicted,
            "actual_all_three_pct": actual_all_three,
            "interaction_term_pp": interaction_term,
            "verdict": verdict,
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

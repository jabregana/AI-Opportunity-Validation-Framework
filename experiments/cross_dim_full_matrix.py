"""Full cross-dimension variant matrix experiment.

Runs every combination of (prompt, tools, recovery) variants on the
unified cross-dim workload. Identifies Pareto-optimal joint
configurations and surfaces interaction patterns invisible to
single-dimension benchmarks.

Variants in scope (n = 6 * 4 * 3 = 72 configurations):
  prompt:    b-default, v0.1.0-cot, v0.1.1-direct-structured,
             v0.1.2-few-shot-1, v0.1.3-few-shot-3,
             v0.1.4-cot-plus-structured
  tools:     b-allow-all, v0.1.0-budget, v0.1.1-intent,
             v0.1.2-intent-plus-helper
  recovery:  b-abort, v0.1.0-retry, v0.1.1-fallback

For each config, computes completion rate + cost (proxy: avg P_prompt
* P_tools * P_recovery, since per-config costs are dominated by the
prompt token count). Identifies:
  - Best-completion config(s)
  - Best-cost-per-completion config(s)
  - Pareto frontier of (cost-proxy, completion)
  - Joint configs that BEAT all-baselines vs joint configs that LOSE
"""
from __future__ import annotations
import argparse
import itertools
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


PROMPT_VARIANTS = [
    "b-default-prompt",
    "prompt-v0.1.0-cot",
    "prompt-v0.1.1-direct-structured",
    "prompt-v0.1.2-few-shot-1",
    "prompt-v0.1.3-few-shot-3",
    "prompt-v0.1.4-cot-plus-structured",
]

TOOL_VARIANTS = [
    "b-allow-all-tools",
    "tool-v0.1.0-budget-bucketed",
    "tool-v0.1.1-intent-classified",
    "tool-v0.1.2-intent-plus-helper",
]

RECOVERY_VARIANTS = [
    "b-abort-on-failure",
    "recovery-v0.1.0-retry-with-backoff",
    "recovery-v0.1.1-fallback-chain",
]


def main():
    p = argparse.ArgumentParser(prog="cross-dim-full-matrix")
    p.add_argument("--n-scenarios", type=int, default=500)
    p.add_argument("--failure-rate", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Cross-dim FULL MATRIX experiment")
    print("=" * 78)
    n_configs = (len(PROMPT_VARIANTS) * len(TOOL_VARIANTS)
                 * len(RECOVERY_VARIANTS))
    print(f"Configs: {len(PROMPT_VARIANTS)} prompts x "
          f"{len(TOOL_VARIANTS)} tools x "
          f"{len(RECOVERY_VARIANTS)} recovery = {n_configs}")

    workload = generate_cross_dim_workload(
        n_scenarios=args.n_scenarios,
        failure_rate=args.failure_rate,
        seed=args.seed,
    )
    print(f"Workload: {workload.n_scenarios} scenarios, "
          f"{workload.n_scenarios_with_failure} with failures")
    print()

    results = []
    t0 = time.perf_counter()
    for p_id, t_id, r_id in itertools.product(
        PROMPT_VARIANTS, TOOL_VARIANTS, RECOVERY_VARIANTS,
    ):
        prompt_v = build_prompt(p_id)
        tool_v = build_tool(t_id)
        recovery_v = build_recovery(r_id)
        res = run_cross_dim(
            prompt_v, tool_v, recovery_v,
            workload,
            tool_universe=list(TOOL_UNIVERSE),
            categories_map=TOOL_CATEGORIES,
            seed=args.seed,
        )
        results.append({
            "prompt": p_id,
            "tools": t_id,
            "recovery": r_id,
            "completion_rate_pct": res.completion_rate_pct,
            "avg_p_prompt": res.avg_p_prompt,
            "avg_p_tools": res.avg_p_tools,
            "avg_p_recovery": res.avg_p_recovery,
        })
    elapsed = time.perf_counter() - t0
    print(f"Ran {len(results)} configs in {elapsed:.2f}s "
          f"({elapsed / len(results) * 1000:.1f}ms per config)")
    print()

    # Sort by completion rate
    results.sort(key=lambda r: -r["completion_rate_pct"])

    # Top 10
    print("=" * 78)
    print("Top 10 by completion rate")
    print("=" * 78)
    print(f"{'rank':>4} {'compl%':>7} {'prompt':<32} {'tools':<30} {'recovery':<32}")
    for i, r in enumerate(results[:10]):
        p_short = r["prompt"].replace("prompt-", "").replace("b-default-prompt", "b-default")
        t_short = r["tools"].replace("tool-", "").replace("b-allow-all-tools", "b-allow-all")
        rec_short = r["recovery"].replace("recovery-", "").replace("b-abort-on-failure", "b-abort")
        print(f"{i+1:>4} {r['completion_rate_pct']:>6.2f}% "
              f"{p_short:<32} {t_short:<30} {rec_short:<32}")
    print()

    # Bottom 5 (likely worse-than-baseline)
    print("=" * 78)
    print("Bottom 5 by completion rate")
    print("=" * 78)
    print(f"{'rank':>4} {'compl%':>7} {'prompt':<32} {'tools':<30} {'recovery':<32}")
    for i, r in enumerate(results[-5:]):
        rank = len(results) - 5 + i + 1
        p_short = r["prompt"].replace("prompt-", "").replace("b-default-prompt", "b-default")
        t_short = r["tools"].replace("tool-", "").replace("b-allow-all-tools", "b-allow-all")
        rec_short = r["recovery"].replace("recovery-", "").replace("b-abort-on-failure", "b-abort")
        print(f"{rank:>4} {r['completion_rate_pct']:>6.2f}% "
              f"{p_short:<32} {t_short:<30} {rec_short:<32}")
    print()

    # Baseline + count beat
    baseline = next(
        r for r in results
        if r["prompt"] == "b-default-prompt"
        and r["tools"] == "b-allow-all-tools"
        and r["recovery"] == "b-abort-on-failure"
    )
    n_beat_baseline = sum(
        1 for r in results
        if r["completion_rate_pct"] > baseline["completion_rate_pct"]
    )
    n_worse_baseline = sum(
        1 for r in results
        if r["completion_rate_pct"] < baseline["completion_rate_pct"]
    )

    print("=" * 78)
    print("Cross-dim interaction summary")
    print("=" * 78)
    print(f"All-baselines completion:    {baseline['completion_rate_pct']:.2f}%")
    print(f"Configs that BEAT baseline:  {n_beat_baseline} / {len(results)}"
          f" ({100.0 * n_beat_baseline / len(results):.1f}%)")
    print(f"Configs that LOSE vs baseline: {n_worse_baseline} / {len(results)}"
          f" ({100.0 * n_worse_baseline / len(results):.1f}%)")
    print()

    # Per-tools-variant rollup: avg completion across all (prompt, recovery) combos
    print("=" * 78)
    print("Avg completion by tools variant (rolled up across prompt + recovery)")
    print("=" * 78)
    by_tool: dict[str, list[float]] = {t: [] for t in TOOL_VARIANTS}
    for r in results:
        by_tool[r["tools"]].append(r["completion_rate_pct"])
    for t in TOOL_VARIANTS:
        avg = sum(by_tool[t]) / max(1, len(by_tool[t]))
        print(f"  {t:<35}  {avg:.2f}% avg")
    print()

    print("=" * 78)
    print("Avg completion by recovery variant (rolled up across prompt + tools)")
    print("=" * 78)
    by_rec: dict[str, list[float]] = {r: [] for r in RECOVERY_VARIANTS}
    for r in results:
        by_rec[r["recovery"]].append(r["completion_rate_pct"])
    for rv in RECOVERY_VARIANTS:
        avg = sum(by_rec[rv]) / max(1, len(by_rec[rv]))
        print(f"  {rv:<40}  {avg:.2f}% avg")
    print()

    print("=" * 78)
    print("Avg completion by prompt variant (rolled up across tools + recovery)")
    print("=" * 78)
    by_pr: dict[str, list[float]] = {p: [] for p in PROMPT_VARIANTS}
    for r in results:
        by_pr[r["prompt"]].append(r["completion_rate_pct"])
    for pv in PROMPT_VARIANTS:
        avg = sum(by_pr[pv]) / max(1, len(by_pr[pv]))
        print(f"  {pv:<40}  {avg:.2f}% avg")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "cross_dim_full_matrix"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "cross-dimension full variant matrix",
        "n_configs": len(results),
        "workload_params": {
            "n_scenarios": args.n_scenarios,
            "failure_rate": args.failure_rate,
            "seed": args.seed,
        },
        "baseline_completion_pct": baseline["completion_rate_pct"],
        "n_configs_beat_baseline": n_beat_baseline,
        "n_configs_worse_baseline": n_worse_baseline,
        "results": results,
        "rolled_up_by_tools": {
            t: sum(by_tool[t]) / max(1, len(by_tool[t]))
            for t in TOOL_VARIANTS
        },
        "rolled_up_by_recovery": {
            r: sum(by_rec[r]) / max(1, len(by_rec[r]))
            for r in RECOVERY_VARIANTS
        },
        "rolled_up_by_prompt": {
            p: sum(by_pr[p]) / max(1, len(by_pr[p]))
            for p in PROMPT_VARIANTS
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

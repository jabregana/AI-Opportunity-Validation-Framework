"""Cost-weighted full cross-dim matrix.

Extends cross_dim_full_matrix.py with per-config cost tracking (prompt
tokens + tool tokens + recovery tokens) and bootstrap confidence
intervals on the completion rate. Identifies the (cost, completion)
Pareto frontier.

This experiment directly addresses two pieces of analyst feedback:

  1. 'Currently answers "is this real?" but executives need "what
      should I do next?"' -> Pareto frontier gives ordered candidates
      by cost-per-correct.

  2. 'Top-10 by completion may not be the deployable top-10 if some
      configurations cost 10x more per completion' -> cost-weighted
      ranking surfaces this directly.

Output includes both raw completion ranking + Pareto frontier + CIs
on top configurations for statistical confidence.
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
from runner.cross_dim_runner import (
    bootstrap_ci_for_completion,
    run_cross_dim,
)
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


def is_pareto_optimal(
    candidate: dict,
    all_configs: list[dict],
) -> bool:
    """A config is Pareto-optimal if no other config has BOTH
    higher completion AND lower (or equal) cost-per-completion."""
    for other in all_configs:
        if other is candidate:
            continue
        if (other["completion_rate_pct"] > candidate["completion_rate_pct"]
                and other["cost_per_completion"] <= candidate["cost_per_completion"]):
            return False
        if (other["completion_rate_pct"] >= candidate["completion_rate_pct"]
                and other["cost_per_completion"] < candidate["cost_per_completion"]):
            return False
    return True


def main():
    p = argparse.ArgumentParser(prog="cross-dim-cost-weighted")
    p.add_argument("--n-scenarios", type=int, default=500)
    p.add_argument("--failure-rate", type=float, default=0.30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-bootstrap", type=int, default=500,
                   help="bootstrap resamples for CI computation")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Cost-weighted cross-dim matrix")
    print("=" * 78)
    n_configs = (len(PROMPT_VARIANTS) * len(TOOL_VARIANTS)
                 * len(RECOVERY_VARIANTS))
    print(f"Configs: {n_configs} = {len(PROMPT_VARIANTS)} prompts x "
          f"{len(TOOL_VARIANTS)} tools x {len(RECOVERY_VARIANTS)} recovery")

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
        # Bootstrap CI for completion
        point, lo, hi = bootstrap_ci_for_completion(
            res.per_scenario_outcomes,
            n_resamples=args.n_bootstrap,
            seed=args.seed,
        )
        results.append({
            "prompt": p_id,
            "tools": t_id,
            "recovery": r_id,
            "completion_rate_pct": res.completion_rate_pct,
            "completion_ci_lo_pct": lo,
            "completion_ci_hi_pct": hi,
            "total_cost": res.total_cost,
            "cost_per_completion": res.cost_per_completion,
            "avg_prompt_tokens": res.avg_prompt_tokens,
            "avg_tool_tokens": res.avg_tool_tokens,
            "avg_recovery_tokens": res.avg_recovery_tokens,
            "avg_p_tools": res.avg_p_tools,
        })
    elapsed = time.perf_counter() - t0
    print(f"Ran {len(results)} configs + bootstraps in {elapsed:.2f}s")
    print()

    # Pareto frontier
    pareto = [r for r in results if is_pareto_optimal(r, results)]
    pareto.sort(key=lambda r: -r["completion_rate_pct"])

    print("=" * 78)
    print(f"Pareto frontier ({len(pareto)} configs)")
    print("(non-dominated on (cost-per-completion, completion-rate))")
    print("=" * 78)
    print(f"{'compl%':>8} {'CI(lo-hi)':>17} {'cost/comp':>10} "
          f"{'prompt':<22} {'tools':<22} {'recovery':<24}")
    for r in pareto:
        p_short = r["prompt"].replace("prompt-", "").replace("b-default-prompt", "b-default")[:22]
        t_short = r["tools"].replace("tool-", "").replace("b-allow-all-tools", "b-allow-all")[:22]
        rec_short = r["recovery"].replace("recovery-", "").replace("b-abort-on-failure", "b-abort")[:24]
        ci = f"[{r['completion_ci_lo_pct']:.1f}-{r['completion_ci_hi_pct']:.1f}]"
        print(f"{r['completion_rate_pct']:>7.2f}% {ci:>17} "
              f"{r['cost_per_completion']:>10.1f} "
              f"{p_short:<22} {t_short:<22} {rec_short:<24}")
    print()

    # Top 10 by completion + CIs
    by_completion = sorted(results, key=lambda r: -r["completion_rate_pct"])[:10]
    print("=" * 78)
    print("Top 10 by completion rate (with bootstrap CIs)")
    print("=" * 78)
    print(f"{'rank':>4} {'compl%':>8} {'CI(lo-hi)':>17} {'cost/comp':>10} "
          f"{'prompt':<22} {'tools':<22} {'recovery':<24}")
    for i, r in enumerate(by_completion):
        p_short = r["prompt"].replace("prompt-", "").replace("b-default-prompt", "b-default")[:22]
        t_short = r["tools"].replace("tool-", "").replace("b-allow-all-tools", "b-allow-all")[:22]
        rec_short = r["recovery"].replace("recovery-", "").replace("b-abort-on-failure", "b-abort")[:24]
        ci = f"[{r['completion_ci_lo_pct']:.1f}-{r['completion_ci_hi_pct']:.1f}]"
        print(f"{i+1:>4} {r['completion_rate_pct']:>7.2f}% {ci:>17} "
              f"{r['cost_per_completion']:>10.1f} "
              f"{p_short:<22} {t_short:<22} {rec_short:<24}")
    print()

    # Best cost-per-completion (lowest)
    by_cost = sorted(results, key=lambda r: r["cost_per_completion"])[:10]
    print("=" * 78)
    print("Top 10 by cost-per-completion (cheapest first)")
    print("=" * 78)
    print(f"{'rank':>4} {'cost/comp':>10} {'compl%':>8} {'CI(lo-hi)':>17} "
          f"{'prompt':<22} {'tools':<22} {'recovery':<24}")
    for i, r in enumerate(by_cost):
        p_short = r["prompt"].replace("prompt-", "").replace("b-default-prompt", "b-default")[:22]
        t_short = r["tools"].replace("tool-", "").replace("b-allow-all-tools", "b-allow-all")[:22]
        rec_short = r["recovery"].replace("recovery-", "").replace("b-abort-on-failure", "b-abort")[:24]
        ci = f"[{r['completion_ci_lo_pct']:.1f}-{r['completion_ci_hi_pct']:.1f}]"
        print(f"{i+1:>4} {r['cost_per_completion']:>10.1f} "
              f"{r['completion_rate_pct']:>7.2f}% {ci:>17} "
              f"{p_short:<22} {t_short:<22} {rec_short:<24}")
    print()

    # Overlap test: which of the top-10 by completion are statistically
    # distinguishable from each other?
    print("=" * 78)
    print("Statistical-distinguishability check (top 10 by completion)")
    print("=" * 78)
    rank1 = by_completion[0]
    n_overlapping = sum(
        1 for r in by_completion[1:]
        if r["completion_ci_hi_pct"] >= rank1["completion_ci_lo_pct"]
    )
    print(f"Of top-10 configs, {n_overlapping} of 9 below #1 have CIs that")
    print(f"overlap with #1's CI {rank1['completion_ci_lo_pct']:.1f}-{rank1['completion_ci_hi_pct']:.1f}%.")
    print("These configs are NOT statistically distinguishable from #1 at 95% CI.")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "cross_dim_cost_weighted"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "cross-dimension cost-weighted matrix",
        "n_configs": len(results),
        "workload_params": {
            "n_scenarios": args.n_scenarios,
            "failure_rate": args.failure_rate,
            "seed": args.seed,
        },
        "bootstrap_params": {
            "n_resamples": args.n_bootstrap,
            "confidence_level": 0.95,
        },
        "results": results,
        "pareto_frontier": pareto,
        "top_10_by_completion": by_completion,
        "top_10_by_cost_per_completion": by_cost,
        "rank1_completion_ci_lo_pct": rank1["completion_ci_lo_pct"],
        "rank1_completion_ci_hi_pct": rank1["completion_ci_hi_pct"],
        "n_top10_overlapping_rank1": n_overlapping,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

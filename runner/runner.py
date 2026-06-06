"""Harness entrypoint per experiments.md §6.

Pilot scope: UC-4.1 only. Runs one variant + one baseline on a workload,
computes paired pairwise-F1 + per-item correctness, bootstraps the CI +
one-sided p-value on the variant - baseline difference, runs the result
through a LORD++ ledger (single-test ledger in pilot), applies the §6.4
INCONCLUSIVE-is-FAIL gate, and writes a §6.1 three-block artifact.

Usage:
  python -m runner.runner \\
    --variant stub-random-bucket \\
    --baseline b-raw-identity \\
    --workload W-CONCEPTNET-REL \\
    --use-case UC-4.1 \\
    --tier fast
"""
from __future__ import annotations
import argparse
import sys
import time
from dataclasses import asdict

from fixtures import workloads
from runner import artifacts, gates, variants
from runner.fdr import LordPlusPlusLedger, run_ledger
from runner.metrics import alignment, stats


def _run_variant(
    variant: variants.Variant, workload: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], float]:
    """Apply variant to workload, return predictions and wall-clock time (s)."""
    t0 = time.perf_counter()
    preds = [(inp, variant.align(inp)) for inp, _ in workload]
    elapsed = time.perf_counter() - t0
    return preds, elapsed


def _outcome_from_bootstrap(bs: stats.BootstrapResult, alpha_n: float) -> str:
    """Map a bootstrap result + LORD++ alpha into the artifact `outcome` enum.

    - CI excludes 0 on the positive side AND p ≤ α  → REJECT_NULL_SUPERIOR
    - CI excludes 0 on the negative side             → REGRESSION_DETECTED
    - CI brackets 0                                  → INCONCLUSIVE
    - Else                                           → FAIL_TO_REJECT
    """
    if bs.ci_low > 0 and bs.p_value_one_sided_gt <= alpha_n:
        return "REJECT_NULL_SUPERIOR"
    if bs.ci_high < 0:
        return "REGRESSION_DETECTED"
    if bs.ci_low <= 0 <= bs.ci_high:
        return "INCONCLUSIVE"
    return "FAIL_TO_REJECT"


def _pipeline_decision(
    test_executions: list[dict], tier: str
) -> tuple[str, list[str]]:
    """Apply §6.4 gates and produce a final pipeline_decision.

    Returns (decision, reasons[]).
    """
    reasons: list[str] = []
    outcomes = [t["outcome"] for t in test_executions]

    inconc_gate = gates.inconclusive_is_fail(outcomes, tier=tier)
    if not inconc_gate.passed:
        reasons.append(inconc_gate.reason)

    has_regression = any(o == "REGRESSION_DETECTED" for o in outcomes)
    if has_regression:
        reasons.append("at least one test detected a regression")

    has_failed_killswitch = any(
        t.get("type") == "guardrail_kill_switch" and t["outcome"] == "FAIL"
        for t in test_executions
    )
    if has_failed_killswitch:
        reasons.append("kill-switch guardrail FAIL")

    if not reasons:
        return "PASS_AND_MERGE", []
    if tier == "fast":
        return "BLOCK_PR", reasons
    return "SOFT_REGRESSION_OPENED", reasons


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="amg-run")
    p.add_argument("--variant", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--workload", required=True)
    p.add_argument("--use-case", required=True, help="e.g. UC-4.1")
    p.add_argument("--tier", default="fast", choices=["fast", "nightly"])
    p.add_argument("--bootstrap-resamples", type=int, default=10_000)
    p.add_argument("--target-q", type=float, default=0.10)
    p.add_argument("--out-dir", default="runs")
    args = p.parse_args(argv)

    workload = workloads.load(args.workload)
    workload_sha = artifacts.workload_sha256(workload)

    var = variants.build(args.variant)
    base = variants.build(args.baseline)

    var_preds, var_elapsed = _run_variant(var, workload)
    base_preds, base_elapsed = _run_variant(base, workload)

    var_f1 = alignment.pairwise_f1(var_preds, workload)
    base_f1 = alignment.pairwise_f1(base_preds, workload)

    var_correct = alignment.per_item_correctness(var_preds, workload)
    base_correct = alignment.per_item_correctness(base_preds, workload)
    mc_b, mc_c = stats.mcnemar_discordant_counts(var_correct, base_correct)

    # Primary signal: per-item B-cubed F1. Each item gets a continuous
    # score in [0, 1]; paired bootstrap on the per-item difference. This
    # replaces both (a) per-item strict-cluster correctness, which is
    # degenerate at sub-perfect F1, and (b) an earlier attempt at
    # index-resampled pairwise F1 bootstrap, which suffers from
    # bootstrap-duplicate-pair pathology on pair-level metrics.
    var_bcubed = alignment.per_item_bcubed_f1(var_preds, workload)
    base_bcubed = alignment.per_item_bcubed_f1(base_preds, workload)
    bcubed_diffs = [v - b for v, b in zip(var_bcubed, base_bcubed)]
    bs = stats.paired_bootstrap(
        bcubed_diffs, n_resamples=args.bootstrap_resamples
    )

    var_mean_bcubed = sum(var_bcubed) / len(var_bcubed) if var_bcubed else 0.0
    base_mean_bcubed = sum(base_bcubed) / len(base_bcubed) if base_bcubed else 0.0

    metric_id_suffix = args.use_case.lower().replace("-", "_").replace(".", "_")

    # Build one test_execution per metric. For the pilot UC-4.1 we have one
    # paired-bootstrap test on the per-item B-cubed F1 difference.
    test_executions: list[dict] = [
        {
            "test_seq_id": 1,
            "use_case": args.use_case,
            "metric_id": f"{metric_id_suffix}_per_item_bcubed_f1_diff",
            "type": "superiority",
            "statistical_test": "paired_bootstrap_per_item_bcubed",
            "n": bs.n,
            "point_estimate": bs.mean_diff,
            "always_valid_ci_lower": bs.ci_low,
            "always_valid_ci_upper": bs.ci_high,
            "ci_level": bs.ci_level,
            "p_value": bs.p_value_one_sided_gt,
            "diagnostics": {
                "variant_mean_bcubed_f1": var_mean_bcubed,
                "baseline_mean_bcubed_f1": base_mean_bcubed,
                "variant_pairwise_f1": var_f1.f1,
                "baseline_pairwise_f1": base_f1.f1,
                "variant_seconds": var_elapsed,
                "baseline_seconds": base_elapsed,
                "per_item_strict_correct_mcnemar_b": mc_b,
                "per_item_strict_correct_mcnemar_c": mc_c,
                "items": len(workload),
            },
        }
    ]

    # Run through LORD++ ledger to populate alpha_allocated + outcome_rejected.
    ordered, ledger = run_ledger(test_executions, target_q=args.target_q)
    for t in ordered:
        t["outcome"] = _outcome_from_bootstrap(bs, t["alpha_allocated"])

    decision, reasons = _pipeline_decision(ordered, tier=args.tier)

    path = artifacts.emit(
        variant_name=var.name,
        baseline_name=base.name,
        workload_id=args.workload,
        workload_sha=workload_sha,
        tier=args.tier,
        test_executions=ordered,
        ledger=ledger,
        pipeline_decision=decision,
        out_dir=args.out_dir,
    )
    print(f"Wrote {path}")
    print(f"  variant {var.name}: pairwise F1 = {var_f1.f1:.4f}")
    print(f"  baseline {base.name}: pairwise F1 = {base_f1.f1:.4f}")
    print(
        f"  per-item B-cubed F1: variant mean = {var_mean_bcubed:.4f}, "
        f"baseline mean = {base_mean_bcubed:.4f}"
    )
    print(
        f"  paired per-item B-cubed F1 diff: {bs.mean_diff:+.4f} "
        f"(95% CI [{bs.ci_low:+.4f}, {bs.ci_high:+.4f}], "
        f"one-sided p = {bs.p_value_one_sided_gt:.4f})"
    )
    print(f"  alpha allocated by LORD++ (n=1): {ordered[0]['alpha_allocated']:.4f}")
    print(f"  outcome: {ordered[0]['outcome']}")
    print(f"  pipeline_decision: {decision}")
    if reasons:
        for r in reasons:
            print(f"    - {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

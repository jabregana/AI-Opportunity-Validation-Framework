"""Harness entrypoint per experiments.md §6.

Supports two use-case modes:

  UC-4.1 (clustering): paired bootstrap on per-item B-cubed F1
    diff between variant and baseline on a workload.
      python -m runner.runner --variant V --baseline B \\
        --workload W --use-case UC-4.1 --tier fast

  UC-4.4 (false-positive resistance): runs the variant on every
    pair in a Tier B adversarial fixture and reports false-merge
    rate as a guardrail_kill_switch outcome.
      python -m runner.runner --variant V \\
        --tier-b-fixture fixtures/adversarials/X.json \\
        --use-case UC-4.4 --tier fast

Both modes apply the §6.4.1 INCONCLUSIVE-is-FAIL gate and write a
§6.1 three-block artifact.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

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


def _run_uc_4_4(args) -> int:
    """UC-4.4 — false-merge rate on a Tier B adversarial fixture."""
    fixture_path = Path(args.tier_b_fixture)
    fixture = json.loads(fixture_path.read_text())
    pairs = fixture["pairs"]
    n = len(pairs)
    if n == 0:
        print("Empty Tier B fixture; nothing to evaluate.", file=sys.stderr)
        return 2

    variant_factory = variants.FACTORIES[args.variant]
    false_merges = 0
    aliased_examples: list[dict] = []
    t0 = time.perf_counter()
    for pair in pairs:
        v = variant_factory()  # fresh variant per pair to isolate state
        ca = v.align(pair["a"])
        cb = v.align(pair["b"])
        if ca == cb:
            false_merges += 1
            if len(aliased_examples) < 5:
                aliased_examples.append({
                    "a": pair["a"], "b": pair["b"],
                    "reference_cosine": pair["cosine"],
                    "aliased_to": ca,
                })
    elapsed = time.perf_counter() - t0

    false_merge_rate = false_merges / n
    threshold = args.kill_switch_threshold
    outcome = "PASS" if false_merge_rate <= threshold else "FAIL"

    metric_id = "uc_4_4_tier_b_false_merge_rate"
    test_executions = [
        {
            "test_seq_id": 1,
            "use_case": args.use_case,
            "metric_id": metric_id,
            "type": "guardrail_kill_switch",
            "statistical_test": "raw_proportion",
            "n": n,
            "point_estimate": false_merge_rate,
            "guardrail_threshold": threshold,
            "alpha_allocated": 0.0,  # kill switches are not in the LORD++ family
            "outcome": outcome,
            "diagnostics": {
                "false_merges": false_merges,
                "total_pairs": n,
                "elapsed_seconds": elapsed,
                "fixture_path": str(fixture_path),
                "fixture_sha256": fixture.get("fixture_sha256", "unknown"),
                "reference_embedder": fixture.get("reference_embedder", "unknown"),
                "aliased_examples": aliased_examples,
            },
        }
    ]

    # Kill switches run outside the LORD++ ledger but we still emit a
    # minimal ledger block so the artifact schema is uniform.
    ledger = LordPlusPlusLedger(target_q=args.target_q)

    has_failure = any(t["outcome"] == "FAIL" for t in test_executions)
    if has_failure:
        decision = "BLOCK_PR" if args.tier == "fast" else "SOFT_REGRESSION_OPENED"
    else:
        decision = "PASS_AND_MERGE"

    path = artifacts.emit(
        variant_name=variant_factory().name,
        baseline_name="(none — kill-switch test)",
        workload_id=f"tier-b:{fixture_path.name}",
        workload_sha=fixture.get("fixture_sha256", "unknown"),
        tier=args.tier,
        test_executions=test_executions,
        ledger=ledger,
        pipeline_decision=decision,
        out_dir=args.out_dir,
    )
    print(f"Wrote {path}")
    print(f"  variant {args.variant} on {fixture_path.name}")
    print(f"  pairs evaluated: {n}")
    print(
        f"  false merges: {false_merges} ({false_merge_rate:.3%}); "
        f"kill-switch threshold: {threshold:.3%}"
    )
    print(f"  outcome: {outcome}")
    if aliased_examples:
        print(f"  first {len(aliased_examples)} false merges:")
        for ex in aliased_examples:
            print(
                f"    {ex['a']:30s} <-> {ex['b']:30s} "
                f"(ref cosine {ex['reference_cosine']:.3f}, aliased to {ex['aliased_to']!r})"
            )
    print(f"  pipeline_decision: {decision}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="amg-run")
    p.add_argument("--variant", required=True)
    p.add_argument("--baseline", help="(UC-4.1 only) baseline variant id")
    p.add_argument("--workload", help="(UC-4.1 only) workload id")
    p.add_argument("--use-case", required=True,
                   help="UC-4.1 (clustering) or UC-4.4 (Tier B kill-switch)")
    p.add_argument("--tier", default="fast", choices=["fast", "nightly"])
    p.add_argument("--bootstrap-resamples", type=int, default=10_000)
    p.add_argument("--target-q", type=float, default=0.10)
    p.add_argument("--out-dir", default="runs")
    # UC-4.4-specific
    p.add_argument("--tier-b-fixture",
                   help="(UC-4.4 only) path to adversarial fixture JSON")
    p.add_argument("--kill-switch-threshold", type=float, default=0.01,
                   help="(UC-4.4 only) max acceptable false-merge rate "
                        "(default 1%% per experiments.md §3 UC-4.4 Tier A)")
    args = p.parse_args(argv)

    if args.use_case == "UC-4.4":
        if not args.tier_b_fixture:
            print("UC-4.4 requires --tier-b-fixture", file=sys.stderr)
            return 2
        return _run_uc_4_4(args)

    # UC-4.1 path (existing logic)
    if not args.baseline or not args.workload:
        print("UC-4.1 requires --baseline and --workload", file=sys.stderr)
        return 2

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

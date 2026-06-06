"""Harness entrypoint per experiments.md §6.

Pilot scope: UC-4.1 only. Runs one variant + one baseline on a workload,
computes paired pairwise-F1 and per-item correctness, bootstraps the CI
on the variant - baseline difference, and writes a JSON artifact.

Usage:
  python -m runner.runner \\
    --variant stub-random-bucket \\
    --baseline b-raw-identity \\
    --workload W-CONCEPTNET-REL \\
    --use-case UC-4.1
"""
from __future__ import annotations
import argparse
import sys
import time
from dataclasses import asdict

from fixtures import workloads
from runner import artifacts, variants
from runner.metrics import alignment, stats


def _run_variant(
    variant: variants.Variant, workload: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], float]:
    """Apply variant to workload, return predictions and wall-clock time (s)."""
    t0 = time.perf_counter()
    preds = [(inp, variant.align(inp)) for inp, _ in workload]
    elapsed = time.perf_counter() - t0
    return preds, elapsed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="amg-run")
    p.add_argument("--variant", required=True, help="variant id from runner.variants.FACTORIES")
    p.add_argument("--baseline", required=True, help="baseline variant id")
    p.add_argument("--workload", required=True, help="workload id from fixtures.workloads.LOADERS")
    p.add_argument("--use-case", required=True, help="UC label, e.g. UC-4.1")
    p.add_argument("--bootstrap-resamples", type=int, default=10_000)
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
    diffs = [float(v - b) for v, b in zip(var_correct, base_correct)]
    # TODO: when a real variant lands non-trivial F1, switch this bootstrap
    # to resample input indices and recompute pairwise F1 within each
    # resample — per-item strict-cluster correctness is degenerate (all 0)
    # at near-chance performance.
    bs = stats.paired_bootstrap(diffs, n_resamples=args.bootstrap_resamples)
    mc_b, mc_c = stats.mcnemar_discordant_counts(var_correct, base_correct)

    metrics = {
        args.use_case.lower().replace("-", "_").replace(".", "_"): {
            "primary": {
                "metric": "pairwise_f1",
                "variant": asdict(var_f1),
                "baseline": asdict(base_f1),
                "paired_diff_mean_per_item_correct": bs.mean_diff,
                "paired_diff_ci_95": [bs.ci_low, bs.ci_high],
                "paired_diff_n": bs.n,
                "bootstrap_resamples": bs.n_resamples,
                "mcnemar_b_variant_wins": mc_b,
                "mcnemar_c_baseline_wins": mc_c,
            },
            "diagnostics": {
                "variant_seconds": var_elapsed,
                "baseline_seconds": base_elapsed,
                "items": len(workload),
            },
        }
    }

    # Pilot decision rule: CI excludes zero in the positive direction → variant wins.
    if bs.ci_low > 0:
        decision = "pass"
    elif bs.ci_high < 0:
        decision = "regress"
    else:
        decision = "inconclusive"

    path = artifacts.emit(
        variant=var.name,
        baseline=base.name,
        workload_id=args.workload,
        workload_sha=workload_sha,
        use_case=args.use_case,
        metrics=metrics,
        decision=decision,
        out_dir=args.out_dir,
    )
    print(f"Wrote {path}")
    print(f"  variant {var.name}: pairwise F1 = {var_f1.f1:.4f}")
    print(f"  baseline {base.name}: pairwise F1 = {base_f1.f1:.4f}")
    print(
        f"  paired per-item correctness diff: {bs.mean_diff:+.4f} "
        f"(95% CI [{bs.ci_low:+.4f}, {bs.ci_high:+.4f}])"
    )
    print(f"  McNemar discordants: variant-wins={mc_b}, baseline-wins={mc_c}")
    print(f"  decision: {decision}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

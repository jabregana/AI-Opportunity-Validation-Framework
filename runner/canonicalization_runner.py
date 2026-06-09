"""Harness entrypoint per experiments.md §6.

Supports two use-case modes:

  UC-4.1 (clustering): paired bootstrap on per-item B-cubed F1
    diff between variant and baseline on a workload.
      python -m runner.canonicalization_runner --variant V --baseline B \\
        --workload W --use-case UC-4.1 --tier fast

  UC-4.4 (false-positive resistance): runs the variant on every
    pair in a Tier B adversarial fixture and reports false-merge
    rate as a guardrail_kill_switch outcome.
      python -m runner.canonicalization_runner --variant V \\
        --tier-b-fixture fixtures/adversarials/X.json \\
        --use-case UC-4.4 --tier fast

Both modes apply the §6.4.1 INCONCLUSIVE-is-FAIL gate and write a
§6.1 three-block artifact.
"""
from __future__ import annotations
import argparse
import json
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path

from fixtures import workloads
from runner import artifacts, gates, variants
from runner.fdr import LordPlusPlusLedger, run_ledger
from runner.metrics import alignment, stats


def _run_variant(variant, workload, two_pass: bool = True):
    """Apply variant to workload entries with optional consolidation.

    Returns (post_preds, pre_preds, consolidation_summary, elapsed_seconds).

      post_preds              : list[(input, canonical)] from the FINAL state
                                (after consolidation if applicable).
      pre_preds               : list[(input, canonical)] from pass 1, BEFORE
                                consolidation. Identical to post_preds for
                                eager variants; may differ for v0.4.2 lazy.
      consolidation_summary   : dict returned by variant.consolidate() if the
                                variant exposes it; None otherwise.
      elapsed_seconds         : wall clock for the whole two-pass cycle.

    Three execution paths:
      - Single-pass variants (v0.1.0 - v0.4.1): align_with_context is idempotent;
        second pass returns same canonicals as first.
      - Lazy variants (v0.4.2): pass 1 returns source-prefixed canonicals;
        consolidate() runs the cross-source merge; pass 2 returns merged
        canonicals. The diff between pass 1 and pass 2 is the drift_rate.
      - UC-4.6 latency benchmark uses _run_variant_single_pass instead
        to keep timing measurement accurate.
    """
    t0 = time.perf_counter()
    # Pass 1: ingestion. Capture pre-consolidation predictions for the
    # drift_rate metric.
    pre_preds = []
    for entry in workload:
        ctx = {"source_id": entry.source_id}
        canonical = variant.align_with_context(entry.input, ctx)
        pre_preds.append((entry.input, canonical))

    # Optional consolidation step (lazy variants only)
    consolidation_summary = None
    if hasattr(variant, "consolidate"):
        consolidation_summary = variant.consolidate()

    if two_pass:
        # Pass 2: re-query to capture final canonicals
        preds = []
        for entry in workload:
            ctx = {"source_id": entry.source_id}
            canonical = variant.align_with_context(entry.input, ctx)
            preds.append((entry.input, canonical))
    else:
        raise RuntimeError(
            "single-pass via _run_variant is no longer supported; "
            "use _run_variant_single_pass for accurate latency measurement"
        )
    elapsed = time.perf_counter() - t0
    return preds, pre_preds, consolidation_summary, elapsed


def _run_variant_single_pass(variant, workload):
    """One-pass variant of _run_variant for UC-4.6 latency measurement.
    Predicted canonicals reflect the state AT the moment of each write,
    which is what latency benchmarks want."""
    t0 = time.perf_counter()
    preds = []
    for entry in workload:
        ctx = {"source_id": entry.source_id}
        canonical = variant.align_with_context(entry.input, ctx)
        preds.append((entry.input, canonical))
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


def _run_uc_4_7(args) -> int:
    """UC-4.7 lite — held-out generalization.

    Splits the workload into an ingestion set (first 1 - holdout_fraction)
    and a query set (the rest). The variant builds its canonical store on
    the ingestion set, then for each held-out query input, checks whether
    align() returns the same canonical as the variant assigned to the
    query input's oracle group during ingestion.

    Compared to UC-4.1 (which trains and tests on the same set), this is
    the basic generalization test: does the proxy correctly route unseen
    surface forms to the right existing canonical?

    A full UC-4.7 with a downstream retrieval system (per spec §3) needs
    a fact-and-query corpus like LongMemEval-S. This lite version uses
    the held-out subset of the same workload as a proxy for retrieval
    relevance.
    """
    workload = workloads.load(args.workload)
    workload_sha = artifacts.workload_sha256(
        [(e.input, e.oracle_canonical) for e in workload]
    )
    holdout = args.holdout_fraction
    if not 0 < holdout < 1:
        print("--holdout-fraction must be in (0, 1)", file=sys.stderr)
        return 2

    # Deterministic split: group by oracle canonical so each oracle group
    # gets a held-out item. Otherwise rare canonicals may have all items
    # in the ingestion set, leaving no queries for them.
    rng = random.Random(args.split_seed)
    by_oracle: dict[str, list] = {}
    for entry in workload:
        by_oracle.setdefault(entry.oracle_canonical, []).append(entry)
    ingestion: list = []
    queries: list = []
    for canonical, entries in by_oracle.items():
        if len(entries) < 2:
            ingestion.extend(entries)
            continue
        shuffled = list(entries)
        rng.shuffle(shuffled)
        n_query = max(1, int(round(len(shuffled) * holdout)))
        queries.extend(shuffled[:n_query])
        ingestion.extend(shuffled[n_query:])

    if not queries:
        print("Workload too small for hold-out split", file=sys.stderr)
        return 2

    variant_factory = variants.FACTORIES[args.variant]
    baseline_factory = variants.FACTORIES[args.baseline] if args.baseline else None

    def _ingest_and_query(factory) -> tuple[list[float], float]:
        """Returns per-query F1 contribution (0 or 1) and elapsed seconds."""
        v = factory()
        t0 = time.perf_counter()
        # Ingestion phase: build the canonical store.
        for entry in ingestion:
            v.align_with_context(entry.input, {"source_id": entry.source_id})
        # Record what canonical each oracle-cluster received during ingestion.
        oracle_to_canonical: dict[str, set[str]] = {}
        for entry in ingestion:
            c = v.align_with_context(entry.input, {"source_id": entry.source_id})
            oracle_to_canonical.setdefault(entry.oracle_canonical, set()).add(c)
        # Query phase: for each held-out query, get the variant's canonical
        # for that input and check it's in the set of canonicals already
        # assigned to that query's oracle group.
        correct: list[float] = []
        for entry in queries:
            c = v.align_with_context(entry.input, {"source_id": entry.source_id})
            expected = oracle_to_canonical.get(entry.oracle_canonical, set())
            correct.append(1.0 if c in expected else 0.0)
        elapsed = time.perf_counter() - t0
        return correct, elapsed

    var_correct, var_elapsed = _ingest_and_query(variant_factory)
    var_accuracy = sum(var_correct) / len(var_correct)

    test_executions = []
    if baseline_factory is not None:
        base_correct, base_elapsed = _ingest_and_query(baseline_factory)
        base_accuracy = sum(base_correct) / len(base_correct)
        diffs = [v - b for v, b in zip(var_correct, base_correct)]
        bs = stats.paired_bootstrap(diffs, n_resamples=args.bootstrap_resamples)
        test_executions.append({
            "test_seq_id": 1,
            "use_case": args.use_case,
            "metric_id": "uc_4_7_held_out_accuracy_diff",
            "type": "superiority",
            "statistical_test": "paired_bootstrap_held_out_accuracy",
            "n": bs.n,
            "point_estimate": bs.mean_diff,
            "always_valid_ci_lower": bs.ci_low,
            "always_valid_ci_upper": bs.ci_high,
            "ci_level": bs.ci_level,
            "p_value": bs.p_value_one_sided_gt,
            "diagnostics": {
                "variant_accuracy": var_accuracy,
                "baseline_accuracy": base_accuracy,
                "n_ingestion": len(ingestion),
                "n_queries": len(queries),
                "n_oracle_groups": len(by_oracle),
                "holdout_fraction": holdout,
                "variant_seconds": var_elapsed,
                "baseline_seconds": base_elapsed,
            },
        })
        ordered, ledger = run_ledger(test_executions, target_q=args.target_q)
        for t in ordered:
            t["outcome"] = _outcome_from_bootstrap(bs, t["alpha_allocated"])
        decision, _reasons = _pipeline_decision(ordered, tier=args.tier)
        test_executions = ordered
    else:
        # No baseline: report variant accuracy as informational.
        ledger = LordPlusPlusLedger(target_q=args.target_q)
        test_executions.append({
            "test_seq_id": 1,
            "use_case": args.use_case,
            "metric_id": "uc_4_7_held_out_accuracy",
            "type": "informational",
            "statistical_test": "raw_proportion",
            "n": len(queries),
            "point_estimate": var_accuracy,
            "alpha_allocated": 0.0,
            "outcome": "PASS",
            "diagnostics": {
                "variant_accuracy": var_accuracy,
                "n_ingestion": len(ingestion),
                "n_queries": len(queries),
                "n_oracle_groups": len(by_oracle),
                "holdout_fraction": holdout,
                "variant_seconds": var_elapsed,
            },
        })
        decision = "PASS_AND_MERGE"

    path = artifacts.emit(
        variant_name=variant_factory().name,
        baseline_name=baseline_factory().name if baseline_factory else "(none)",
        workload_id=args.workload,
        workload_sha=workload_sha,
        tier=args.tier,
        test_executions=test_executions,
        ledger=ledger,
        pipeline_decision=decision,
        out_dir=args.out_dir,
    )
    print(f"Wrote {path}")
    print(f"  variant {args.variant} on {args.workload}")
    print(f"  split: {len(ingestion)} ingestion, {len(queries)} held-out queries")
    print(f"  variant held-out accuracy: {var_accuracy:.4f}")
    if baseline_factory is not None:
        print(f"  baseline {args.baseline} held-out accuracy: {base_accuracy:.4f}")
        print(
            f"  paired diff: {test_executions[0]['point_estimate']:+.4f}, "
            f"CI [{test_executions[0]['always_valid_ci_lower']:+.4f}, "
            f"{test_executions[0]['always_valid_ci_upper']:+.4f}], "
            f"one-sided p={test_executions[0]['p_value']:.4f}"
        )
        print(f"  outcome: {test_executions[0]['outcome']}")
    print(f"  pipeline_decision: {decision}")
    return 0


def _run_uc_4_6(args) -> int:
    """UC-4.6 lite — per-write latency on a workload (single-thread).

    Measures the variant's latency at "no contention" (one request at a
    time, in process). This is the floor; a proper QPS sweep with
    concurrent load is a separate workstream.
    """
    workload = workloads.load(args.workload)
    workload_sha = artifacts.workload_sha256(
        [(e.input, e.oracle_canonical) for e in workload]
    )

    variant_factory = variants.FACTORIES[args.variant]
    v = variant_factory()
    # Warmup: first call often pays one-time init costs (e.g., embedder
    # model load). Discount the first N writes from the latency sample.
    warmup = min(50, len(workload) // 20)

    latencies_ms: list[float] = []
    t_total_start = time.perf_counter()
    for i, entry in enumerate(workload):
        ctx = {"source_id": entry.source_id}
        t0 = time.perf_counter()
        v.align_with_context(entry.input, ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if i >= warmup:
            latencies_ms.append(elapsed_ms)
    total_seconds = time.perf_counter() - t_total_start

    n = len(latencies_ms)
    sorted_lat = sorted(latencies_ms)
    def pct(p: float) -> float:
        idx = max(0, min(n - 1, int(round((p / 100) * n)) - 1))
        return sorted_lat[idx]

    p50 = pct(50)
    p95 = pct(95)
    p99 = pct(99)
    p999 = pct(99.9)
    mean = sum(latencies_ms) / n if n > 0 else 0.0
    qps_observed = (len(workload) - warmup) / total_seconds if total_seconds > 0 else 0.0

    # §3 UC-4.6 guardrail: p99 < 100 ms. This is at single-thread, no
    # contention; concurrent load could only raise it.
    p99_threshold_ms = args.latency_p99_threshold_ms
    outcome = "PASS" if p99 < p99_threshold_ms else "FAIL"

    test_executions = [
        {
            "test_seq_id": 1,
            "use_case": args.use_case,
            "metric_id": "uc_4_6_per_write_latency_ms",
            "type": "guardrail_kill_switch",
            "statistical_test": "raw_quantile",
            "n": n,
            "point_estimate": p99,
            "guardrail_threshold": p99_threshold_ms,
            "alpha_allocated": 0.0,
            "outcome": outcome,
            "diagnostics": {
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "p99_9_ms": p999,
                "mean_ms": mean,
                "writes_measured": n,
                "writes_warmed": warmup,
                "total_seconds": total_seconds,
                "qps_observed_single_thread": qps_observed,
            },
        }
    ]

    ledger = LordPlusPlusLedger(target_q=args.target_q)
    decision = "BLOCK_PR" if outcome == "FAIL" and args.tier == "fast" else (
        "SOFT_REGRESSION_OPENED" if outcome == "FAIL" else "PASS_AND_MERGE"
    )

    path = artifacts.emit(
        variant_name=v.name,
        baseline_name="(none, latency self-measurement)",
        workload_id=args.workload,
        workload_sha=workload_sha,
        tier=args.tier,
        test_executions=test_executions,
        ledger=ledger,
        pipeline_decision=decision,
        out_dir=args.out_dir,
    )
    print(f"Wrote {path}")
    print(f"  variant {v.name} on {args.workload}")
    print(f"  writes measured: {n} (warmup discounted: {warmup})")
    print(f"  latency ms — p50: {p50:.3f}, p95: {p95:.3f}, p99: {p99:.3f}, p99.9: {p999:.3f}, mean: {mean:.3f}")
    print(f"  observed throughput (single thread): {qps_observed:.0f} writes/sec")
    print(f"  guardrail p99 < {p99_threshold_ms} ms: {outcome}")
    print(f"  pipeline_decision: {decision}")
    return 0


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
    # UC-4.6-specific
    p.add_argument("--latency-p99-threshold-ms", type=float, default=100.0,
                   help="(UC-4.6 only) p99 latency kill-switch in ms "
                        "(default 100 ms per experiments.md §3 UC-4.6)")
    # UC-4.7-specific
    p.add_argument("--holdout-fraction", type=float, default=0.2,
                   help="(UC-4.7 only) fraction of each oracle group to hold "
                        "out for queries (default 0.2)")
    p.add_argument("--split-seed", type=int, default=0xC0FFEE,
                   help="(UC-4.7 only) deterministic split seed")
    args = p.parse_args(argv)

    if args.use_case == "UC-4.4":
        if not args.tier_b_fixture:
            print("UC-4.4 requires --tier-b-fixture", file=sys.stderr)
            return 2
        return _run_uc_4_4(args)
    if args.use_case == "UC-4.6":
        if not args.workload:
            print("UC-4.6 requires --workload", file=sys.stderr)
            return 2
        return _run_uc_4_6(args)
    if args.use_case == "UC-4.7":
        if not args.workload:
            print("UC-4.7 requires --workload", file=sys.stderr)
            return 2
        return _run_uc_4_7(args)

    # UC-4.1 path (existing logic)
    if not args.baseline or not args.workload:
        print("UC-4.1 requires --baseline and --workload", file=sys.stderr)
        return 2

    workload = workloads.load(args.workload)
    # Metrics and artifact helpers operate on (input, label) tuples;
    # extract the (input, oracle_canonical) view from the entries once.
    oracle_view = [(entry.input, entry.oracle_canonical) for entry in workload]
    workload_sha = artifacts.workload_sha256(oracle_view)

    var = variants.build(args.variant)
    base = variants.build(args.baseline)

    var_preds, var_pre_preds, var_consolidation, var_elapsed = _run_variant(var, workload)
    base_preds, base_pre_preds, base_consolidation, base_elapsed = _run_variant(base, workload)

    # drift_rate: fraction of entries where pre-consolidation prediction
    # differs from post-consolidation. Non-zero only for lazy variants.
    var_drift_rate = sum(
        1 for pre, post in zip(var_pre_preds, var_preds) if pre != post
    ) / len(var_preds) if var_preds else 0.0
    base_drift_rate = sum(
        1 for pre, post in zip(base_pre_preds, base_preds) if pre != post
    ) / len(base_preds) if base_preds else 0.0

    var_f1 = alignment.pairwise_f1(var_preds, oracle_view)
    base_f1 = alignment.pairwise_f1(base_preds, oracle_view)

    var_correct = alignment.per_item_correctness(var_preds, oracle_view)
    base_correct = alignment.per_item_correctness(base_preds, oracle_view)
    mc_b, mc_c = stats.mcnemar_discordant_counts(var_correct, base_correct)

    # Primary signal: per-item B-cubed F1. Each item gets a continuous
    # score in [0, 1]; paired bootstrap on the per-item difference. This
    # replaces both (a) per-item strict-cluster correctness, which is
    # degenerate at sub-perfect F1, and (b) an earlier attempt at
    # index-resampled pairwise F1 bootstrap, which suffers from
    # bootstrap-duplicate-pair pathology on pair-level metrics.
    var_bcubed = alignment.per_item_bcubed_f1(var_preds, oracle_view)
    base_bcubed = alignment.per_item_bcubed_f1(base_preds, oracle_view)
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
                "variant_drift_rate": var_drift_rate,
                "baseline_drift_rate": base_drift_rate,
                "variant_consolidation": var_consolidation,
                "baseline_consolidation": base_consolidation,
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

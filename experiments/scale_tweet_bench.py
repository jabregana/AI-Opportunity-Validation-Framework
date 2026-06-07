"""Scaled real-data bench with bootstrap CIs.

Runs the same comparison as real_dataset_bench but at N=500 (50 tweets
per entity × 10 entities). Adds per-tweet binary metrics so we can
bootstrap-CI the surface-variant reduction and accuracy lift.

Per-tweet metrics:
  - llm_picked_correct (binary): canonicalize the LLM output via the
    map; did it match the oracle entity?
  - llm_output_is_canonical (binary): did the LLM's output equal the
    canonical name (vs a surface variant)?

Aggregates and bootstrap CIs computed via runner.metrics.stats.paired_bootstrap.

Run:
  .venv/bin/python experiments/scale_tweet_bench.py --per-entity 50
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.real_dataset_bench import (
    ENTITIES_REAL,
    build_alias_map,
    canonicalize_for_scoring,
    load_filtered_tweets,
    run_condition,
)
from runner.metrics.stats import paired_bootstrap


def per_tweet_correct(extractions: list[dict], alias_map: dict[str, str]) -> list[int]:
    """1 if canonicalized LLM output matches oracle, else 0."""
    return [
        1 if canonicalize_for_scoring(ex["llm_extracted"], alias_map) == ex["oracle"]
        else 0
        for ex in extractions
    ]


def per_tweet_canonical(extractions: list[dict],
                        canonical_names: set[str]) -> list[int]:
    """1 if the LLM's raw output is exactly a canonical name (not a
    surface variant), else 0."""
    return [
        1 if ex["llm_extracted"].strip() in canonical_names else 0
        for ex in extractions
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scale-tweet-bench")
    parser.add_argument("--per-entity", type=int, default=50)
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--n-bootstrap", type=int, default=2000)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"scale_tweet_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    alias_map = build_alias_map()
    canonical_names = set(alias_map.values())
    print(f"Alias map: {len(alias_map)} aliases / "
          f"{len(canonical_names)} canonical entities")
    print(f"Target: {args.per_entity} tweets per entity = "
          f"~{args.per_entity * len(canonical_names)} total")

    by_entity = load_filtered_tweets(args.per_entity, alias_map)
    tweets = []
    for canonical, tw_list in by_entity.items():
        for tw in tw_list:
            tw["oracle"] = canonical
            tweets.append(tw)
    print(f"Loaded {len(tweets)} real tweets")
    for canonical, tw_list in by_entity.items():
        print(f"  {canonical:22} {len(tw_list)}")

    print(f"\nModel: {args.model}")
    print(f"Will make ~{2 * len(tweets)} total LLM calls "
          f"(~{2 * len(tweets) * 0.15 / 60:.1f} min at 150ms/call)")

    no_p = run_condition(args.model, tweets, "no_proxy", False, alias_map)
    yes_p = run_condition(args.model, tweets, "with_proxy", True, alias_map)

    # Per-tweet binary metrics
    no_correct = per_tweet_correct(no_p["extractions"], alias_map)
    yes_correct = per_tweet_correct(yes_p["extractions"], alias_map)
    no_canonical = per_tweet_canonical(no_p["extractions"], canonical_names)
    yes_canonical = per_tweet_canonical(yes_p["extractions"], canonical_names)

    # Aggregates
    n = len(tweets)
    no_acc = sum(no_correct) / n
    yes_acc = sum(yes_correct) / n
    no_canon = sum(no_canonical) / n
    yes_canon = sum(yes_canonical) / n

    # Bootstrap CIs on the paired difference. paired_bootstrap takes a
    # single pre-computed diffs list, so compute (with_proxy - no_proxy)
    # per tweet first.
    diffs_correct = [y - n for y, n in zip(yes_correct, no_correct)]
    diffs_canon = [y - n for y, n in zip(yes_canonical, no_canonical)]
    print(f"\nBootstrapping {args.n_bootstrap} resamples on each diff...")
    res_c = paired_bootstrap(diffs_correct, n_resamples=args.n_bootstrap, seed=42)
    res_q = paired_bootstrap(diffs_canon, n_resamples=args.n_bootstrap, seed=43)
    diff_correct, lo_c, hi_c = res_c.mean_diff, res_c.ci_low, res_c.ci_high
    p1_c, p2_c = res_c.p_value_one_sided_gt, res_c.p_value_two_sided
    diff_canon, lo_q, hi_q = res_q.mean_diff, res_q.ci_low, res_q.ci_high
    p1_q, p2_q = res_q.p_value_one_sided_gt, res_q.p_value_two_sided

    # Per-entity surface-variant counts
    no_outputs_by_oracle: dict[str, set[str]] = {}
    yes_outputs_by_oracle: dict[str, set[str]] = {}
    for ex in no_p["extractions"]:
        no_outputs_by_oracle.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])
    for ex in yes_p["extractions"]:
        yes_outputs_by_oracle.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])

    print("\n" + "=" * 70)
    print(f"Summary — scaled tweet bench, N={n} (per-entity bootstrap CIs)")
    print("=" * 70)
    print(f"  Entity-identification accuracy (canonicalized):")
    print(f"    no proxy:    {no_acc:.3f}")
    print(f"    with proxy:  {yes_acc:.3f}")
    print(f"    Δ: {diff_correct:+.4f}  95% CI [{lo_c:+.4f}, {hi_c:+.4f}]  "
          f"one-sided p={p1_c:.4f}")
    print(f"\n  LLM output exactly matches a canonical name:")
    print(f"    no proxy:    {no_canon:.3f}")
    print(f"    with proxy:  {yes_canon:.3f}")
    print(f"    Δ: {diff_canon:+.4f}  95% CI [{lo_q:+.4f}, {hi_q:+.4f}]  "
          f"one-sided p={p1_q:.4f}")

    print(f"\n  Per-entity unique surface forms in LLM output:")
    print(f"  {'entity':22} {'no proxy':>10} {'with proxy':>12}")
    total_no = 0
    total_yes = 0
    for canonical in sorted(set(t["oracle"] for t in tweets)):
        no_v = len(no_outputs_by_oracle.get(canonical, set()))
        yes_v = len(yes_outputs_by_oracle.get(canonical, set()))
        total_no += no_v
        total_yes += yes_v
        print(f"  {canonical:22} {no_v:>10} {yes_v:>12}")
    print(f"  {'TOTAL':22} {total_no:>10} {total_yes:>12}")
    pct = 100.0 * (total_no - total_yes) / total_no if total_no > 0 else 0
    print(f"  Surface-variant reduction: {total_no - total_yes} ({pct:+.1f}%)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "n_tweets": n,
        "n_canonicals": len(canonical_names),
        "accuracy": {
            "no_proxy": no_acc,
            "with_proxy": yes_acc,
            "diff": diff_correct,
            "ci_95_lo": lo_c,
            "ci_95_hi": hi_c,
            "p_one_sided": p1_c,
            "p_two_sided": p2_c,
        },
        "canonical_output_rate": {
            "no_proxy": no_canon,
            "with_proxy": yes_canon,
            "diff": diff_canon,
            "ci_95_lo": lo_q,
            "ci_95_hi": hi_q,
            "p_one_sided": p1_q,
            "p_two_sided": p2_q,
        },
        "surface_variants": {
            "no_proxy_total": total_no,
            "with_proxy_total": total_yes,
            "reduction_pct": pct,
        },
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Real-data benchmark: proxy lift on naturally-occurring text.

Uses the Twitter Financial News dataset (zeroshot/twitter-financial-news-topic)
as a source of real, human-written text mentioning real companies under
multiple surface forms. Replaces the synthetic single-sentence /
multi-turn dialogues from prior benches.

Method:
  1. Load the validation split (~4k tweets).
  2. Filter to tweets mentioning at least one entity from a known set
     of well-known public companies (with multiple known aliases each).
  3. Sample N tweets per entity for a balanced workload.
  4. For each tweet, ask llama3.1:8b to extract distinct companies
     mentioned. Run with and without the proxy's mention_map.
  5. Compare: per-entity surface-variant count in the LLM's outputs.
     Fewer unique surface forms per real entity = more coherent
     output.

The honest comparison: the proxy normalizes known aliases before the
LLM sees them; the LLM should then produce fewer surface variants
per real entity in its extraction output.

Run:
  .venv/bin/python experiments/real_dataset_bench.py
  .venv/bin/python experiments/real_dataset_bench.py --per-entity 5
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

from experiments.small_llm_quality_bench import (
    EXTRACTION_PROMPT,
    llm_extract,
    pre_normalize,
)


# Real entities present in financial Twitter, with the surface forms
# they commonly appear under. Larger / more naturalistic alias set
# than the synthetic bench (no synthetic "_Inc" suffix variants).
ENTITIES_REAL = {
    "Apple Inc": ["Apple", "AAPL", "$AAPL"],
    "Microsoft Corp": ["Microsoft", "MSFT", "$MSFT"],
    "Tesla Inc": ["Tesla", "TSLA", "$TSLA"],
    "Nvidia Corp": ["Nvidia", "NVDA", "$NVDA"],
    "Alphabet Inc": ["Google", "Alphabet", "GOOGL", "$GOOGL", "GOOG"],
    "Amazon Inc": ["Amazon", "AMZN", "$AMZN"],
    "Meta Platforms": ["Meta", "Facebook", "META", "$META", "FB"],
    "JPMorgan Chase": ["JPMorgan", "JPM", "JP Morgan"],
    "Goldman Sachs": ["Goldman", "Goldman Sachs", "GS", "$GS"],
    "Morgan Stanley": ["Morgan Stanley", "MS"],
}


def build_alias_map() -> dict[str, str]:
    out = {}
    for canonical, aliases in ENTITIES_REAL.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def load_filtered_tweets(per_entity: int, alias_map: dict[str, str]):
    """Load Twitter Financial News, filter to tweets mentioning at least
    one known alias. Returns up to `per_entity` tweets per entity for a
    balanced workload, plus the entity-of-interest for each tweet."""
    from datasets import load_dataset

    ds = load_dataset("zeroshot/twitter-financial-news-topic", split="validation")
    by_entity: dict[str, list[str]] = {c: [] for c in set(alias_map.values())}

    aliases_longest_first = sorted(alias_map, key=len, reverse=True)
    import re
    pattern = re.compile(
        r"(?:^|\s|[^\w$])(" + "|".join(re.escape(a) for a in aliases_longest_first) + r")(?:$|[^\w])"
    )
    for example in ds:
        text = example["text"]
        match = pattern.search(text)
        if not match:
            continue
        alias = match.group(1)
        canonical = alias_map[alias]
        if len(by_entity[canonical]) >= per_entity:
            continue
        by_entity[canonical].append({"text": text, "primary_alias": alias})
        if all(len(v) >= per_entity for v in by_entity.values()):
            break

    return by_entity


def run_condition(model: str, tweets: list[dict], label: str,
                  with_proxy: bool, alias_map: dict[str, str]):
    print(f"\n=== Condition: {label} ===")
    extractions = []
    t0 = time.perf_counter()
    for tw in tweets:
        text = tw["text"]
        if with_proxy:
            text = pre_normalize(text, alias_map)
        extracted = llm_extract(model, text)
        extractions.append({
            "original_text": tw["text"],
            "primary_alias": tw.get("primary_alias"),
            "oracle": tw.get("oracle"),
            "preprocessed": text if with_proxy else None,
            "llm_extracted": extracted,
        })
    elapsed = time.perf_counter() - t0
    return {"label": label, "elapsed_s": elapsed, "extractions": extractions}


def canonicalize_for_scoring(s: str, alias_map: dict[str, str]) -> str:
    """Apply alias map to the LLM's raw output so we can compare conditions
    on a consistent canonical form (otherwise no-proxy is unfairly
    penalized for outputting "AAPL" when the oracle is "Apple Inc")."""
    return alias_map.get(s.strip(), s.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="real-dataset-bench")
    parser.add_argument("--per-entity", type=int, default=4,
                        help="tweets per entity (default 4, total ~40 tweets)")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"real_dataset_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    alias_map = build_alias_map()
    print(f"Alias map: {len(alias_map)} aliases over "
          f"{len(set(alias_map.values()))} canonical entities")
    print(f"Loading Twitter Financial News validation split, "
          f"filtering to {args.per_entity} tweets per entity...")
    by_entity = load_filtered_tweets(args.per_entity, alias_map)

    tweets = []
    for canonical, tw_list in by_entity.items():
        for tw in tw_list:
            tw["oracle"] = canonical
            tweets.append(tw)
    print(f"Loaded {len(tweets)} real tweets:")
    for canonical, tw_list in by_entity.items():
        print(f"  {canonical:20} {len(tw_list)} tweets")

    print(f"\nModel: {args.model}")
    no_p = run_condition(args.model, tweets, "no_proxy", False, alias_map)
    yes_p = run_condition(args.model, tweets, "with_proxy", True, alias_map)

    # Compute per-canonical surface-variant counts in LLM outputs.
    print("\n" + "=" * 70)
    print("Surface variants per real entity in LLM extraction output")
    print("(lower = more coherent; ideal = 1 surface form per entity)")
    print("=" * 70)
    print(f"  {'entity':22} {'no proxy variants':>20} {'with proxy variants':>22}")

    no_outputs_by_oracle: dict[str, set[str]] = {}
    yes_outputs_by_oracle: dict[str, set[str]] = {}
    for ex in no_p["extractions"]:
        no_outputs_by_oracle.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])
    for ex in yes_p["extractions"]:
        yes_outputs_by_oracle.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])

    total_no_variants = 0
    total_yes_variants = 0
    for canonical in sorted(set(t["oracle"] for t in tweets)):
        no_var = len(no_outputs_by_oracle.get(canonical, set()))
        yes_var = len(yes_outputs_by_oracle.get(canonical, set()))
        total_no_variants += no_var
        total_yes_variants += yes_var
        print(f"  {canonical:22} {no_var:>20} {yes_var:>22}")
    print(f"  {'TOTAL':22} {total_no_variants:>20} {total_yes_variants:>22}")
    delta = total_no_variants - total_yes_variants
    pct = 100.0 * delta / total_no_variants if total_no_variants > 0 else 0
    print(f"\nSurface-variant reduction: {delta} ({pct:+.1f}%)")

    # Also compute extraction precision: fraction of LLM outputs that
    # match the tweet's primary entity (after canonicalization).
    no_correct = sum(
        1 for ex in no_p["extractions"]
        if canonicalize_for_scoring(ex["llm_extracted"], alias_map) == ex["oracle"]
    )
    yes_correct = sum(
        1 for ex in yes_p["extractions"]
        if canonicalize_for_scoring(ex["llm_extracted"], alias_map) == ex["oracle"]
    )
    print(f"\nLLM picked the right entity (canonicalized):")
    print(f"  no proxy:   {no_correct} / {len(tweets)} ({100*no_correct/len(tweets):.1f}%)")
    print(f"  with proxy: {yes_correct} / {len(tweets)} ({100*yes_correct/len(tweets):.1f}%)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "n_tweets": len(tweets),
        "n_canonicals": len(set(t["oracle"] for t in tweets)),
        "alias_map_size": len(alias_map),
        "total_no_proxy_variants": total_no_variants,
        "total_with_proxy_variants": total_yes_variants,
        "surface_variant_reduction_pct": pct,
        "no_proxy_correct": no_correct,
        "with_proxy_correct": yes_correct,
        "no_proxy": no_p,
        "with_proxy": yes_p,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

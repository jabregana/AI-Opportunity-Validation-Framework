"""Production case study: 50-entity financial alias map on real text.

Curated alias map covering the top 30 S&P 500 companies by market cap,
10 major financial institutions, and 10 major indices/ETFs. Each entity
has the canonical name plus 3-8 surface forms (ticker, $-prefixed
ticker, short name, alternative names).

This is the realistic deployment shape for a "financial chat
assistant" or "trading desk memory" integration: a domain-specific
alias map maintained by the integrator, with the proxy as the
deterministic substitution layer.

Bench:
  - Load Twitter Financial News validation (4117 tweets).
  - Filter to tweets mentioning at least one entity in the curated map.
  - Sample up to N per entity for balanced coverage.
  - Run llama3.1:8b extraction with and without the curated map.
  - Report surface-variant reduction, entity-identification accuracy,
    and confidence intervals.

Run:
  .venv/bin/python experiments/case_study_financial.py
  .venv/bin/python experiments/case_study_financial.py --per-entity 30
"""
from __future__ import annotations
import argparse
import json
import re
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
from runner.metrics.stats import paired_bootstrap


# 50-entity curated financial alias map.
# Format: canonical_name -> [list of surface forms].
CURATED_ENTITIES: dict[str, list[str]] = {
    # Top tech (Mag 7 + adjacent)
    "Apple Inc": ["Apple", "AAPL", "$AAPL", "Apple Computer"],
    "Microsoft Corp": ["Microsoft", "MSFT", "$MSFT", "MS Corp"],
    "Nvidia Corp": ["Nvidia", "NVDA", "$NVDA", "NVIDIA"],
    "Alphabet Inc": ["Google", "Alphabet", "GOOGL", "$GOOGL", "GOOG", "$GOOG"],
    "Amazon Inc": ["Amazon", "AMZN", "$AMZN", "Amazon.com"],
    "Meta Platforms": ["Meta", "Facebook", "META", "$META", "FB"],
    "Tesla Inc": ["Tesla", "TSLA", "$TSLA", "Tesla Motors"],
    "Netflix Inc": ["Netflix", "NFLX", "$NFLX"],
    "Adobe Inc": ["Adobe", "ADBE", "$ADBE"],
    "Salesforce Inc": ["Salesforce", "CRM", "$CRM", "SFDC", "Salesforce.com"],
    "Oracle Corp": ["Oracle", "ORCL", "$ORCL"],
    "Intel Corp": ["Intel", "INTC", "$INTC"],
    "AMD": ["AMD", "$AMD", "Advanced Micro Devices"],
    "IBM": ["IBM", "$IBM", "International Business Machines"],
    "Cisco Systems": ["Cisco", "CSCO", "$CSCO"],
    # Top finance
    "JPMorgan Chase": ["JPMorgan", "JPM", "$JPM", "JP Morgan", "Chase"],
    "Goldman Sachs": ["Goldman", "Goldman Sachs", "GS", "$GS"],
    "Morgan Stanley": ["Morgan Stanley", "MS"],
    "Bank of America": ["Bank of America", "BofA", "BAC", "$BAC", "BoA"],
    "Wells Fargo": ["Wells Fargo", "WFC", "$WFC", "Wells"],
    "Citigroup": ["Citi", "Citigroup", "C", "$C", "Citibank"],
    "BlackRock Inc": ["BlackRock", "BLK", "$BLK"],
    "Berkshire Hathaway": ["Berkshire", "BRK", "$BRK", "Berkshire Hathaway"],
    "American Express": ["AmEx", "American Express", "AXP", "$AXP", "Amex"],
    "Visa Inc": ["Visa", "V", "$V"],
    # Healthcare / consumer
    "Johnson & Johnson": ["JNJ", "$JNJ", "Johnson & Johnson", "J&J"],
    "Pfizer Inc": ["Pfizer", "PFE", "$PFE"],
    "Eli Lilly": ["Lilly", "Eli Lilly", "LLY", "$LLY"],
    "UnitedHealth Group": ["UnitedHealth", "UNH", "$UNH"],
    "Walmart Inc": ["Walmart", "WMT", "$WMT"],
    "Costco": ["Costco", "COST", "$COST"],
    "Procter & Gamble": ["P&G", "Procter & Gamble", "PG", "$PG"],
    "Coca-Cola Co": ["Coca-Cola", "Coke", "KO", "$KO"],
    "PepsiCo": ["PepsiCo", "Pepsi", "PEP", "$PEP"],
    "McDonald's": ["McDonald's", "MCD", "$MCD", "McDonalds"],
    # Energy / industrial
    "ExxonMobil": ["ExxonMobil", "Exxon", "XOM", "$XOM"],
    "Chevron Corp": ["Chevron", "CVX", "$CVX"],
    "Boeing Co": ["Boeing", "BA", "$BA"],
    "Caterpillar Inc": ["Caterpillar", "CAT", "$CAT"],
    "General Electric": ["GE", "$GE", "General Electric"],
    # Indices and ETFs
    "S&P 500": ["S&P 500", "SPX", "$SPX", "SPY", "$SPY", "S&P", "SP500"],
    "Nasdaq 100": ["Nasdaq 100", "NDX", "$NDX", "QQQ", "$QQQ", "Nasdaq"],
    "Dow Jones": ["Dow Jones", "DJIA", "$DJIA", "DIA", "Dow"],
    "Russell 2000": ["Russell 2000", "RUT", "IWM", "$IWM"],
    "VIX": ["VIX", "$VIX", "VIX Index", "volatility index"],
    # Crypto-adjacent / fintech
    "Coinbase": ["Coinbase", "COIN", "$COIN"],
    "PayPal": ["PayPal", "PYPL", "$PYPL"],
    "Square Inc": ["Square", "Block", "SQ", "$SQ"],
    "Robinhood": ["Robinhood", "HOOD", "$HOOD"],
    "Roku Inc": ["Roku", "ROKU", "$ROKU"],
}


def build_alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in CURATED_ENTITIES.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def load_filtered_tweets(per_entity: int, alias_map: dict[str, str]):
    from datasets import load_dataset
    ds = load_dataset("zeroshot/twitter-financial-news-topic", split="validation")
    by_entity: dict[str, list[dict]] = {c: [] for c in set(alias_map.values())}
    aliases_longest_first = sorted(alias_map, key=len, reverse=True)
    pattern = re.compile(
        r"(?:^|\s|[^\w$])(" + "|".join(re.escape(a) for a in aliases_longest_first)
        + r")(?:$|[^\w])"
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
        by_entity[canonical].append({"text": text, "primary_alias": alias,
                                     "oracle": canonical})
    return by_entity


def run_condition(model: str, tweets: list[dict], with_proxy: bool,
                  alias_map: dict[str, str]):
    extractions = []
    t0 = time.perf_counter()
    for tw in tweets:
        text = tw["text"]
        if with_proxy:
            text = pre_normalize(text, alias_map)
        extracted = llm_extract(model, text)
        extractions.append({
            "original_text": tw["text"],
            "primary_alias": tw["primary_alias"],
            "oracle": tw["oracle"],
            "llm_extracted": extracted,
        })
    elapsed = time.perf_counter() - t0
    return {"elapsed_s": elapsed, "extractions": extractions}


def canonicalize(s: str, alias_map: dict[str, str]) -> str:
    return alias_map.get(s.strip(), s.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="case-study-financial")
    parser.add_argument("--per-entity", type=int, default=20,
                        help="max tweets per entity (default 20, ~1000 total)")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"case_study_financial_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    alias_map = build_alias_map()
    canonicals = sorted(set(alias_map.values()))
    print(f"Curated map: {len(alias_map)} aliases over "
          f"{len(canonicals)} canonical entities")
    print(f"Target: up to {args.per_entity} tweets per entity")
    print(f"Loading Twitter Financial News validation, filtering...")
    by_entity = load_filtered_tweets(args.per_entity, alias_map)
    tweets = [t for tw_list in by_entity.values() for t in tw_list]
    print(f"Loaded {len(tweets)} real tweets across "
          f"{sum(1 for v in by_entity.values() if v)} entities with coverage")

    entities_with_data = [(c, len(v)) for c, v in by_entity.items() if v]
    print("Coverage (entities with tweets):")
    for c, n in sorted(entities_with_data, key=lambda x: -x[1])[:15]:
        print(f"  {c:24} {n}")
    if len(entities_with_data) > 15:
        print(f"  ... and {len(entities_with_data) - 15} more")

    print(f"\nModel: {args.model}")
    print(f"Will make ~{2 * len(tweets)} LLM calls "
          f"(~{2 * len(tweets) * 0.15 / 60:.1f} min)")

    no_p = run_condition(args.model, tweets, False, alias_map)
    yes_p = run_condition(args.model, tweets, True, alias_map)

    # Per-tweet correctness
    no_correct = [
        1 if canonicalize(ex["llm_extracted"], alias_map) == ex["oracle"] else 0
        for ex in no_p["extractions"]
    ]
    yes_correct = [
        1 if canonicalize(ex["llm_extracted"], alias_map) == ex["oracle"] else 0
        for ex in yes_p["extractions"]
    ]
    n = len(tweets)
    no_acc = sum(no_correct) / n
    yes_acc = sum(yes_correct) / n

    # Bootstrap
    diffs = [y - x for y, x in zip(yes_correct, no_correct)]
    print(f"\nBootstrapping {2000} resamples on accuracy diff...")
    res = paired_bootstrap(diffs, n_resamples=2000, seed=42)

    # Surface variants per entity
    no_var = {}
    yes_var = {}
    for ex in no_p["extractions"]:
        no_var.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])
    for ex in yes_p["extractions"]:
        yes_var.setdefault(ex["oracle"], set()).add(ex["llm_extracted"])
    total_no_var = sum(len(v) for v in no_var.values())
    total_yes_var = sum(len(v) for v in yes_var.values())

    print("\n" + "=" * 70)
    print(f"PRODUCTION CASE STUDY — Financial chat / trading desk")
    print(f"  Curated map: {len(alias_map)} aliases / {len(canonicals)} entities")
    print(f"  Real workload: {len(tweets)} Twitter Financial News tweets")
    print(f"  Model: {args.model}")
    print("=" * 70)
    print(f"\n  Entity-identification accuracy (canonicalized):")
    print(f"    no proxy:    {no_acc:.3f}   ({sum(no_correct)}/{n})")
    print(f"    with proxy:  {yes_acc:.3f}   ({sum(yes_correct)}/{n})")
    print(f"    Δ: {res.mean_diff:+.4f}  95% CI [{res.ci_low:+.4f}, {res.ci_high:+.4f}]  "
          f"one-sided p={res.p_value_one_sided_gt:.4f}")
    print(f"\n  Surface-variant fragmentation:")
    pct = 100 * (total_no_var - total_yes_var) / total_no_var if total_no_var > 0 else 0
    print(f"    no proxy:    {total_no_var} unique outputs")
    print(f"    with proxy:  {total_yes_var} unique outputs ({pct:+.1f}%)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "n_tweets": n,
        "n_entities_with_data": sum(1 for v in by_entity.values() if v),
        "n_canonicals_total": len(canonicals),
        "alias_map_size": len(alias_map),
        "accuracy": {
            "no_proxy": no_acc,
            "with_proxy": yes_acc,
            "diff": res.mean_diff,
            "ci_95_lo": res.ci_low,
            "ci_95_hi": res.ci_high,
            "p_one_sided": res.p_value_one_sided_gt,
        },
        "surface_variants": {
            "no_proxy": total_no_var,
            "with_proxy": total_yes_var,
            "reduction_pct": pct,
        },
        "coverage": {c: len(v) for c, v in by_entity.items() if v},
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

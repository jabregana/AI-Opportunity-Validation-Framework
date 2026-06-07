"""Expanded case study: 100+ entity financial alias map for substantial N.

Bigger than case_study_financial.py (50 entities). This pushes the
sample size up by covering more of the entities that actually appear
in Twitter Financial News, addressing the "small N" pressure test.

The alias map covers:
  - S&P 500 large-caps: tech (Mag 7+), finance, healthcare, energy, industrial,
    consumer, communications (~70 companies)
  - Top ETFs and indices (~10)
  - Regional/international banks, financial services (~10)
  - Crypto-adjacent and fintech (~10)
  - Recent / popular tickers (~10)

Goal: expand from 269 matched tweets (34-alias map) to 1000+ matched tweets.

Run:
  .venv/bin/python experiments/case_study_expanded.py --per-entity 30
  .venv/bin/python experiments/case_study_expanded.py --per-entity 30 --models qwen2.5:3b,llama3.2:3b,gpt-4o
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

from experiments.ladder_sweep_real_data import (
    run_model,
    _route_extractor,
)
from experiments.small_llm_quality_bench import (
    EXTRACTION_PROMPT,
    llm_extract as ollama_extract,
    pre_normalize,
)
from runner.metrics.stats import paired_bootstrap


# ~120 entities, ~400+ aliases covering the major surface forms in
# financial news / Twitter. Designed to maximize matching coverage on
# Twitter Financial News while staying canonical (each entity has the
# obvious ticker, $-ticker, bare name, and a short-name variant).
CURATED_ENTITIES: dict[str, list[str]] = {
    # === Mag 7 + adjacent tech ===
    "Apple Inc": ["Apple", "AAPL", "$AAPL", "Apple Computer"],
    "Microsoft Corp": ["Microsoft", "MSFT", "$MSFT", "MS Corp"],
    "Nvidia Corp": ["Nvidia", "NVDA", "$NVDA", "NVIDIA"],
    "Alphabet Inc": ["Google", "Alphabet", "GOOGL", "$GOOGL", "GOOG", "$GOOG"],
    "Amazon Inc": ["Amazon", "AMZN", "$AMZN", "Amazon.com"],
    "Meta Platforms": ["Meta", "Facebook", "META", "$META", "FB"],
    "Tesla Inc": ["Tesla", "TSLA", "$TSLA", "Tesla Motors"],
    # === Big tech beyond Mag 7 ===
    "Netflix Inc": ["Netflix", "NFLX", "$NFLX"],
    "Adobe Inc": ["Adobe", "ADBE", "$ADBE"],
    "Salesforce Inc": ["Salesforce", "CRM", "$CRM", "SFDC"],
    "Oracle Corp": ["Oracle", "ORCL", "$ORCL"],
    "Intel Corp": ["Intel", "INTC", "$INTC"],
    "AMD": ["AMD", "$AMD", "Advanced Micro Devices"],
    "IBM": ["IBM", "$IBM", "International Business Machines"],
    "Cisco Systems": ["Cisco", "CSCO", "$CSCO"],
    "Broadcom Inc": ["Broadcom", "AVGO", "$AVGO"],
    "Qualcomm Inc": ["Qualcomm", "QCOM", "$QCOM"],
    "Texas Instruments": ["TI", "Texas Instruments", "TXN", "$TXN"],
    "Micron Technology": ["Micron", "MU", "$MU"],
    "Applied Materials": ["Applied Materials", "AMAT", "$AMAT"],
    "ServiceNow": ["ServiceNow", "NOW", "$NOW"],
    "Snowflake Inc": ["Snowflake", "SNOW", "$SNOW"],
    "Palantir": ["Palantir", "PLTR", "$PLTR"],
    "Workday Inc": ["Workday", "WDAY", "$WDAY"],
    # === Top finance / banks ===
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
    "Mastercard Inc": ["Mastercard", "MA", "$MA"],
    "Charles Schwab": ["Schwab", "Charles Schwab", "SCHW", "$SCHW"],
    "U.S. Bancorp": ["US Bancorp", "USB", "$USB"],
    "Capital One": ["Capital One", "COF", "$COF"],
    "PNC Financial": ["PNC", "$PNC"],
    "Truist Financial": ["Truist", "TFC", "$TFC"],
    # === Healthcare / pharma / consumer ===
    "Johnson & Johnson": ["JNJ", "$JNJ", "Johnson & Johnson", "J&J"],
    "Pfizer Inc": ["Pfizer", "PFE", "$PFE"],
    "Eli Lilly": ["Lilly", "Eli Lilly", "LLY", "$LLY"],
    "UnitedHealth Group": ["UnitedHealth", "UNH", "$UNH"],
    "Merck & Co": ["Merck", "MRK", "$MRK"],
    "AbbVie Inc": ["AbbVie", "ABBV", "$ABBV"],
    "Bristol Myers Squibb": ["Bristol Myers", "BMY", "$BMY"],
    "Walmart Inc": ["Walmart", "WMT", "$WMT"],
    "Costco": ["Costco", "COST", "$COST"],
    "Procter & Gamble": ["P&G", "Procter & Gamble", "PG", "$PG"],
    "Coca-Cola Co": ["Coca-Cola", "Coke", "KO", "$KO"],
    "PepsiCo": ["PepsiCo", "Pepsi", "PEP", "$PEP"],
    "McDonald's": ["McDonald's", "MCD", "$MCD", "McDonalds"],
    "Nike Inc": ["Nike", "NKE", "$NKE"],
    "Starbucks": ["Starbucks", "SBUX", "$SBUX"],
    "Target Corp": ["Target", "TGT", "$TGT"],
    "Home Depot": ["Home Depot", "HD", "$HD"],
    "Lowe's": ["Lowe's", "LOW", "$LOW", "Lowes"],
    "CVS Health": ["CVS", "$CVS", "CVS Health"],
    # === Energy / industrial / materials ===
    "ExxonMobil": ["ExxonMobil", "Exxon", "XOM", "$XOM"],
    "Chevron Corp": ["Chevron", "CVX", "$CVX"],
    "ConocoPhillips": ["ConocoPhillips", "COP", "$COP", "Conoco"],
    "Occidental Petroleum": ["Occidental", "OXY", "$OXY"],
    "Schlumberger": ["Schlumberger", "SLB", "$SLB"],
    "Boeing Co": ["Boeing", "BA", "$BA"],
    "Caterpillar Inc": ["Caterpillar", "CAT", "$CAT"],
    "General Electric": ["GE", "$GE", "General Electric"],
    "Honeywell": ["Honeywell", "HON", "$HON"],
    "Lockheed Martin": ["Lockheed", "LMT", "$LMT", "Lockheed Martin"],
    "Raytheon": ["Raytheon", "RTX", "$RTX"],
    "3M Company": ["3M", "MMM", "$MMM"],
    # === Communications / media ===
    "Walt Disney": ["Disney", "DIS", "$DIS"],
    "Comcast Corp": ["Comcast", "CMCSA", "$CMCSA"],
    "Verizon": ["Verizon", "VZ", "$VZ"],
    "AT&T Inc": ["AT&T", "T", "$T", "ATT"],
    "T-Mobile US": ["T-Mobile", "TMUS", "$TMUS"],
    # === Indices and ETFs ===
    "S&P 500": ["S&P 500", "SPX", "$SPX", "SPY", "$SPY", "S&P", "SP500", "S&P500"],
    "Nasdaq 100": ["Nasdaq 100", "NDX", "$NDX", "QQQ", "$QQQ", "Nasdaq"],
    "Dow Jones": ["Dow Jones", "DJIA", "$DJIA", "DIA", "Dow"],
    "Russell 2000": ["Russell 2000", "RUT", "IWM", "$IWM"],
    "VIX": ["VIX", "$VIX", "VIX Index", "volatility index"],
    "VOO": ["VOO", "$VOO"],
    "VTI": ["VTI", "$VTI"],
    "ARKK": ["ARKK", "$ARKK", "ARK Innovation"],
    # === Crypto / fintech ===
    "Bitcoin": ["Bitcoin", "BTC", "$BTC"],
    "Ethereum": ["Ethereum", "ETH", "$ETH"],
    "Coinbase": ["Coinbase", "COIN", "$COIN"],
    "PayPal": ["PayPal", "PYPL", "$PYPL"],
    "Square Inc": ["Square", "Block", "SQ", "$SQ"],
    "Robinhood": ["Robinhood", "HOOD", "$HOOD"],
    "MicroStrategy": ["MicroStrategy", "MSTR", "$MSTR"],
    # === Auto / EV ===
    "Ford Motor": ["Ford", "F", "$F"],
    "General Motors": ["GM", "$GM", "General Motors"],
    "Rivian": ["Rivian", "RIVN", "$RIVN"],
    "Lucid Group": ["Lucid", "LCID", "$LCID"],
    "Stellantis": ["Stellantis", "STLA", "$STLA"],
    # === Recent / popular / meme tickers ===
    "GameStop": ["GameStop", "GME", "$GME"],
    "AMC Entertainment": ["AMC", "$AMC", "AMC Entertainment"],
    "Roblox": ["Roblox", "RBLX", "$RBLX"],
    "DraftKings": ["DraftKings", "DKNG", "$DKNG"],
    "Snap Inc": ["Snap", "SNAP", "$SNAP", "Snapchat"],
    "Pinterest": ["Pinterest", "PINS", "$PINS"],
    "Uber Technologies": ["Uber", "UBER", "$UBER"],
    "Lyft Inc": ["Lyft", "LYFT", "$LYFT"],
    "DoorDash": ["DoorDash", "DASH", "$DASH"],
    "Airbnb": ["Airbnb", "ABNB", "$ABNB"],
    "Spotify": ["Spotify", "SPOT", "$SPOT"],
    "Zoom Video": ["Zoom", "ZM", "$ZM"],
    "Roku Inc": ["Roku", "ROKU", "$ROKU"],
    "Pinduoduo": ["Pinduoduo", "PDD", "$PDD"],
    "Alibaba Group": ["Alibaba", "BABA", "$BABA"],
    "Baidu Inc": ["Baidu", "BIDU", "$BIDU"],
    "JD.com": ["JD.com", "JD", "$JD"],
    "Tencent": ["Tencent", "TCEHY"],
    "Taiwan Semiconductor": ["TSMC", "TSM", "$TSM", "Taiwan Semiconductor"],
    "Sony Group": ["Sony", "SONY", "$SONY"],
    "Toyota Motor": ["Toyota", "TM", "$TM"],
    # === Defensive / dividend names ===
    "AT&T Wireless": ["AT&T Wireless"],  # Place-holder; rarely appears
    "Duke Energy": ["Duke Energy", "DUK", "$DUK"],
    "NextEra Energy": ["NextEra", "NEE", "$NEE"],
    "Realty Income": ["Realty Income", "O", "$O"],
    "Simon Property": ["Simon Property", "SPG", "$SPG"],
    "Prologis Inc": ["Prologis", "PLD", "$PLD"],
    # === Misc that appears often in news ===
    "Goldman Sachs Group": ["Goldman Sachs Group"],  # Variant — sometimes used long form
    "Federal Reserve": ["Fed", "Federal Reserve", "FOMC"],
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


def canonicalize_for_scoring(s: str, alias_map: dict[str, str]) -> str:
    return alias_map.get(s.strip(), s.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="case-study-expanded")
    parser.add_argument("--per-entity", type=int, default=20)
    parser.add_argument("--models", default="qwen2.5:3b,llama3.2:3b")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"case_study_expanded_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    alias_map = build_alias_map()
    canonicals_set = set(alias_map.values())
    print(f"EXPANDED alias map: {len(alias_map)} aliases / "
          f"{len(canonicals_set)} canonical entities")
    print(f"Loading Twitter Financial News validation, "
          f"max {args.per_entity} per entity...")
    by_entity = load_filtered_tweets(args.per_entity, alias_map)
    tweets = [t for tw_list in by_entity.values() for t in tw_list]
    print(f"Loaded {len(tweets)} real tweets across "
          f"{sum(1 for v in by_entity.values() if v)} entities with coverage")

    n_entities_with_data = [(c, len(v)) for c, v in by_entity.items() if v]
    print("Top-15 entities by coverage:")
    for c, n in sorted(n_entities_with_data, key=lambda x: -x[1])[:15]:
        print(f"  {c:28} {n}")
    if len(n_entities_with_data) > 15:
        total_rest = sum(n for _, n in
                         sorted(n_entities_with_data, key=lambda x: -x[1])[15:])
        print(f"  ... {len(n_entities_with_data) - 15} more entities "
              f"with {total_rest} total tweets")

    models = args.models.split(",")
    all_results = []
    print(f"\nModels: {models}")
    print(f"Estimated total LLM calls: {2 * len(tweets) * len(models)}")
    for model in models:
        provider, extractor, env_name, key = _route_extractor(model)
        if env_name is not None and not key:
            print(f"\n  SKIP {model}: {env_name} not set")
            continue
        result = run_model(model, tweets, alias_map, canonicals_set,
                           extractor=extractor)
        result["provider"] = provider
        all_results.append(result)

    print("\n" + "=" * 70)
    print(f"EXPANDED case study: {len(tweets)} real tweets, "
          f"{len(canonicals_set)} entities, {len(alias_map)} aliases")
    print("=" * 70)
    print(f"  {'Model':18} {'no_acc':>8} {'with_acc':>9} {'Δ acc':>8} "
          f"{'CI 95% [lo, hi]':>20} {'Δ canon':>8}")
    for r in all_results:
        if "accuracy_no_proxy" not in r:
            continue
        print(f"  {r['model']:18} {r['accuracy_no_proxy']:>8.3f} "
              f"{r['accuracy_with_proxy']:>9.3f} {r['accuracy_diff']:>+8.4f} "
              f"  [{r['accuracy_ci_lo']:+.4f}, {r['accuracy_ci_hi']:+.4f}]   "
              f"{r['canonical_rate_diff']:>+8.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_tweets": len(tweets),
        "n_canonicals_in_map": len(canonicals_set),
        "n_aliases_in_map": len(alias_map),
        "n_entities_with_coverage": len(n_entities_with_data),
        "models": models,
        "results": all_results,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

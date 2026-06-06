"""Open-world alias benchmark: does the embedding-based EntityNormalizer
handle aliases that are NOT in the static mention_map?

This closes the gap flagged in docs/finding-small-llm-quality.md and
docs/finding-conversational-llm.md: those benchmarks used a fully-closed
mention_map (every alias the LLM might see was in the map). Real
deployments have open-world aliases (ones the integrator didn't know
about, or new aliases that arrive after the map was authored). The
v0.5.x claim is that the embedding-based EntityNormalizer handles
those via the variant's embedding similarity.

Four conditions, run against llama3.1:8b on the same 30-utterance
single-sentence workload from small_llm_quality_bench:

  A. baseline:        no proxy at all (LLM sees raw text)
  B. full_map:        all 30 aliases in the mention_map (gold upper bound)
  C. partial_map:     only 2/5 aliases per entity in the map; other 3
                      pass through unchanged
  D. hybrid:          partial_map for known aliases, embedding-based
                      EntityNormalizer.normalize() fallback for unmapped

The interesting comparison is D vs B (does hybrid recover the full-map
result?) and D vs C (does the embedding fallback add value over the
partial map alone?).

Run:
  .venv/bin/python experiments/open_world_alias_bench.py
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

from runner.metrics import alignment
from runner.service import EntityNormalizer
from experiments.small_llm_quality_bench import (
    ENTITIES,
    build_workload,
    llm_extract,
    pre_normalize as full_map_normalize,
)


# Per entity, take the FIRST TWO aliases as "known to the integrator"
# and leave the rest as open-world. The first two are typically the
# bare name and ticker; the unmapped three include surface variants
# (Apple Inc., Apple Computer) and corporate suffixes.
def build_partial_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in ENTITIES.items():
        for alias in aliases[:2]:  # first two only
            out[alias] = canonical
    return out


def build_full_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in ENTITIES.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def normalize_text_with_handler(text: str, alias_list: list[str],
                                handler) -> str:
    """Apply `handler(alias)` to every known alias appearing in `text`.
    Longest-first to avoid prefix collisions. Each alias is replaced at
    most once per text (mirrors the per-utterance contract)."""
    out = text
    for alias in sorted(alias_list, key=len, reverse=True):
        if alias in out:
            replacement = handler(alias)
            out = out.replace(alias, replacement, 1)
    return out


def build_warmed_normalizer(canonical_names: list[str]) -> EntityNormalizer:
    """Pre-warm an EntityNormalizer by feeding it each canonical name
    once. After warming, subsequent normalize() calls compare the input
    against these pre-existing canonicals."""
    norm = EntityNormalizer("embed-proxy-v0.3.1")
    for canonical in canonical_names:
        norm.normalize(canonical)
    return norm


def run_condition(model: str, utterances: list[str], oracle: list[tuple[str, str]],
                  condition_name: str, transform):
    inputs = [transform(u) for u in utterances]
    t0 = time.perf_counter()
    extracted = [llm_extract(model, inp) for inp in inputs]
    elapsed = time.perf_counter() - t0
    preds = list(zip(utterances, extracted))
    bc = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
    unique = len(set(extracted))
    print(f"  {condition_name:18} B-cubed F1 = {bc:.4f}, "
          f"{unique:>2} unique outputs (ideal: 6), "
          f"{elapsed:.1f}s ({elapsed/len(utterances)*1000:.0f}ms/call)")
    return {
        "condition": condition_name,
        "bcubed_f1": bc,
        "unique_outputs": unique,
        "elapsed_s": elapsed,
        "ms_per_call": elapsed / len(utterances) * 1000,
        "preds": preds,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="open-world-alias-bench")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"open_world_alias_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    workload = build_workload()
    utterances = [u for u, _, _ in workload]
    oracle = [(u, canonical) for u, canonical, _ in workload]
    full_map = build_full_map()
    partial_map = build_partial_map()
    canonical_names = list(ENTITIES.keys())
    all_aliases = list(full_map)

    print(f"Workload: {len(utterances)} utterances over "
          f"{len(canonical_names)} canonicals")
    print(f"Full alias map: {len(full_map)} aliases")
    print(f"Partial map (2/5 per entity): {len(partial_map)} aliases "
          f"(missing {len(full_map) - len(partial_map)} open-world aliases)")
    print(f"\nModel: {args.model}\n")

    # Pre-warm the embedding-based normalizer once for hybrid condition.
    print("Pre-warming EntityNormalizer with 6 canonical entity names...")
    norm = build_warmed_normalizer(canonical_names)

    def baseline_transform(text):
        return text

    def full_map_transform(text):
        return full_map_normalize(text, full_map)

    def partial_map_transform(text):
        return full_map_normalize(text, partial_map)

    def hybrid_transform(text):
        # Use the alias_list (every alias the workload uses) as the
        # detection vocabulary (this is the NER step; in production it
        # would be NER + word-boundary matching).
        def handler(alias):
            if alias in partial_map:
                return partial_map[alias]
            # Open-world fallback: embedding-based normalize.
            return norm.normalize(alias)
        return normalize_text_with_handler(text, all_aliases, handler)

    results = []
    print()
    results.append(run_condition(args.model, utterances, oracle,
                                 "A_baseline", baseline_transform))
    results.append(run_condition(args.model, utterances, oracle,
                                 "B_full_map", full_map_transform))
    results.append(run_condition(args.model, utterances, oracle,
                                 "C_partial_map", partial_map_transform))
    results.append(run_condition(args.model, utterances, oracle,
                                 "D_hybrid", hybrid_transform))

    print("\n" + "=" * 70)
    print(f"Summary — open-world alias coverage on {args.model}")
    print("=" * 70)
    by_name = {r["condition"]: r for r in results}
    a = by_name["A_baseline"]["bcubed_f1"]
    b = by_name["B_full_map"]["bcubed_f1"]
    c = by_name["C_partial_map"]["bcubed_f1"]
    d = by_name["D_hybrid"]["bcubed_f1"]
    print(f"  A baseline (no proxy):                B-cubed = {a:.4f}")
    print(f"  B full map (gold upper bound):        B-cubed = {b:.4f}   "
          f"(Δ vs A = {b - a:+.4f})")
    print(f"  C partial map (2/5 only, no fallback): B-cubed = {c:.4f}   "
          f"(Δ vs A = {c - a:+.4f})")
    print(f"  D hybrid (partial + embed fallback):  B-cubed = {d:.4f}   "
          f"(Δ vs A = {d - a:+.4f}, vs C = {d - c:+.4f}, vs B = {d - b:+.4f})")

    # Interpret
    if d - c >= 0.05:
        verdict = "embedding fallback ADDS meaningful value over partial map"
    elif d - c <= -0.05:
        verdict = "embedding fallback HURTS vs partial map (false merges?)"
    else:
        verdict = "embedding fallback is roughly NEUTRAL on this workload"
    if d >= b - 0.02:
        verdict += "; hybrid RECOVERS full-map quality"
    else:
        verdict += f"; hybrid still trails full map by {b - d:.4f}"
    print(f"\nVerdict: {verdict}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "n_utterances": len(utterances),
        "n_canonicals": len(canonical_names),
        "full_map_size": len(full_map),
        "partial_map_size": len(partial_map),
        "results": results,
        "verdict": verdict,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

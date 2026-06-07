"""Unseen-entity benchmark: does the embedding fallback mint a coherent
canonical for an entity that was NOT in the warm-up set?

Extends open_world_alias_bench with a 7th entity (AMD) whose aliases
were never seen by the EntityNormalizer at warm-up time. Compares:

  A. baseline (no proxy) — the LLM sees raw text including AMD aliases
  B. full_map_known_only — full map for the 6 warmed entities only;
     AMD aliases pass through unchanged. Tests whether the LLM
     fragments AMD's aliases on its own.
  C. hybrid_with_embed_fallback — full map for the 6 warmed entities,
     embedding-based EntityNormalizer fallback for any unmapped alias
     (including AMD's). The fallback path may or may not mint a single
     coherent canonical for AMD's three aliases.

What the embedding fallback can do for an unseen entity:
  - First time it sees "AMD", it mints "AMD" as a new canonical.
  - Second time it sees "Advanced Micro Devices", it embeds and
    compares to all existing canonicals. If none clear threshold, it
    mints "Advanced Micro Devices" as another new canonical. Two
    canonicals for one entity = fragmentation.
  - For coherence, the embedder's cosine between "AMD" and "Advanced
    Micro Devices" would need to clear the 0.8 threshold. That is the
    test.

Run:
  .venv/bin/python experiments/unseen_entity_bench.py
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
    TEMPLATES,
    llm_extract,
    pre_normalize as map_normalize,
)
from experiments.open_world_alias_bench import normalize_text_with_handler


# Add AMD as the unseen 7th entity. Its aliases will NOT be added to
# the warm-up set or the mention_map, so the hybrid condition has to
# discover them via embedding similarity alone.
UNSEEN_ENTITY = {
    "AMD": ["AMD", "Advanced Micro Devices", "AMD Inc", "Advanced Micro", "AMD Corp"],
}


def build_workload_with_unseen():
    """All 6 known entities + AMD. 7 * 5 = 35 utterances."""
    out = []
    all_entities = {**ENTITIES, **UNSEEN_ENTITY}
    for canonical, aliases in all_entities.items():
        for alias, template in zip(aliases, TEMPLATES):
            out.append((template.format(alias=alias), canonical, alias))
    return out


def build_known_map() -> dict[str, str]:
    """Mention map for the 6 known entities only. AMD aliases not included."""
    out = {}
    for canonical, aliases in ENTITIES.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def build_warmed_normalizer():
    """Pre-warm with the 6 known canonical names. AMD is NOT included."""
    norm = EntityNormalizer("embed-proxy-v0.3.1")
    for canonical in ENTITIES:
        norm.normalize(canonical)
    return norm


def run_condition(model: str, utterances, oracle, condition_name, transform):
    inputs = [transform(u) for u in utterances]
    t0 = time.perf_counter()
    extracted = [llm_extract(model, inp) for inp in inputs]
    elapsed = time.perf_counter() - t0
    preds = list(zip(utterances, extracted))
    bc = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
    # Per-entity breakdown so we can see if AMD specifically fragments
    by_oracle = {}
    for (u, o, _alias), pred in zip(workload, extracted):
        by_oracle.setdefault(o, []).append(pred)
    unique_per_entity = {o: len(set(preds_for_o)) for o, preds_for_o in by_oracle.items()}
    total_unique = len(set(extracted))
    amd_unique = unique_per_entity.get("AMD", 0)
    print(f"  {condition_name:32} B-cubed F1 = {bc:.4f}, "
          f"total unique = {total_unique:>2} (ideal: 7), "
          f"AMD-specific unique = {amd_unique} (ideal: 1), "
          f"{elapsed:.1f}s")
    return {
        "condition": condition_name,
        "bcubed_f1": bc,
        "total_unique_outputs": total_unique,
        "amd_unique_outputs": amd_unique,
        "unique_per_entity": unique_per_entity,
        "elapsed_s": elapsed,
        "extractions": [
            {"utterance": u, "oracle": o, "alias": a, "llm_output": e}
            for (u, o, a), e in zip(workload, extracted)
        ],
    }


def main(argv=None):
    global workload
    parser = argparse.ArgumentParser(prog="unseen-entity-bench")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"unseen_entity_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    workload = build_workload_with_unseen()
    utterances = [u for u, _, _ in workload]
    oracle = [(u, canonical) for u, canonical, _ in workload]
    known_map = build_known_map()

    print(f"Workload: {len(utterances)} utterances over 7 oracle entities "
          f"(6 known + 1 unseen 'AMD')")
    print(f"Known mention map covers: {sorted(set(known_map.values()))}")
    print(f"Unseen entity (NOT in map, NOT in warm-up): AMD with aliases "
          f"{UNSEEN_ENTITY['AMD']}")
    print(f"\nModel: {args.model}\n")

    print("Pre-warming EntityNormalizer with 6 KNOWN canonicals (no AMD)...")
    norm = build_warmed_normalizer()

    def baseline_transform(text):
        return text

    def known_only_transform(text):
        return map_normalize(text, known_map)

    def hybrid_transform(text):
        all_aliases = list(known_map) + UNSEEN_ENTITY["AMD"]

        def handler(alias):
            if alias in known_map:
                return known_map[alias]
            return norm.normalize(alias)
        return normalize_text_with_handler(text, all_aliases, handler)

    results = []
    print()
    results.append(run_condition(args.model, utterances, oracle,
                                 "A_baseline", baseline_transform))
    results.append(run_condition(args.model, utterances, oracle,
                                 "B_known_map_only", known_only_transform))
    results.append(run_condition(args.model, utterances, oracle,
                                 "C_hybrid_with_embed_fallback",
                                 hybrid_transform))

    print("\n" + "=" * 75)
    print(f"Summary on {args.model}: does embedding fallback handle AMD?")
    print("=" * 75)
    by_name = {r["condition"]: r for r in results}
    a = by_name["A_baseline"]
    b = by_name["B_known_map_only"]
    c = by_name["C_hybrid_with_embed_fallback"]
    print(f"  A baseline                AMD unique = {a['amd_unique_outputs']}, "
          f"B-cubed = {a['bcubed_f1']:.4f}")
    print(f"  B map-only (no AMD)       AMD unique = {b['amd_unique_outputs']}, "
          f"B-cubed = {b['bcubed_f1']:.4f}")
    print(f"  C hybrid (embed fallback) AMD unique = {c['amd_unique_outputs']}, "
          f"B-cubed = {c['bcubed_f1']:.4f}")

    if c["amd_unique_outputs"] < b["amd_unique_outputs"]:
        amd_verdict = f"Embedding fallback REDUCED AMD fragmentation ({b['amd_unique_outputs']} -> {c['amd_unique_outputs']})"
    elif c["amd_unique_outputs"] == b["amd_unique_outputs"]:
        amd_verdict = f"Embedding fallback DID NOT change AMD fragmentation (still {c['amd_unique_outputs']} unique)"
    else:
        amd_verdict = f"Embedding fallback INCREASED AMD fragmentation"
    print(f"\nAMD-specific verdict: {amd_verdict}")
    print(f"Ideal AMD unique = 1 (all 5 aliases collapsed to one canonical)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "n_utterances": len(utterances),
        "unseen_entity": UNSEEN_ENTITY,
        "results": results,
        "amd_verdict": amd_verdict,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


workload = []  # populated by main()

if __name__ == "__main__":
    sys.exit(main())

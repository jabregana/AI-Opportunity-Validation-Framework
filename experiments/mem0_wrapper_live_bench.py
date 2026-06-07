"""Live Mem0 deployment with Mem0PreNormalized wrapper.

The earlier `mem0_baseline.py` ran Mem0 v3 OSS with raw inputs and
documented that Mem0 outputs extracted natural-language facts rather
than canonical IDs (so direct B-cubed comparison wasn't possible).
That finding still holds.

This bench asks a different question: when we wrap Mem0 with
Mem0PreNormalized using a domain alias map, does the resulting stored
memory contain FEWER fragmented entries for the same conceptual
entities?

Method:
  1. Build a synthetic stream of 30 utterances mentioning 6 entities
     under multiple aliases (the same workload as small_llm_quality_bench).
  2. Run Mem0 WITHOUT wrapper. Each utterance becomes one or more
     extracted memories. Count total memories at the end.
  3. Reset to a fresh Mem0 instance. Run the SAME 30 utterances WITH
     Mem0PreNormalized in front. Pre-normalization rewrites aliases
     to canonicals before Mem0's LLM extraction. Count memories.
  4. Compare:
     - Total memory count (lower = less fragmentation)
     - Number of distinct entities the memories refer to (proxy
       for store coherence)
     - Per-entity memory count distribution

This is the operational counterpart to the LLM-quality benches:
those measured the LLM's output coherence; this measures the
downstream memory's storage coherence.

Run:
  ! ANTHROPIC_API_KEY=... .venv/bin/python experiments/mem0_wrapper_live_bench.py
(no API key needed; Mem0 uses Ollama backend per mem0_baseline.py)
"""
from __future__ import annotations
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.small_llm_quality_bench import build_workload, build_alias_map
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized


def build_memory(collection_suffix: str):
    """Build a Mem0 v3 client with a fresh Qdrant collection."""
    os.environ.setdefault("OPENAI_API_KEY", "dummy-not-used")
    from mem0 import Memory

    config = {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": "llama3.1:8b",
                "temperature": 0.0,
                "max_tokens": 500,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {"model": "all-minilm"},
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": f"mem0_wrapper_bench_{collection_suffix}_{int(time.time())}",
                "path": "/tmp/mem0_wrapper_bench",
                "embedding_model_dims": 384,
            },
        },
    }
    return Memory.from_config(config)


def run_condition(label: str, utterances: list[str], use_wrapper: bool,
                  alias_map: dict[str, str]):
    print(f"\n=== Condition: {label} ===")
    print("Building fresh Mem0 instance...")
    raw_mem = build_memory(label)
    if use_wrapper:
        norm = EntityNormalizer("embed-proxy-v0.3.1")
        mem = Mem0PreNormalized(raw_mem, norm, mention_map=alias_map)
    else:
        mem = raw_mem

    print(f"Ingesting {len(utterances)} utterances...")
    add_results = []
    t0 = time.perf_counter()
    for i, utt in enumerate(utterances, 1):
        out = mem.add(utt, user_id="bench_user")
        add_results.append({"i": i, "utterance": utt, "response": out})
        if i % 5 == 0:
            print(f"  ... {i}/{len(utterances)} ingested ({time.perf_counter() - t0:.1f}s)")
    ingest_s = time.perf_counter() - t0

    print(f"Ingest done in {ingest_s:.1f}s. Fetching final memory state...")
    # Mem0 v2.x changed the get_all signature: top-level entity kwargs
    # (user_id, agent_id, run_id) were moved into the filters dict.
    final = raw_mem.get_all(filters={"user_id": "bench_user"})
    if isinstance(final, dict) and "results" in final:
        memories = final["results"]
    elif isinstance(final, list):
        memories = final
    else:
        memories = []
    memory_texts = [str(m.get("memory", "")) for m in memories]
    print(f"Final memory count: {len(memories)}")
    for i, text in enumerate(memory_texts[:10], 1):
        print(f"  [{i}] {text[:80]}")
    if len(memory_texts) > 10:
        print(f"  ... and {len(memory_texts) - 10} more")

    return {
        "condition": label,
        "use_wrapper": use_wrapper,
        "ingest_seconds": ingest_s,
        "n_inputs": len(utterances),
        "n_memories_stored": len(memories),
        "memory_texts": memory_texts,
        "add_results": add_results,
    }


def count_entity_references(memory_texts: list[str], canonical_names: list[str]) -> dict:
    """For each canonical entity, count how many stored memories mention
    it (any surface form). A perfect proxy would produce 1 memory per
    entity per topic; fragmentation increases counts."""
    counts = {}
    for canonical in canonical_names:
        hits = sum(1 for text in memory_texts if canonical.lower() in text.lower())
        counts[canonical] = hits
    return counts


def main():
    workload = build_workload()
    utterances = [u for u, _, _ in workload]
    alias_map = build_alias_map()
    canonical_names = sorted(set(canonical for _, canonical, _ in workload))
    print(f"Workload: {len(utterances)} utterances over "
          f"{len(canonical_names)} entities")
    print(f"Alias map: {len(alias_map)} aliases -> {len(canonical_names)} canonicals")

    # Run both conditions.
    no_wrapper = run_condition("no_wrapper", utterances, False, alias_map)
    with_wrapper = run_condition("with_wrapper", utterances, True, alias_map)

    # Counts
    no_counts = count_entity_references(no_wrapper["memory_texts"], canonical_names)
    yes_counts = count_entity_references(with_wrapper["memory_texts"], canonical_names)

    print("\n" + "=" * 70)
    print("Summary — Mem0 live, with vs without Mem0PreNormalized")
    print("=" * 70)
    print(f"  No wrapper:    {no_wrapper['n_memories_stored']:>3} memories stored, "
          f"{no_wrapper['ingest_seconds']:.1f}s ingest")
    print(f"  With wrapper:  {with_wrapper['n_memories_stored']:>3} memories stored, "
          f"{with_wrapper['ingest_seconds']:.1f}s ingest")
    delta = no_wrapper['n_memories_stored'] - with_wrapper['n_memories_stored']
    if no_wrapper['n_memories_stored'] > 0:
        pct = 100.0 * delta / no_wrapper['n_memories_stored']
    else:
        pct = 0.0
    print(f"  Reduction:     {delta} memories ({pct:+.1f}%)")

    print(f"\n  Per-entity reference counts in final memory state:")
    print(f"  {'entity':22} {'no wrapper':>12} {'with wrapper':>14}")
    for canonical in canonical_names:
        print(f"  {canonical:22} {no_counts[canonical]:>12} {yes_counts[canonical]:>14}")

    out_path = (
        ROOT / "runs"
        / f"mem0_wrapper_live_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_utterances": len(utterances),
        "n_canonicals": len(canonical_names),
        "alias_map_size": len(alias_map),
        "no_wrapper": {
            "n_memories": no_wrapper["n_memories_stored"],
            "ingest_seconds": no_wrapper["ingest_seconds"],
            "memory_texts": no_wrapper["memory_texts"],
            "per_entity_reference_counts": no_counts,
        },
        "with_wrapper": {
            "n_memories": with_wrapper["n_memories_stored"],
            "ingest_seconds": with_wrapper["ingest_seconds"],
            "memory_texts": with_wrapper["memory_texts"],
            "per_entity_reference_counts": yes_counts,
        },
        "fragmentation_reduction": {
            "absolute": delta,
            "percent": pct,
        },
    }, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Multi-session conversational Mem0 bench with retrieval F1.

This is the long-form conversational test the analysis doc identifies
as the right shape for measuring the proxy's value in the
conversational memory category. It also doubles as the Mem0 retrieval
F1 bench (the storage-layer commercial pitch's missing piece).

Setup:
  - K simulated sessions (default K=30), evenly split across N
    entities (default N=6, so 5 sessions per entity).
  - Each session is a short 3-turn dialogue mentioning ONE entity
    via a different alias each time. Across the 5 sessions for an
    entity, every alias of that entity gets used.
  - Ingest each session into Mem0 as a separate `add()` call.
  - Run two conditions: with and without Mem0PreNormalized wrapper.

After all sessions ingest:
  - Query Mem0 with `search(query=canonical_name)` for each entity.
  - Compute retrieval precision/recall/F1:
    * Precision = fraction of returned memories that are actually
      about the queried entity (we know the ground truth because we
      ingested them).
    * Recall = fraction of the entity's sessions that surfaced in
      the search results.
    * F1 = harmonic mean.
  - Average across all 6 entities.

This measures the operational claim: "after K sessions, can queries
for the canonical entity name find the relevant memories?" The wrapper
should produce a higher recall because pre-normalization makes the
stored memory mention the canonical name explicitly.

Run:
  .venv/bin/python experiments/mem0_multi_session_bench.py
  (Mem0 + Ollama running on localhost)
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.small_llm_quality_bench import ENTITIES, build_alias_map
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized


SESSION_TEMPLATES = [
    "Today I'm thinking about {alias}. {alias} had a strong quarter. I might buy.",
    "Bought some {alias} shares this morning. {alias} looks undervalued.",
    "Watching {alias} closely. {alias} earnings are next week.",
    "Sold my {alias} position. {alias} ran up too fast.",
    "Long term hold on {alias}. {alias} has staying power.",
]


def build_multi_session_workload():
    """Build K sessions, one per (entity, alias) pair.
    Returns list of (session_text, oracle_entity, alias_used)."""
    sessions = []
    for entity, aliases in ENTITIES.items():
        for alias, template in zip(aliases, SESSION_TEMPLATES):
            text = template.format(alias=alias)
            sessions.append({
                "text": text,
                "oracle": entity,
                "alias": alias,
            })
    return sessions


def build_memory(collection_suffix: str):
    """Fresh Mem0 instance with a unique Qdrant collection."""
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
                "collection_name": f"mem0_multi_session_{collection_suffix}_{int(time.time())}",
                "path": "/tmp/mem0_multi_session_bench",
                "embedding_model_dims": 384,
            },
        },
    }
    return Memory.from_config(config)


def warm_cache(model: str = "llama3.1:8b"):
    """Send a dummy call to warm Ollama's model cache so the latency
    comparison between conditions is fair."""
    print("Warming Ollama cache with a dummy call...")
    import urllib.request
    body = json.dumps({"model": model, "prompt": "ok",
                       "stream": False, "options": {"num_predict": 2}}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp.read()


SHARED_USER_ID = "shared_user"


def ingest_sessions(mem, sessions, label: str):
    """Ingest all sessions under a SHARED user_id."""
    print(f"\n[{label}] Ingesting {len(sessions)} sessions under "
          f"shared user_id={SHARED_USER_ID!r}...")
    t0 = time.perf_counter()
    for i, sess in enumerate(sessions, 1):
        mem.add(sess["text"], user_id=SHARED_USER_ID)
        if i % 5 == 0:
            print(f"  [{label}]  {i}/{len(sessions)} sessions "
                  f"ingested ({time.perf_counter() - t0:.1f}s)")
    return time.perf_counter() - t0


def collect_all_memories(raw_mem, n_sessions: int):
    """Pull all stored memories from the shared user store."""
    try:
        result = raw_mem.get_all(filters={"user_id": SHARED_USER_ID})
    except Exception as e:
        print(f"  WARN: get_all failed: {e}")
        return []
    return result.get("results", []) if isinstance(result, dict) else result


def retrieve_for_canonicals(raw_mem, canonicals: list[str], top_k: int = 10):
    """For each canonical, run ONE search against the shared store and
    take the top K results. This is what an integrator would do at
    query time."""
    results = {}
    for canonical in canonicals:
        try:
            search_result = raw_mem.search(query=canonical,
                                           filters={"user_id": SHARED_USER_ID},
                                           limit=top_k)
        except Exception as e:
            print(f"  WARN: search failed for {canonical}: {e}")
            results[canonical] = []
            continue
        memories = (search_result.get("results", [])
                    if isinstance(search_result, dict)
                    else search_result)
        results[canonical] = memories
    return results


def memory_oracle(memory: dict, alias_map: dict[str, str]) -> str | None:
    """Determine which oracle entity a stored memory is about by
    matching aliases in the memory text. Returns the canonical name
    if exactly one entity is mentioned, else None (ambiguous or none)."""
    text = str(memory.get("memory", "")).lower()
    matched: set[str] = set()
    for alias, canonical in alias_map.items():
        # Case-insensitive whole-token match.
        import re
        if re.search(r"\b" + re.escape(alias.lower()) + r"\b", text):
            matched.add(canonical)
    if len(matched) == 1:
        return next(iter(matched))
    return None


def count_memories_per_oracle(memories: list[dict], alias_map: dict[str, str]) -> dict[str, int]:
    """Count how many stored memories are about each canonical entity.
    Used to compute recall (against actual store contents, not ideal
    session count)."""
    counts: dict[str, int] = {}
    for m in memories:
        oracle = memory_oracle(m, alias_map)
        if oracle:
            counts[oracle] = counts.get(oracle, 0) + 1
    return counts


def compute_retrieval_metrics(retrieval, all_memories, canonicals: list[str],
                              alias_map: dict[str, str]):
    """For each canonical, compute precision/recall on the top-K
    retrieved memories.

    Precision = fraction of retrieved memories that are actually about
    the queried canonical (determined by alias-match on the memory text).

    Recall = fraction of TOTAL memories about that canonical (in the
    store) that the search retrieved. This measures whether search
    finds the relevant memories that DO exist in the store."""
    # Total memories per oracle (the population the retrieval is sampling).
    population_per_oracle = count_memories_per_oracle(all_memories, alias_map)
    metrics = {}
    macro_p, macro_r, macro_f = 0.0, 0.0, 0.0
    for canonical in canonicals:
        retrieved_ids = set()
        retrieved_correct_ids = set()
        for m in retrieval[canonical]:
            mid = m.get("id")
            if mid is None:
                continue
            retrieved_ids.add(mid)
            if memory_oracle(m, alias_map) == canonical:
                retrieved_correct_ids.add(mid)
        # Build the set of all in-store memory ids for this canonical
        # (the relevant set).
        relevant_ids = {
            m.get("id") for m in all_memories
            if memory_oracle(m, alias_map) == canonical and m.get("id")
        }
        tp = len(retrieved_correct_ids)
        p = tp / len(retrieved_ids) if retrieved_ids else 0.0
        r = tp / len(relevant_ids) if relevant_ids else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        metrics[canonical] = {
            "precision": p,
            "recall": r,
            "f1": f,
            "retrieved_count": len(retrieved_ids),
            "retrieved_correct": tp,
            "relevant_in_store": len(relevant_ids),
        }
        macro_p += p
        macro_r += r
        macro_f += f
    n = len(canonicals)
    return metrics, macro_p / n, macro_r / n, macro_f / n


def store_summary(all_memories, alias_map):
    """Count how many stored memories mention each canonical entity."""
    counts = {}
    for m in all_memories:
        oracle = memory_oracle(m, alias_map)
        if oracle:
            counts[oracle] = counts.get(oracle, 0) + 1
    return counts


def run_condition(label: str, sessions, use_wrapper: bool, alias_map):
    print(f"\n{'=' * 70}\n=== Condition: {label} ===\n{'=' * 70}")
    raw_mem = build_memory(label)
    if use_wrapper:
        norm = EntityNormalizer("embed-proxy-v0.3.1")
        mem = Mem0PreNormalized(raw_mem, norm, mention_map=alias_map)
    else:
        mem = raw_mem
    ingest_s = ingest_sessions(mem, sessions, label)
    print(f"\n[{label}] Ingest done in {ingest_s:.1f}s")

    print(f"\n[{label}] Collecting stored memories...")
    all_memories = collect_all_memories(raw_mem, len(sessions))
    print(f"[{label}] Total stored memories: {len(all_memories)}")

    # Per-canonical store coverage: how many memories mention each
    # canonical name (the population that retrieval is sampling).
    store_per_oracle = store_summary(all_memories, alias_map)
    print(f"[{label}] Stored memories per canonical (via alias-match):")
    for c in sorted(set(s["oracle"] for s in sessions)):
        print(f"  {c:22} {store_per_oracle.get(c, 0)}")

    canonicals = sorted(set(s["oracle"] for s in sessions))
    print(f"[{label}] Running retrieval queries for {len(canonicals)} "
          f"canonical names (top-10 each)...")
    retrieval = retrieve_for_canonicals(raw_mem, canonicals, top_k=10)
    metrics, macro_p, macro_r, macro_f = compute_retrieval_metrics(
        retrieval, all_memories, canonicals, alias_map
    )
    print(f"\n[{label}] Per-canonical retrieval (precision / recall / F1):")
    for canonical in canonicals:
        m = metrics[canonical]
        print(f"  {canonical:22} P={m['precision']:.3f} R={m['recall']:.3f} "
              f"F1={m['f1']:.3f}  ({m['retrieved_correct']}/{m['relevant_in_store']} "
              f"relevant-in-store, {m['retrieved_count']} retrieved)")
    print(f"  {'MACRO':22} P={macro_p:.3f} R={macro_r:.3f} F1={macro_f:.3f}")
    return {
        "label": label,
        "ingest_seconds": ingest_s,
        "n_stored_memories": len(all_memories),
        "retrieval_metrics": metrics,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f,
    }


def main():
    sessions = build_multi_session_workload()
    alias_map = build_alias_map()
    canonical_names = sorted(set(s["oracle"] for s in sessions))
    print(f"Workload: {len(sessions)} sessions over "
          f"{len(canonical_names)} entities ({len(sessions) // len(canonical_names)} per entity)")
    print(f"Alias map: {len(alias_map)} aliases\n")

    warm_cache()

    no_p = run_condition("no_wrapper", sessions, False, alias_map)
    yes_p = run_condition("with_wrapper", sessions, True, alias_map)

    print("\n" + "=" * 70)
    print("SUMMARY — Multi-session conversational Mem0 with retrieval F1")
    print("=" * 70)
    print(f"  Ingest time (cache-warmed):")
    print(f"    no wrapper:    {no_p['ingest_seconds']:.1f}s")
    print(f"    with wrapper:  {yes_p['ingest_seconds']:.1f}s")
    print(f"  Stored memories:")
    print(f"    no wrapper:    {no_p['n_stored_memories']}")
    print(f"    with wrapper:  {yes_p['n_stored_memories']}")
    print(f"  Retrieval (macro across {len(canonical_names)} canonical-name queries):")
    print(f"    no wrapper:    P={no_p['macro_precision']:.3f} "
          f"R={no_p['macro_recall']:.3f} F1={no_p['macro_f1']:.3f}")
    print(f"    with wrapper:  P={yes_p['macro_precision']:.3f} "
          f"R={yes_p['macro_recall']:.3f} F1={yes_p['macro_f1']:.3f}")
    print(f"    Δ F1: {yes_p['macro_f1'] - no_p['macro_f1']:+.3f}")
    print(f"    Δ Recall: {yes_p['macro_recall'] - no_p['macro_recall']:+.3f}")

    out_path = (
        ROOT / "runs"
        / f"mem0_multi_session_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_sessions": len(sessions),
        "n_canonicals": len(canonical_names),
        "alias_map_size": len(alias_map),
        "no_wrapper": no_p,
        "with_wrapper": yes_p,
    }, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

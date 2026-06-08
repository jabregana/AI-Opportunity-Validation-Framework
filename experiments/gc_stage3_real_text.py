"""Stage 3 real-data benchmark for the graph-GC opportunity.

Uses the same Twitter Financial News validation split + CURATED_ENTITIES
alias map that the schema-alignment proxy used for its Stage 3 / 4 work.
Different matching semantics (findall vs first-match) so each tweet
contributes one fact node plus an edge per distinct entity mentioned
(real edge density, not 1:1).

Workload construction:
  - For each filtered tweet i (those matching at least one entity),
    timestamp t_i = i * tick_seconds.
  - add_node(fact_i, kind='fact', t=t_i)
  - For each distinct entity e mentioned in tweet i:
    add_node(entity_e) if first time seen (at the first tweet that
    mentions it), add_edge(fact_i, entity_e) at t_i + epsilon,
    schedule remove_edge at t_i + fact_lifetime.
  - Pin the top-K most frequently mentioned entities.
  - expected_survivors = all entity nodes (conservative philosophy).

Runs b-raw-no-gc and gc-v0.1.2-fact-only. v0.1.0 / v0.1.1 omitted
because the Stage 2 revision finding established they fail UC-GC-2
under conservative-survival semantics.

Day 1 of Stage 3 (the integration-shim Stage 3 with Mem0 or Graphiti
runtime + actual LLM extraction) is a future extension. This script
is the small-N real-text-input baseline: real entity distribution,
real surface-form diversity, real Twitter text. The temporal model
(uniform tick) and the extraction (deterministic regex against the
curated alias map) are still simplifications. See the finding doc for
what is real vs simplified.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures.workloads.w_graph_churn import ChurnWorkload, GraphEvent
from runner.gc_runner import compute_uc_gates, run_gc
from runner.gc_variants import build

# Re-uses the proxy's curated financial entity map (~120 entities,
# ~400 aliases). Importing the constant only; no module-level side
# effects in case_study_expanded.
from experiments.case_study_expanded import CURATED_ENTITIES


def build_alias_map() -> dict[str, str]:
    """alias -> canonical entity name."""
    out: dict[str, str] = {}
    for canonical, aliases in CURATED_ENTITIES.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def build_match_pattern(alias_map: dict[str, str]) -> re.Pattern:
    """Longest-first alternation with word-ish boundaries.

    Mirrors the proxy's matching except this pattern is used with
    findall() so every entity mention per tweet is captured, not just
    the first.
    """
    aliases_longest_first = sorted(alias_map, key=len, reverse=True)
    return re.compile(
        r"(?:^|\s|[^\w$])(" + "|".join(re.escape(a) for a in aliases_longest_first)
        + r")(?:$|[^\w])"
    )


def load_tweets_and_extract(
    per_entity_cap: int,
    alias_map: dict[str, str],
) -> tuple[list[dict], dict[str, int]]:
    """Load Twitter Financial News validation split. Return:

      tweets: list of {text, idx, entities=[canonical, ...]} for tweets
        that mention at least one curated entity. Capped at per_entity_cap
        tweets per "primary" canonical (the first one mentioned) to keep
        the workload balanced across entities.
      entity_freq: canonical -> total mention count across kept tweets.
    """
    from datasets import load_dataset

    ds = load_dataset("zeroshot/twitter-financial-news-topic",
                      split="validation")
    pattern = build_match_pattern(alias_map)
    by_primary: dict[str, list[dict]] = {c: [] for c in set(alias_map.values())}
    entity_freq: dict[str, int] = {}

    for idx, example in enumerate(ds):
        text = example["text"]
        aliases_found = pattern.findall(text)
        if not aliases_found:
            continue
        entities = []
        seen = set()
        for alias in aliases_found:
            canonical = alias_map[alias]
            if canonical not in seen:
                seen.add(canonical)
                entities.append(canonical)
        primary = entities[0]
        if len(by_primary[primary]) >= per_entity_cap:
            continue
        by_primary[primary].append({
            "text": text,
            "idx": idx,
            "entities": entities,
        })
        for e in entities:
            entity_freq[e] = entity_freq.get(e, 0) + 1

    # Flatten in original Twitter order
    all_tweets = [t for tw_list in by_primary.values() for t in tw_list]
    all_tweets.sort(key=lambda t: t["idx"])
    return all_tweets, entity_freq


def build_workload(
    tweets: list[dict],
    entity_freq: dict[str, int],
    *,
    tick_seconds: float,
    fact_lifetime_seconds: float,
    pin_top_k: int,
) -> ChurnWorkload:
    """Construct a ChurnWorkload from the tweet stream.

    Each tweet becomes a fact node + one edge per distinct entity
    mentioned. Edge removal is scheduled at fact_lifetime later.
    Entities are added the first time they appear. The top-K entities
    by mention frequency are pinned.
    """
    events: list[GraphEvent] = []
    seen_entities: set[str] = set()
    entity_add_t: dict[str, float] = {}

    # Pin top-K entities (most frequently mentioned)
    pinned = set(
        c for c, _ in sorted(entity_freq.items(), key=lambda x: -x[1])[:pin_top_k]
    )

    for i, tweet in enumerate(tweets):
        t = float(i) * tick_seconds

        # Add any new entities first
        for entity in tweet["entities"]:
            if entity not in seen_entities:
                seen_entities.add(entity)
                entity_add_t[entity] = t
                events.append(GraphEvent(
                    op="add_node", timestamp=t,
                    node_id=entity, node_kind="entity",
                ))

        # Pin the newly-discovered top-K entities once each
        for entity in tweet["entities"]:
            if entity in pinned and entity in seen_entities:
                # Only emit one pin event per entity, right after its add
                if entity_add_t.get(entity) == t:
                    events.append(GraphEvent(
                        op="pin", timestamp=t + 0.0001, node_id=entity,
                    ))

        # Add fact node
        fact_id = f"tweet_{tweet['idx']:06d}"
        events.append(GraphEvent(
            op="add_node", timestamp=t + 0.001,
            node_id=fact_id, node_kind="fact",
        ))

        # Add edges fact -> entities and schedule their removal
        for entity in tweet["entities"]:
            events.append(GraphEvent(
                op="add_edge", timestamp=t + 0.002,
                edge_src=fact_id, edge_dst=entity,
            ))
            events.append(GraphEvent(
                op="remove_edge", timestamp=t + fact_lifetime_seconds,
                edge_src=fact_id, edge_dst=entity,
            ))

    events.sort(key=lambda e: e.timestamp)

    return ChurnWorkload(
        events=events,
        pinned_nodes=pinned,
        expected_survivors=set(seen_entities),  # conservative philosophy
        n_entities=len(seen_entities),
        n_facts=len(tweets),
    )


def main():
    p = argparse.ArgumentParser(prog="gc-stage3-real-text")
    p.add_argument("--per-entity-cap", type=int, default=20,
                   help="max tweets per primary entity (default 20)")
    p.add_argument("--tick-seconds", type=float, default=600.0,
                   help="seconds between tweets (default 600 = 10 min)")
    p.add_argument("--fact-lifetime-days", type=float, default=7.0)
    p.add_argument("--pin-top-k", type=int, default=5,
                   help="pin top-K most-mentioned entities (default 5)")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    alias_map = build_alias_map()
    canonicals = set(alias_map.values())
    print(f"Alias map: {len(alias_map)} aliases -> {len(canonicals)} canonicals")
    print("Loading Twitter Financial News validation split...")
    tweets, entity_freq = load_tweets_and_extract(
        per_entity_cap=args.per_entity_cap, alias_map=alias_map,
    )
    n_entities_with_data = sum(1 for v in entity_freq.values() if v > 0)
    print(f"Loaded {len(tweets)} tweets across {n_entities_with_data} entities")
    print(f"Top 10 entities by mention freq:")
    for c, f in sorted(entity_freq.items(), key=lambda x: -x[1])[:10]:
        print(f"  {c:30} {f}")
    print()

    workload = build_workload(
        tweets, entity_freq,
        tick_seconds=args.tick_seconds,
        fact_lifetime_seconds=args.fact_lifetime_days * 86400,
        pin_top_k=args.pin_top_k,
    )
    print(f"Workload: {len(workload.events)} events, "
          f"{workload.n_entities} entities, "
          f"{workload.n_facts} facts, "
          f"{len(workload.pinned_nodes)} pinned, "
          f"{len(workload.expected_survivors)} expected survivors")
    print()

    variant_ids = [
        "b-raw-no-gc",
        "gc-v0.1.2-fact-only",
        "gc-v0.1.3-fact-only-tombstone",
        "gc-v0.1.4-conservative-entity-plus-fact",
        "gc-v0.1.5-fact-only-tenant-pinning",
        "gc-v0.1.6-comprehensive",
    ]
    results = {}
    timings = {}
    for vid in variant_ids:
        v = build(vid)
        t0 = time.perf_counter()
        r = run_gc(v, workload)
        elapsed = time.perf_counter() - t0
        results[vid] = r
        timings[vid] = elapsed
        print(f"--- {vid} ---")
        print(f"  nodes added:       {r.n_nodes_added}")
        print(f"  nodes collected:   {r.n_nodes_collected}")
        print(f"  nodes at end:      {r.n_nodes_at_end}")
        print(f"  store reduction:   {r.store_size_reduction_pct:.2f}%")
        print(f"  surviving entities:{len(r.surviving_entity_ids)}")
        print(f"  false collections: {r.n_false_collections} "
              f"({r.false_collection_rate_pct:.3f}%)")
        print(f"  write p50:         {r.write_p50_ms:.4f} ms")
        print(f"  write p99:         {r.write_p99_ms:.4f} ms")
        print(f"  sweep total:       {r.sweep_seconds:.4f} s")
        print(f"  wall time:         {elapsed:.3f} s")
        print()

    baseline = results["b-raw-no-gc"]
    gates = compute_uc_gates(results["gc-v0.1.2-fact-only"], baseline)
    print("=" * 72)
    print("UC gates for gc-v0.1.2-fact-only (vs b-raw-no-gc baseline)")
    print("=" * 72)
    for uc, info in gates.items():
        mark = "PASS" if info["status"] == "PASS" else "FAIL"
        print(f"  [{mark}] {uc} ({info['name']}): {info['reason']}")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_stage3_real_text"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "stage": "Stage 3 real-text (small N, real-text-input + deterministic extraction)",
        "opportunity": "real-time graph GC",
        "data_source": "zeroshot/twitter-financial-news-topic (validation split)",
        "alias_map": {
            "n_canonicals": len(canonicals),
            "n_aliases": len(alias_map),
        },
        "workload_params": {
            "per_entity_cap": args.per_entity_cap,
            "tick_seconds": args.tick_seconds,
            "fact_lifetime_days": args.fact_lifetime_days,
            "pin_top_k": args.pin_top_k,
        },
        "workload": {
            "n_events": len(workload.events),
            "n_entities": workload.n_entities,
            "n_facts": workload.n_facts,
            "n_pinned": len(workload.pinned_nodes),
            "n_expected_survivors": len(workload.expected_survivors),
        },
        "variants": {
            vid: {
                "variant": r.variant,
                "n_nodes_added": r.n_nodes_added,
                "n_nodes_collected": r.n_nodes_collected,
                "n_nodes_at_end": r.n_nodes_at_end,
                "store_size_reduction_pct": r.store_size_reduction_pct,
                "n_false_collections": r.n_false_collections,
                "false_collection_rate_pct": r.false_collection_rate_pct,
                "falsely_collected_ids": r.falsely_collected_ids,
                "write_p50_ms": r.write_p50_ms,
                "write_p99_ms": r.write_p99_ms,
                "sweep_seconds": r.sweep_seconds,
                "n_surviving_entities": len(r.surviving_entity_ids),
                "wall_time_seconds": timings[vid],
            }
            for vid, r in results.items()
        },
        "uc_gates": gates,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

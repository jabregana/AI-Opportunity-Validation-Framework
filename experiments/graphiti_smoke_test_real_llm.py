"""Real-Graphiti smoke test for the Phase 2 adapter.

Parallel to experiments/mem0_smoke_test_real_llm.py but targets
Graphiti + Neo4j instead of Mem0 + Qdrant. The shape is identical:

  - Configure the downstream (Graphiti with Neo4j backend)
  - Generate diverse natural-language texts
  - Walk them through the adapter's add_episode()
  - Periodic sweeps with gc-v0.1.8-comprehensive-tuned
  - Report end-to-end timing + sweep behavior

Defers to graphiti-core's defaults for entity extraction. The LLM
used for extraction is configurable via Graphiti's settings (OpenAI
by default; the user can swap in Ollama via OPENAI_BASE_URL +
custom embedder if desired).

Prerequisites (NOT installed by default):
  pip install graphiti-core
  Neo4j running at bolt://localhost:7687 (Docker is easiest)
  OPENAI_API_KEY env var set (or Ollama configured per graphiti-core
    docs)

Defaults to N=100 episodes so the test completes in ~5-10 minutes
at typical Graphiti latency (LLM extraction + Neo4j writes).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CHECKPOINT_EVERY = 25


def _build_graphiti(uri: str, user: str, password: str):
    """Instantiate a Graphiti client.

    Raises ImportError if graphiti-core is not installed.
    """
    try:
        from graphiti_core import Graphiti
    except ImportError as e:
        raise ImportError(
            "graphiti-core not installed. Run: pip install graphiti-core"
        ) from e
    return Graphiti(uri=uri, user=user, password=password)


def _load_test_texts(n: int) -> list[tuple[str, str]]:
    """Return (episode_name, episode_body) pairs.

    Re-uses the Twitter Financial News dataset when available
    (already a dependency for the proxy's Stage 3+ benchmarks).
    Falls back to synthetic statements.
    """
    try:
        from datasets import load_dataset
        ds = load_dataset("zeroshot/twitter-financial-news-topic",
                          split="validation")
        return [(f"tweet_{i}", ex["text"]) for i, ex in enumerate(ds)][:n]
    except Exception as e:
        print(f"  (datasets load failed: {e}; using synthetic)")
    # Fallback: synthetic statements
    templates = [
        "User {name} prefers {item} for {context}.",
        "{name} works at {company} as a {role}.",
        "{name} mentioned that {product} is {assessment}.",
    ]
    names = ["Alex", "Pat", "Sam", "Jordan", "Casey", "Morgan"]
    items = ["coffee", "tea", "sparkling water", "kombucha"]
    contexts = ["morning meetings", "afternoon focus time"]
    companies = ["Acme", "Globex", "Initech"]
    roles = ["engineer", "manager"]
    products = ["the dashboard", "the API"]
    assessments = ["working well", "needs improvement"]
    import random
    rng = random.Random(42)
    out = []
    for i in range(n):
        t = templates[i % len(templates)]
        body = t.format(
            name=rng.choice(names), item=rng.choice(items),
            context=rng.choice(contexts), company=rng.choice(companies),
            role=rng.choice(roles), product=rng.choice(products),
            assessment=rng.choice(assessments),
        )
        out.append((f"ep_{i}", body))
    return out


def main():
    p = argparse.ArgumentParser(prog="graphiti-smoke-real-llm")
    p.add_argument("--n-episodes", type=int, default=100)
    p.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j-user", default="neo4j")
    p.add_argument("--neo4j-password", default="changeme")
    p.add_argument("--sweep-every", type=int, default=25)
    p.add_argument("--min-age-seconds", type=float, default=60.0)
    p.add_argument("--variant", default="gc-v0.1.8-comprehensive-tuned")
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--checkpoint-dir", type=str,
                   default=str(ROOT / "runs" / "graphiti_smoke_real_llm"))
    p.add_argument("--rebuild-indices", action="store_true",
                   help="Call build_indices_and_constraints() before adding")
    args = p.parse_args()

    print("=" * 72)
    print("Real-Graphiti smoke test (Phase 2 credibility anchor)")
    print("=" * 72)
    print(f"N episodes:    {args.n_episodes}")
    print(f"Neo4j URI:     {args.neo4j_uri}")
    print(f"Sweep variant: {args.variant} (min_age={args.min_age_seconds}s)")
    print(f"Sweep every:   {args.sweep_every} episodes")
    print()

    print("Connecting to Graphiti / Neo4j...")
    t0 = time.time()
    try:
        graphiti = _build_graphiti(
            uri=args.neo4j_uri, user=args.neo4j_user,
            password=args.neo4j_password,
        )
    except ImportError as e:
        print(f"  {e}")
        print("Aborting; install prerequisites first.")
        return 1
    setup_seconds = time.time() - t0
    print(f"  Graphiti ready in {setup_seconds:.1f}s")

    from runner.dimensions.memory.lifecycle import FACTORIES
    from runner.dimensions.memory.lifecycle.integrations import (
        GraphitiGCMiddleware,
    )
    variant_cls = FACTORIES[args.variant]
    try:
        variant = variant_cls(min_age_seconds=args.min_age_seconds)
    except TypeError:
        variant = variant_cls()
    mw = GraphitiGCMiddleware(graphiti)
    print(f"  Variant: {variant.name} (min_age_seconds={args.min_age_seconds})")

    if args.rebuild_indices:
        print("  Building Graphiti indices + constraints...")
        try:
            from runner.dimensions.memory.lifecycle.integrations.graphiti_adapter import (
                _run_async,
            )
            _run_async(graphiti.build_indices_and_constraints())
        except Exception as e:
            print(f"  index-build failed (non-fatal): {e}")
    print()

    print("Loading test texts...")
    episodes = _load_test_texts(args.n_episodes)
    print(f"  {len(episodes)} episodes ready")
    print()

    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")

    print("Adding episodes + periodic sweep...")
    print(f"{'i':>5} {'wall(s)':>8} {'add(s)':>8} {'nodes':>6} {'edges':>6} {'sweep':>7}")
    add_latencies: list[float] = []
    sweep_log: list[dict] = []
    group_ids = ["user_a", "user_b", "user_c"]
    start = time.time()

    for i, (name, body) in enumerate(episodes):
        t0 = time.time()
        group_id = group_ids[i % len(group_ids)]
        try:
            result = mw.add_episode(
                name=name, episode_body=body, group_id=group_id,
            )
            n_nodes = len(getattr(result, "nodes", []) or [])
            n_edges = len(getattr(result, "edges", []) or [])
        except Exception as e:
            print(f"  add error at i={i}: {type(e).__name__}: {e}")
            n_nodes = 0
            n_edges = 0
        latency = time.time() - t0
        add_latencies.append(latency)

        if (i + 1) % args.sweep_every == 0:
            sweep_t0 = time.time()
            removed = mw.sweep(variant, current_time=time.time())
            sweep_t = time.time() - sweep_t0
            sweep_log.append({
                "after_i": i + 1, "removed": removed,
                "duration_s": sweep_t,
                "nodes_in_sidecar": len(mw._records),
            })
            print(f"{i+1:>5} {time.time()-start:>7.1f} {latency:>7.2f} "
                  f"{n_nodes:>6} {n_edges:>6} {removed:>6}*")
        elif (i + 1) % 5 == 0:
            print(f"{i+1:>5} {time.time()-start:>7.1f} {latency:>7.2f} "
                  f"{n_nodes:>6} {n_edges:>6}")

        if (i + 1) % CHECKPOINT_EVERY == 0:
            chk_path = checkpoint_dir / f"{ts}.partial.json"
            chk = {
                "i": i + 1, "n_target": args.n_episodes,
                "n_records": len(mw._records),
                "n_edges": len(mw._edges),
                "add_latency_p50": sorted(add_latencies)[len(add_latencies)//2],
                "sweep_log": sweep_log,
                "wall_seconds": time.time() - start,
            }
            chk_path.write_text(json.dumps(chk, indent=2))

    total_wall = time.time() - start
    print()
    print("=" * 72)
    print(f"Done in {total_wall:.1f}s ({total_wall/60:.1f} min)")
    print("=" * 72)
    if add_latencies:
        add_latencies.sort()
        n = len(add_latencies)
        p50 = add_latencies[n//2]
        p99 = add_latencies[min(n-1, int(0.99*n))]
        avg = sum(add_latencies) / n
        print(f"Add latency p50/p99:   {p50:.2f}s / {p99:.2f}s (avg {avg:.2f}s)")
    print(f"Final sidecar size:    {len(mw._records)} nodes, {len(mw._edges)} edges")
    print(f"Sweep cycles:          {len(sweep_log)}")
    if sweep_log:
        total_swept = sum(s["removed"] for s in sweep_log)
        avg_sweep_s = sum(s["duration_s"] for s in sweep_log) / len(sweep_log)
        print(f"Total swept:           {total_swept}")
        print(f"Avg sweep duration:    {avg_sweep_s:.3f}s")

    out_path = (Path(args.out) if args.out
                else checkpoint_dir / f"{ts}.final.json")
    artifact = {
        "experiment": "real-Graphiti smoke test (Phase 2)",
        "n_episodes_attempted": args.n_episodes,
        "n_records_final": len(mw._records),
        "n_edges_final": len(mw._edges),
        "setup_seconds": setup_seconds,
        "total_wall_seconds": total_wall,
        "config": {
            "neo4j_uri": args.neo4j_uri,
            "variant": args.variant,
            "min_age_seconds": args.min_age_seconds,
            "sweep_every": args.sweep_every,
        },
        "add_latency_p50": add_latencies[len(add_latencies)//2] if add_latencies else None,
        "add_latency_p99": add_latencies[min(len(add_latencies)-1, int(0.99*len(add_latencies)))] if add_latencies else None,
        "add_latency_avg": sum(add_latencies)/len(add_latencies) if add_latencies else None,
        "sweep_log": sweep_log,
        "stats": {
            "n_writes": mw.stats().n_writes,
            "n_edges_added": mw.stats().n_edges_added,
            "n_queries": mw.stats().n_queries,
            "n_sweeps_invoked": mw.stats().n_sweeps_invoked,
            "n_nodes_actually_removed": mw.stats().n_nodes_actually_removed,
        },
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\nArtifact: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

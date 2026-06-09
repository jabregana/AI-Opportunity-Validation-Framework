"""Real-Mem0 smoke test for the Phase 1 adapter.

Configures Mem0 v2 with a fully local stack (Ollama phi3:mini for LLM
extraction, Ollama all-minilm for embedding, Qdrant local file
storage), drives N memories through Mem0GCMiddleware, runs periodic
sweeps with gc-v0.1.8-comprehensive-tuned, and reports end-to-end
timing + adapter behavior.

This is the credibility-anchor test from the synthesis plan's Phase 1.
The output answers questions like:

  - Does the adapter work end-to-end against the real Mem0 v2 API?
  - What is the per-add latency under real LLM extraction?
  - How does v0.1.8's sweep behave on LLM-derived memories?
  - Are the variant defaults reasonable for a real Mem0 workload?

Checkpoints every CHECKPOINT_EVERY memories so the test can be
stopped early or resumed if needed.

Defaults to N=200 memories so the test completes in roughly 30 minutes
at ~10 seconds per add. Override via --n-memories.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CHECKPOINT_EVERY = 50


def _build_memory(config_dict: dict):
    from mem0 import Memory
    return Memory.from_config(config_dict)


def _load_test_texts(n: int) -> list[str]:
    """Source diverse natural-language texts for Mem0 to extract from.

    Uses the Twitter Financial News dataset (already a dependency for
    the proxy's Stage 3+ benchmarks). Falls back to synthetic
    statements if the dataset is unavailable.
    """
    try:
        from datasets import load_dataset
        ds = load_dataset("zeroshot/twitter-financial-news-topic",
                          split="validation")
        texts = [ex["text"] for ex in ds][:n]
        if len(texts) >= n:
            return texts[:n]
    except Exception as e:
        print(f"  (datasets load failed: {e}; using synthetic)")
    # Fallback: synthetic statements
    templates = [
        "User {name} prefers {item} for {context}.",
        "{name} works at {company} as a {role}.",
        "{name} mentioned that {product} is {assessment}.",
        "{name} scheduled a meeting with {team} about {topic}.",
        "{name} reviewed {document} and noted {observation}.",
    ]
    names = ["Alex", "Pat", "Sam", "Jordan", "Casey", "Morgan"]
    items = ["coffee", "tea", "sparkling water", "kombucha"]
    contexts = ["morning meetings", "afternoon focus time", "evening reviews"]
    companies = ["Acme Corp", "Globex", "Initech", "Umbrella"]
    roles = ["engineer", "manager", "designer", "analyst"]
    products = ["the dashboard", "the new API", "the mobile app"]
    assessments = ["working well", "needs improvement", "ready to ship"]
    teams = ["the eng team", "marketing", "ops"]
    topics = ["the roadmap", "Q3 planning", "the launch"]
    documents = ["the proposal", "the brief", "the spec"]
    observations = ["missing context", "good direction", "needs more data"]
    import random
    rng = random.Random(42)
    out: list[str] = []
    for i in range(n):
        t = templates[i % len(templates)]
        out.append(t.format(
            name=rng.choice(names), item=rng.choice(items),
            context=rng.choice(contexts), company=rng.choice(companies),
            role=rng.choice(roles), product=rng.choice(products),
            assessment=rng.choice(assessments), team=rng.choice(teams),
            topic=rng.choice(topics), document=rng.choice(documents),
            observation=rng.choice(observations),
        ))
    return out


def main():
    p = argparse.ArgumentParser(prog="mem0-smoke-real-llm")
    p.add_argument("--n-memories", type=int, default=200)
    p.add_argument("--llm-model", default="phi3:mini")
    p.add_argument("--embed-model", default="all-minilm:latest")
    p.add_argument("--qdrant-path", default="/tmp/qdrant_mem0_smoke")
    p.add_argument("--history-db", default="/tmp/mem0_smoke_history.db")
    p.add_argument("--sweep-every", type=int, default=50,
                   help="Run a v0.1.8 sweep every N memories (default 50)")
    p.add_argument("--variant", default="gc-v0.1.8-comprehensive-tuned",
                   help="GC variant to use for sweeps")
    p.add_argument("--min-age-seconds", type=float, default=120.0,
                   help="Override min_age for sweep collection. Default 120s "
                        "(2 minutes) so the smoke test sees actual collections. "
                        "Production deployments use ~86400 (1 day).")
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--checkpoint-dir", type=str,
                   default=str(ROOT / "runs" / "mem0_smoke_real_llm"))
    args = p.parse_args()

    print("=" * 72)
    print("Real-Mem0 smoke test (Phase 1 credibility anchor)")
    print("=" * 72)
    print(f"N memories:    {args.n_memories}")
    print(f"LLM model:     {args.llm_model}")
    print(f"Embedder:      {args.embed_model}")
    print(f"Qdrant path:   {args.qdrant_path}")
    print(f"Sweep variant: {args.variant}")
    print(f"Sweep every:   {args.sweep_every} memories")
    print()

    # Wipe any prior run state for a clean smoke test
    import shutil
    for path in [args.qdrant_path, args.history_db]:
        Path(path).is_file() and Path(path).unlink()
        if Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)

    config = {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": args.llm_model,
                "ollama_base_url": "http://localhost:11434",
                "temperature": 0.0,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": args.embed_model,
                "ollama_base_url": "http://localhost:11434",
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "mem0_smoke_test",
                "path": args.qdrant_path,
                "embedding_model_dims": 384,
            },
        },
        "history_db_path": args.history_db,
    }

    print("Instantiating Memory + adapter...")
    t0 = time.time()
    memory = _build_memory(config)
    setup_seconds = time.time() - t0
    print(f"  Memory ready in {setup_seconds:.1f}s")

    from runner.dimensions.memory.lifecycle import FACTORIES
    from runner.dimensions.memory.lifecycle.integrations import (
        Mem0GCMiddleware,
    )
    # Build variant with a smaller min_age_seconds for testing
    variant_cls = FACTORIES[args.variant]
    try:
        variant = variant_cls(min_age_seconds=args.min_age_seconds)
    except TypeError:
        variant = variant_cls()  # variant doesn't accept min_age (b-raw)
    mw = Mem0GCMiddleware(memory)
    print(f"  Variant: {variant.name} (min_age_seconds={args.min_age_seconds})")
    print()

    print("Loading test texts...")
    texts = _load_test_texts(args.n_memories)
    print(f"  {len(texts)} texts ready")
    print()

    # Checkpoint dir
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")

    # Bench loop
    print("Adding memories + periodic sweep...")
    print(f"{'i':>5} {'wall(s)':>8} {'add(s)':>8} {'memories':>9} {'sweep':>7}")
    add_latencies: list[float] = []
    sweep_log: list[dict] = []
    total_added = 0
    n_swept = 0
    user_ids = ["user_a", "user_b", "user_c"]
    start = time.time()

    for i, text in enumerate(texts):
        t0 = time.time()
        user_id = user_ids[i % len(user_ids)]
        try:
            result = mw.add(text, user_id=user_id)
            if isinstance(result, dict):
                n_new = len(result.get("results", []))
            else:
                n_new = 0
            total_added += n_new
        except Exception as e:
            print(f"  add error at i={i}: {type(e).__name__}: {e}")
            n_new = 0
        latency = time.time() - t0
        add_latencies.append(latency)

        if (i + 1) % args.sweep_every == 0:
            sweep_t0 = time.time()
            removed = mw.sweep(variant, current_time=time.time())
            sweep_t = time.time() - sweep_t0
            sweep_log.append({
                "after_i": i + 1, "removed": removed,
                "duration_s": sweep_t,
                "memories_before_sweep": total_added,
                "memories_after_sweep": total_added - removed,
            })
            n_swept += removed
            total_added -= removed
            print(f"{i+1:>5} {time.time()-start:>7.1f} {latency:>7.2f} "
                  f"{total_added:>9} {removed:>6}*")
        elif (i + 1) % 10 == 0:
            print(f"{i+1:>5} {time.time()-start:>7.1f} {latency:>7.2f} "
                  f"{total_added:>9}")

        # Periodic checkpoint
        if (i + 1) % CHECKPOINT_EVERY == 0:
            chk_path = checkpoint_dir / f"{ts}.partial.json"
            chk = {
                "i": i + 1,
                "n_target": args.n_memories,
                "total_added": total_added,
                "n_swept": n_swept,
                "add_latency_p50": sorted(add_latencies)[len(add_latencies)//2],
                "add_latency_p99": sorted(add_latencies)[min(len(add_latencies)-1, int(0.99*len(add_latencies)))],
                "sweep_log": sweep_log,
                "wall_seconds": time.time() - start,
            }
            chk_path.write_text(json.dumps(chk, indent=2))

    total_wall = time.time() - start
    print()
    print("=" * 72)
    print(f"Done in {total_wall:.1f}s ({total_wall/60:.1f} min)")
    print("=" * 72)
    print(f"Total memories added:  {sum(1 for _ in add_latencies)} attempts")
    print(f"Memories at end:       {total_added}")
    print(f"Total swept:           {n_swept}")
    if add_latencies:
        add_latencies.sort()
        n = len(add_latencies)
        p50 = add_latencies[n//2]
        p99 = add_latencies[min(n-1, int(0.99*n))]
        avg = sum(add_latencies) / n
        print(f"Add latency p50/p99:   {p50:.2f}s / {p99:.2f}s")
        print(f"Add latency avg:       {avg:.2f}s")
    print(f"Sweep cycles:          {len(sweep_log)}")
    if sweep_log:
        avg_sweep_s = sum(s["duration_s"] for s in sweep_log) / len(sweep_log)
        print(f"Avg sweep duration:    {avg_sweep_s:.3f}s")

    # Try a few searches to verify retrieval works
    print()
    print("Verification: search queries on the final state")
    queries = [
        "coffee preferences",
        "engineering work",
        "meeting plans",
    ]
    for q in queries:
        t0 = time.time()
        try:
            sr = mw.search(q, filters={"user_id": "user_a"}, top_k=5)
            n_hits = len(sr.get("results", []))
            print(f"  q='{q}': {n_hits} hits ({time.time()-t0:.2f}s)")
        except Exception as e:
            print(f"  q='{q}' error: {e}")

    out_path = (Path(args.out) if args.out
                else checkpoint_dir / f"{ts}.final.json")
    from runner.artifacts import emit_dimension_artifact
    reduction_pct = (100.0 * n_swept / max(1, mw.stats().n_writes))
    p50 = add_latencies[len(add_latencies)//2] if add_latencies else None
    p99 = add_latencies[min(len(add_latencies)-1, int(0.99*len(add_latencies)))] if add_latencies else None
    avg = sum(add_latencies)/len(add_latencies) if add_latencies else None
    emit_dimension_artifact(
        opportunity="memory_lifecycle",
        dimension="memory.lifecycle",
        stage=5,
        experiment_name="real-Mem0 smoke test (steady-state reduction)",
        variants=[{"id": args.variant, "role": "candidate"}],
        workload={
            "archetype": "real-data-squad-style",
            "n": args.n_memories,
            "seed": 42,
            "params": {"sweep_every": args.sweep_every},
        },
        metrics={
            "n_memories_attempted": args.n_memories,
            "n_writes_total": mw.stats().n_writes,
            "n_swept": n_swept,
            "n_remaining": mw.stats().n_writes - n_swept,
            "reduction_pct": reduction_pct,
            "add_latency_p50_s": p50,
            "add_latency_p99_s": p99,
            "add_latency_avg_s": avg,
            "total_wall_seconds": total_wall,
            "setup_seconds": setup_seconds,
            "n_sweeps_invoked": mw.stats().n_sweeps_invoked,
            "n_queries": mw.stats().n_queries,
            "sweep_log": sweep_log,
        },
        gates={},
        decision="PILOT",
        environment={
            "llm_model": args.llm_model,
            "embedder": args.embed_model,
        },
        out_path=out_path,
    )
    print(f"\nArtifact: {out_path}")


if __name__ == "__main__":
    main()

"""Retrieval-quality F1 benchmark backed by the real Graphiti adapter.

Parallel to experiments/mem0_retrieval_f1_benchmark.py but uses
GraphitiGCMiddleware (graph-native + async) instead of Mem0.

Workflow:
  1. Connect to Graphiti (Neo4j at bolt://localhost:7687)
  2. Load SQuAD subset for real Q&A
  3. Add each context as an episode via mw.add_episode()
     (Graphiti's LLM extracts entities + edges)
  4. Backdate aged subset
  5. Search before sweep (Graphiti's vector + reranker)
  6. mw.sweep(variant); search after
  7. UC-GC-RETRIEVAL verdict

Why Graphiti matters here: Mem0 v2 has flat memories so v0.1.8's
entity rule + tombstones + tenant features under-exercise. Graphiti
exposes the real entity-vs-fact distinction, so this is the better
testbed for the full v0.1.8 feature set.

Prerequisites:
  pip install graphiti-core
  Neo4j running locally (Docker is easiest)
  OPENAI_API_KEY or Ollama configured per graphiti-core docs

Defaults to N=30 episodes (Graphiti's LLM extraction is heavier than
Mem0's; allow ~10-20 min wall time).
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

from experiments.gc_retrieval_f1_benchmark import (
    QAItem,
    RetrievalF1Result,
    _compute_f1,
    _load_squad_corpus,
)
from runner.gc_runner import compute_retrieval_gate


def _build_graphiti(uri: str, user: str, password: str,
                    llm_provider: str = "openai",
                    ollama_base: str = "http://localhost:11434/v1",
                    ollama_llm_model: str = "phi3:mini",
                    ollama_embed_model: str = "all-minilm:latest",
                    ollama_embed_dim: int = 384):
    """Build a Graphiti client.

    llm_provider='openai'  -> default OpenAI client (needs OPENAI_API_KEY)
    llm_provider='ollama'  -> openai_generic_client pointed at local Ollama
                              (works with same Ollama mem0_retrieval_f1
                              benchmark uses; no API key needed)
    """
    try:
        from graphiti_core import Graphiti
    except ImportError as e:
        raise ImportError(
            "graphiti-core not installed. Run: pip install graphiti-core"
        ) from e

    if llm_provider == "ollama":
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        llm_config = LLMConfig(
            api_key="ollama",
            model=ollama_llm_model,
            base_url=ollama_base,
            temperature=0.0,
        )
        llm_client = OpenAIGenericClient(config=llm_config)
        embedder = OpenAIEmbedder(config=OpenAIEmbedderConfig(
            api_key="ollama",
            embedding_model=ollama_embed_model,
            base_url=ollama_base,
            embedding_dim=ollama_embed_dim,
        ))
        # Reranker also needs an OpenAI-compat endpoint; reuse the
        # same Ollama LLM config (Graphiti calls it as a regular LLM)
        cross_encoder = OpenAIRerankerClient(config=llm_config)
        return Graphiti(
            uri=uri, user=user, password=password,
            llm_client=llm_client, embedder=embedder,
            cross_encoder=cross_encoder,
        )
    return Graphiti(uri=uri, user=user, password=password)


def _run_eval_via_graphiti(
    mw,
    qa_items: list[QAItem],
    when: str,
    top_k: int = 20,
) -> RetrievalF1Result:
    """Run all queries through Graphiti; compute F1 against ground truth.

    Graphiti's search returns edges (each with source_node_uuid +
    target_node_uuid). The adapter's search() already records query
    events; we use the returned edges to determine "retrieved nodes"
    for F1 scoring.
    """
    precisions, recalls, f1s = [], [], []
    n_perfect = 0
    n_zero = 0
    for qa in qa_items:
        try:
            result = mw.search(qa.query, num_results=top_k)
            # Result is a list of edges; collect both endpoints as the
            # "predicted" set
            predicted = set()
            for edge in result if isinstance(result, list) else []:
                for attr in ("source_node_uuid", "target_node_uuid"):
                    uuid = str(getattr(edge, attr, None) or "")
                    if uuid:
                        predicted.add(uuid)
        except Exception:
            predicted = set()
        p, r, f = _compute_f1(predicted, qa.ground_truth_ids)
        precisions.append(p)
        recalls.append(r)
        f1s.append(f)
        if r == 1.0:
            n_perfect += 1
        if r == 0.0:
            n_zero += 1
    n = len(qa_items)
    return RetrievalF1Result(
        when=when,
        n_queries=n,
        avg_precision=sum(precisions) / max(1, n),
        avg_recall=sum(recalls) / max(1, n),
        avg_f1=sum(f1s) / max(1, n),
        perfect_recall_pct=100 * n_perfect / max(1, n),
        zero_recall_pct=100 * n_zero / max(1, n),
    )


def main():
    p = argparse.ArgumentParser(prog="graphiti-retrieval-f1")
    p.add_argument("--n-pairs", type=int, default=30)
    p.add_argument("--aged-fraction", type=float, default=0.4)
    p.add_argument("--backdate-days", type=float, default=10.0)
    p.add_argument("--variant", default="gc-v0.1.8-comprehensive-tuned")
    p.add_argument("--min-age-seconds", type=float, default=86400.0)
    p.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j-user", default="neo4j")
    p.add_argument("--neo4j-password", default="changeme")
    p.add_argument("--rebuild-indices", action="store_true")
    p.add_argument("--llm-provider", choices=["openai", "ollama"], default="openai",
                   help="LLM client to wire into Graphiti (ollama = local, "
                        "needs Ollama running with the embed + llm models pulled)")
    p.add_argument("--ollama-base", default="http://localhost:11434/v1")
    p.add_argument("--ollama-llm-model", default="phi3:mini")
    p.add_argument("--ollama-embed-model", default="all-minilm:latest")
    p.add_argument("--ollama-embed-dim", type=int, default=384)
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--profile", default=None,
                   help="v0.2.x profile name (e.g. 'finance-aggressive'). "
                        "Overrides --variant and builds the v0.2.5 bundle "
                        "from runner/dimensions/memory/lifecycle/profiles/<name>.yaml")
    args = p.parse_args()

    print("=" * 78)
    print("Real-Graphiti retrieval F1 benchmark (UC-GC-RETRIEVAL)")
    print("=" * 78)
    print(f"Corpus: SQuAD subset, {args.n_pairs} Q&A pairs, "
          f"aged_fraction={args.aged_fraction}")
    print(f"Variant: {args.variant} (min_age={args.min_age_seconds}s)")
    print()

    print("Connecting to Graphiti / Neo4j...")
    t0 = time.time()
    try:
        graphiti = _build_graphiti(
            uri=args.neo4j_uri, user=args.neo4j_user,
            password=args.neo4j_password,
            llm_provider=args.llm_provider,
            ollama_base=args.ollama_base,
            ollama_llm_model=args.ollama_llm_model,
            ollama_embed_model=args.ollama_embed_model,
            ollama_embed_dim=args.ollama_embed_dim,
        )
    except ImportError as e:
        print(f"  {e}")
        return 1
    print(f"  Graphiti ready in {time.time()-t0:.1f}s")

    from runner.dimensions.memory.lifecycle import FACTORIES
    from runner.dimensions.memory.lifecycle.integrations import (
        GraphitiGCMiddleware,
    )
    if args.profile:
        from runner.dimensions.memory.lifecycle.profile_loader import (
            build_from_profile,
        )
        variant = build_from_profile(args.profile)
        # When using a profile, args.variant is overridden to the bundle id
        # for artifact-emission consistency
        args.variant = "gc-v0.2.5-comprehensive-graph-tuned"
        print(f"  Using profile: {args.profile} -> {variant.__class__.__name__}")
    else:
        variant_cls = FACTORIES[args.variant]
        try:
            variant = variant_cls(min_age_seconds=args.min_age_seconds)
        except TypeError:
            variant = variant_cls()
    mw = GraphitiGCMiddleware(graphiti)

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

    print("Loading SQuAD subset...")
    memories, qa_items = _load_squad_corpus(
        n_pairs=args.n_pairs, aged_fraction=args.aged_fraction, seed=42,
    )
    print(f"  {len(memories)} unique contexts, {len(qa_items)} queries")

    print("Adding episodes to Graphiti (LLM extraction)...")
    squad_to_graphiti: dict[str, list[str]] = {}
    add_start = time.time()
    for i, (squad_id, text, is_aged) in enumerate(memories):
        if (i + 1) % 5 == 0:
            print(f"  added {i+1}/{len(memories)} "
                  f"(wall {time.time()-add_start:.1f}s)")
        try:
            from datetime import datetime, timezone
            result = mw.add_episode(
                name=f"squad_{squad_id}", episode_body=text,
                group_id="f1_user",
                source_description="SQuAD context",
                reference_time=datetime.now(timezone.utc),
            )
            # Map squad_id to both the episode and extracted entities
            ids: list[str] = []
            ep = getattr(result, "episode", None)
            if ep is not None:
                ids.append(str(getattr(ep, "uuid", "")))
            for node in getattr(result, "nodes", []) or []:
                ids.append(str(getattr(node, "uuid", "")))
            squad_to_graphiti[squad_id] = [i for i in ids if i]
        except Exception as e:
            print(f"  add error at i={i}: {e}")
    add_seconds = time.time() - add_start
    print(f"  done in {add_seconds:.1f}s "
          f"({add_seconds/max(1,len(memories)):.2f}s/add)")

    # Translate ground truth to Graphiti uuid-space
    qa_items_g = []
    for qa in qa_items:
        mapped_gt = set()
        for sq_id in qa.ground_truth_ids:
            mapped_gt.update(squad_to_graphiti.get(sq_id, []))
        qa_items_g.append(QAItem(
            query_id=qa.query_id, query=qa.query,
            ground_truth_ids=mapped_gt,
        ))

    # Backdate aged subset
    aged_squad_ids = {sq for sq, _, is_aged in memories if is_aged}
    backdate = time.time() - args.backdate_days * 86400
    n_backdated = 0
    for sq_id in aged_squad_ids:
        for gid in squad_to_graphiti.get(sq_id, []):
            if gid in mw._records:
                mw._records[gid].added_at = backdate
                mw._records[gid].last_access = backdate
                n_backdated += 1
    print(f"  backdated {n_backdated} nodes by {args.backdate_days} days")
    print()

    # BEFORE F1
    print("Running queries BEFORE sweep...")
    t0 = time.time()
    before = _run_eval_via_graphiti(mw, qa_items_g, when="before_sweep")
    print(f"  {len(qa_items)} queries in {time.time()-t0:.1f}s")
    print(f"  precision={before.avg_precision:.3f}, recall={before.avg_recall:.3f}, "
          f"F1={before.avg_f1:.3f}")
    print()

    print(f"Running sweep with {variant.name}...")
    t0 = time.time()
    n_before_sweep = len(mw._records)
    n_removed = mw.sweep(variant, current_time=time.time())
    sweep_seconds = time.time() - t0
    print(f"  swept {n_removed} of {n_before_sweep} nodes in {sweep_seconds:.3f}s")
    reduction_pct = 100 * n_removed / max(1, n_before_sweep)
    print()

    print("Running queries AFTER sweep...")
    after = _run_eval_via_graphiti(mw, qa_items_g, when="after_sweep")
    print(f"  precision={after.avg_precision:.3f}, recall={after.avg_recall:.3f}, "
          f"F1={after.avg_f1:.3f}")
    print()

    gate = compute_retrieval_gate(
        f1_before=before.avg_f1, f1_after=after.avg_f1,
        store_reduction_pct=reduction_pct,
    )
    print("=" * 78)
    print(f"UC-GC-RETRIEVAL: [{gate['status']}] {gate['name']}")
    print(f"  {gate['reason']}")
    print("=" * 78)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "graphiti_retrieval_f1"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    from runner.artifacts import emit_dimension_artifact
    emit_dimension_artifact(
        opportunity="memory_lifecycle",
        dimension="memory.lifecycle",
        stage=5,
        experiment_name="Real-Graphiti retrieval F1 benchmark",
        variants=[{
            "id": args.variant, "role": "candidate",
            "profile": args.profile,
        }],
        workload={
            "archetype": "real-data-squad",
            "n": args.n_pairs,
            "seed": 42,
            "params": {
                "aged_fraction": args.aged_fraction,
                "backdate_days": args.backdate_days,
            },
        },
        metrics={
            "retrieval_f1_before": before.avg_f1,
            "retrieval_f1_after": after.avg_f1,
            "retrieval_precision_before": before.avg_precision,
            "retrieval_precision_after": after.avg_precision,
            "retrieval_recall_before": before.avg_recall,
            "retrieval_recall_after": after.avg_recall,
            "reduction_pct": reduction_pct,
            "n_records_before_sweep": n_before_sweep,
            "n_removed": n_removed,
            "n_remaining": len(mw._records),
            "add_seconds": add_seconds,
            "sweep_seconds": sweep_seconds,
        },
        gates={"UC-GC-RETRIEVAL": gate},
        decision=gate["status"],
        environment={
            "llm_provider": args.llm_provider,
            "llm_model": getattr(args, "ollama_llm_model", None) if args.llm_provider == "ollama" else "openai-default",
            "embedder": getattr(args, "ollama_embed_model", None) if args.llm_provider == "ollama" else "openai-default",
            "min_age_seconds": args.min_age_seconds,
            "neo4j_uri": args.neo4j_uri,
        },
        out_path=out_path,
    )
    try:
        display_path = out_path.relative_to(ROOT)
    except ValueError:
        display_path = out_path
    print(f"\nArtifact: {display_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

"""Retrieval-quality F1 benchmark backed by the real Mem0 adapter.

Plugs the F1 scaffold into the actual Mem0GCMiddleware so the
retrieval pipeline is REAL (Mem0's vector + reranker), not the
substring placeholder the bare scaffold uses.

Workflow:
  1. Build Mem0 with Ollama + local Qdrant (same config as the
     smoke-test script)
  2. Load a real Q&A corpus (SQuAD subset via the F1 scaffold's
     loader; HotpotQA blocked on HF)
  3. Add each context as a Mem0 memory via mw.add()
  4. Backdate the 'aged' subset by manipulating the sidecar timestamps
  5. Run all queries; measure F1 BEFORE the sweep using mw.search()
  6. Run mw.sweep(variant); measure F1 AFTER
  7. Report UC-GC-RETRIEVAL gate verdict

This is the credibility-anchor benchmark the analyst named: real
retrieval pipeline + real Q&A corpus + real GC variants + measured
F1 preservation.

Defaults to N=50 to keep wall time manageable (~5 min at 2-3s per add).
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


def _build_memory(config: dict):
    from mem0 import Memory
    return Memory.from_config(config)


def _run_eval_via_mem0(
    mw,
    qa_items: list[QAItem],
    when: str,
    top_k: int = 20,
    user_id: str = "f1_user",
) -> RetrievalF1Result:
    """Run all queries through Mem0; compute F1 against ground truth."""
    precisions, recalls, f1s = [], [], []
    n_perfect = 0
    n_zero = 0
    for qa in qa_items:
        try:
            # user_id is required by Mem0 v2; the adapter translates
            # it into filters={'user_id': ...} per its search() contract
            result = mw.search(qa.query, top_k=top_k, user_id=user_id)
            hits = result.get("results", []) if isinstance(result, dict) else []
            # Mem0 returns memory dicts with our doc_id stored in
            # metadata.user_id... actually Mem0's id is the Mem0 memory_id,
            # not our doc_id. The adapter records both via record_write
            # but we need to map back.
            # For the retrieval F1 to work, ground_truth_ids must be the
            # ADAPTER's mem_ids, not the SQuAD ctx_ids. We handle this
            # mapping in the workflow.
            predicted = {str(h.get("id")) for h in hits if h.get("id")}
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
    p = argparse.ArgumentParser(prog="mem0-retrieval-f1")
    p.add_argument("--n-pairs", type=int, default=50,
                   help="Number of SQuAD Q&A pairs (default 50)")
    p.add_argument("--aged-fraction", type=float, default=0.4)
    p.add_argument("--backdate-days", type=float, default=10.0)
    p.add_argument("--variant", default="gc-v0.1.8-comprehensive-tuned")
    p.add_argument("--min-age-seconds", type=float, default=86400.0)
    p.add_argument("--llm-model", default="phi3:mini")
    p.add_argument("--embed-model", default="all-minilm:latest")
    p.add_argument("--qdrant-path", default="/tmp/qdrant_mem0_f1")
    p.add_argument("--history-db", default="/tmp/mem0_f1_history.db")
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--seed", type=int, default=42,
                   help="SQuAD subset selection seed (for multi-seed CIs)")
    args = p.parse_args()

    print("=" * 78)
    print("Real-Mem0 retrieval F1 benchmark (UC-GC-RETRIEVAL)")
    print("=" * 78)
    print(f"Corpus: SQuAD subset, {args.n_pairs} Q&A pairs, "
          f"aged_fraction={args.aged_fraction}")
    print(f"Variant: {args.variant} (min_age={args.min_age_seconds}s)")
    print()

    # Wipe any prior run state for a clean smoke test
    import shutil
    for path in [args.qdrant_path, args.history_db]:
        Path(path).is_file() and Path(path).unlink()
        if Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)

    config = {
        "llm": {"provider": "ollama", "config": {
            "model": args.llm_model,
            "ollama_base_url": "http://localhost:11434",
            "temperature": 0.0,
        }},
        "embedder": {"provider": "ollama", "config": {
            "model": args.embed_model,
            "ollama_base_url": "http://localhost:11434",
        }},
        "vector_store": {"provider": "qdrant", "config": {
            "collection_name": "mem0_f1",
            "path": args.qdrant_path,
            "embedding_model_dims": 384,
        }},
        "history_db_path": args.history_db,
    }

    print("Instantiating Mem0 + adapter...")
    t0 = time.time()
    memory = _build_memory(config)
    print(f"  Memory ready in {time.time()-t0:.1f}s")

    from runner.dimensions.memory.lifecycle import FACTORIES
    from runner.dimensions.memory.lifecycle.integrations import Mem0GCMiddleware
    variant_cls = FACTORIES[args.variant]
    try:
        variant = variant_cls(min_age_seconds=args.min_age_seconds)
    except TypeError:
        variant = variant_cls()
    mw = Mem0GCMiddleware(memory)
    print()

    print("Loading SQuAD subset...")
    memories, qa_items = _load_squad_corpus(
        n_pairs=args.n_pairs, aged_fraction=args.aged_fraction,
        seed=args.seed,
    )
    print(f"  {len(memories)} unique contexts, {len(qa_items)} queries")

    # Add memories via the adapter; track squad_ctx_id -> mem0_id mapping
    # so we can rewrite ground truth in Mem0 id-space
    print("Adding contexts to Mem0 (LLM extraction)...")
    squad_to_mem0: dict[str, list[str]] = {}
    add_start = time.time()
    for i, (squad_id, text, is_aged) in enumerate(memories):
        if (i + 1) % 10 == 0:
            print(f"  added {i+1}/{len(memories)} (wall {time.time()-add_start:.1f}s)")
        try:
            result = mw.add(text, user_id="f1_user")
            if isinstance(result, dict):
                mem_ids = [str(r.get("id")) for r in result.get("results", []) if r.get("id")]
                squad_to_mem0[squad_id] = mem_ids
        except Exception as e:
            print(f"  add error at i={i}: {e}")
    add_seconds = time.time() - add_start
    print(f"  done in {add_seconds:.1f}s ({add_seconds/max(1,len(memories)):.2f}s/add)")
    print(f"  squad-to-mem0 mappings: {len(squad_to_mem0)}")

    # Translate ground truth from squad_ctx_ids to mem0 memory_ids
    qa_items_mem0 = []
    for qa in qa_items:
        mapped_gt = set()
        for sq_id in qa.ground_truth_ids:
            mapped_gt.update(squad_to_mem0.get(sq_id, []))
        qa_items_mem0.append(QAItem(
            query_id=qa.query_id, query=qa.query,
            ground_truth_ids=mapped_gt,
        ))

    # Backdate aged memories so they meet min_age
    aged_squad_ids = {sq for sq, _, is_aged in memories if is_aged}
    backdate = time.time() - args.backdate_days * 86400
    n_backdated = 0
    for sq_id in aged_squad_ids:
        for mem0_id in squad_to_mem0.get(sq_id, []):
            if mem0_id in mw._records:
                mw._records[mem0_id].added_at = backdate
                mw._records[mem0_id].last_access = backdate
                n_backdated += 1
    print(f"  backdated {n_backdated} memories by {args.backdate_days} days")
    print()

    # BEFORE F1
    print("Running queries BEFORE sweep...")
    t0 = time.time()
    before = _run_eval_via_mem0(mw, qa_items_mem0, when="before_sweep")
    print(f"  {len(qa_items)} queries in {time.time()-t0:.1f}s")
    print(f"  precision={before.avg_precision:.3f}, recall={before.avg_recall:.3f}, "
          f"F1={before.avg_f1:.3f}")
    print()

    # Sweep
    print(f"Running sweep with {variant.name}...")
    t0 = time.time()
    n_removed = mw.sweep(variant, current_time=time.time())
    sweep_seconds = time.time() - t0
    print(f"  swept {n_removed} memories in {sweep_seconds:.3f}s")
    n_remaining = len(mw._records)
    initial_n = sum(len(v) for v in squad_to_mem0.values())
    reduction_pct = 100 * n_removed / max(1, initial_n)
    print(f"  reduction: {reduction_pct:.1f}% ({n_removed} of {initial_n})")
    print()

    # AFTER F1
    print("Running queries AFTER sweep...")
    t0 = time.time()
    after = _run_eval_via_mem0(mw, qa_items_mem0, when="after_sweep")
    print(f"  precision={after.avg_precision:.3f}, recall={after.avg_recall:.3f}, "
          f"F1={after.avg_f1:.3f}")
    print()

    # UC-GC-RETRIEVAL verdict
    gate = compute_retrieval_gate(
        f1_before=before.avg_f1, f1_after=after.avg_f1,
        store_reduction_pct=reduction_pct,
    )
    print("=" * 78)
    print(f"UC-GC-RETRIEVAL: [{gate['status']}] {gate['name']}: {gate['reason']}")
    print("=" * 78)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "mem0_retrieval_f1"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    # Standardized dimension artifact (schema v1)
    from runner.artifacts import emit_dimension_artifact
    emit_dimension_artifact(
        opportunity="memory_lifecycle",
        dimension="memory.lifecycle",
        stage=5,
        experiment_name="Real-Mem0 retrieval F1 benchmark",
        variants=[{"id": args.variant, "role": "candidate"}],
        workload={
            "archetype": "real-data-squad",
            "n": args.n_pairs,
            "seed": args.seed,
            "params": {
                "aged_fraction": args.aged_fraction,
                "backdate_days": args.backdate_days,
                "n_initial_memories": initial_n,
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
            "n_removed": n_removed,
            "n_remaining": n_remaining,
            "add_seconds": add_seconds,
            "sweep_seconds": sweep_seconds,
        },
        gates={"UC-GC-RETRIEVAL": gate},
        decision=gate["status"],
        environment={
            "llm_model": args.llm_model,
            "embedder": args.embed_model,
            "min_age_seconds": args.min_age_seconds,
        },
        out_path=out_path,
    )
    try:
        display_path = out_path.relative_to(ROOT)
    except ValueError:
        display_path = out_path
    print(f"\nArtifact: {display_path}")


if __name__ == "__main__":
    main()

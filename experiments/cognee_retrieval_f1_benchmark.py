"""Retrieval-quality F1 benchmark backed by the real Cognee adapter.

Parallel to mem0_retrieval_f1_benchmark.py and graphiti_retrieval_f1_benchmark.py
but uses CogneeGCMiddleware (module-level API).

Workflow:
  1. Import cognee module (fail gracefully if not installed)
  2. Load SQuAD subset
  3. mw.add(context) for each (Cognee stores raw text)
  4. mw.cognify(datasets=...) once or per batch (LLM extracts entities)
  5. Backdate aged subset
  6. Search before sweep
  7. mw.sweep(variant); search after
  8. UC-GC-RETRIEVAL verdict

Prerequisites:
  pip install cognee
  Cognee's own config (OpenAI API key by default; can be configured
    for Ollama per Cognee docs)

Defaults to N=30 contexts (Cognee's cognify pipeline is heavier than
single-call adds; allow time).
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


def _import_cognee():
    try:
        import cognee
        return cognee
    except ImportError as e:
        raise ImportError(
            "cognee not installed. Run: pip install cognee"
        ) from e


def _run_eval_via_cognee(
    mw,
    qa_items: list[QAItem],
    when: str,
    top_k: int = 20,
) -> RetrievalF1Result:
    """Run all queries through Cognee; compute F1 against ground truth.

    Cognee's search returns matched nodes (the adapter records query
    events on each). For F1 scoring, the predicted set is the set of
    node ids the search returned.
    """
    precisions, recalls, f1s = [], [], []
    n_perfect = 0
    n_zero = 0
    for qa in qa_items:
        try:
            # Cognee's search signature: search(query_type, query_text, ...)
            # Use "similarity" as the default query type; real benchmarks
            # may use other types (e.g., "graph_completion")
            result = mw.search("similarity", qa.query)
            predicted = set()
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        node_id = str(item.get("id") or item.get("uuid") or "")
                        if node_id:
                            predicted.add(node_id)
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
    p = argparse.ArgumentParser(prog="cognee-retrieval-f1")
    p.add_argument("--n-pairs", type=int, default=30)
    p.add_argument("--aged-fraction", type=float, default=0.4)
    p.add_argument("--backdate-days", type=float, default=10.0)
    p.add_argument("--variant", default="gc-v0.1.8-comprehensive-tuned")
    p.add_argument("--min-age-seconds", type=float, default=86400.0)
    p.add_argument("--dataset-name", default="squad_f1")
    p.add_argument("--cognify-batch-size", type=int, default=10,
                   help="Run cognee.cognify() every N adds (cognify is heavy)")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Real-Cognee retrieval F1 benchmark (UC-GC-RETRIEVAL)")
    print("=" * 78)
    print(f"Corpus: SQuAD subset, {args.n_pairs} Q&A pairs, "
          f"aged_fraction={args.aged_fraction}")
    print(f"Variant: {args.variant} (min_age={args.min_age_seconds}s)")
    print()

    print("Importing Cognee...")
    try:
        cognee = _import_cognee()
    except ImportError as e:
        print(f"  {e}")
        return 1
    print(f"  Cognee module loaded")

    from runner.dimensions.memory.lifecycle import FACTORIES
    from runner.dimensions.memory.lifecycle.integrations import (
        CogneeGCMiddleware,
    )
    variant_cls = FACTORIES[args.variant]
    try:
        variant = variant_cls(min_age_seconds=args.min_age_seconds)
    except TypeError:
        variant = variant_cls()
    mw = CogneeGCMiddleware(cognee)
    print()

    print("Loading SQuAD subset...")
    memories, qa_items = _load_squad_corpus(
        n_pairs=args.n_pairs, aged_fraction=args.aged_fraction, seed=42,
    )
    print(f"  {len(memories)} unique contexts, {len(qa_items)} queries")

    print("Adding contexts to Cognee + periodic cognify...")
    squad_to_cognee: dict[str, list[str]] = {}
    add_start = time.time()
    batch_count = 0
    for i, (squad_id, text, is_aged) in enumerate(memories):
        if (i + 1) % 5 == 0:
            print(f"  added {i+1}/{len(memories)} "
                  f"(wall {time.time()-add_start:.1f}s)")
        try:
            result = mw.add(text, dataset_name=args.dataset_name)
            doc_id = result.get("doc_id") if isinstance(result, dict) else None
            if doc_id:
                squad_to_cognee[squad_id] = [doc_id]
            batch_count += 1
            if batch_count >= args.cognify_batch_size:
                print(f"  cognifying batch (size {batch_count})...")
                try:
                    mw.cognify(datasets=[args.dataset_name])
                except Exception as e:
                    print(f"    cognify error: {e}")
                batch_count = 0
        except Exception as e:
            print(f"  add error at i={i}: {e}")
    # Final cognify
    if batch_count > 0:
        try:
            mw.cognify(datasets=[args.dataset_name])
        except Exception as e:
            print(f"  final cognify error: {e}")
    add_seconds = time.time() - add_start
    print(f"  done in {add_seconds:.1f}s "
          f"({add_seconds/max(1,len(memories)):.2f}s/add)")

    # Translate ground truth
    qa_items_c = []
    for qa in qa_items:
        mapped_gt = set()
        for sq_id in qa.ground_truth_ids:
            mapped_gt.update(squad_to_cognee.get(sq_id, []))
        qa_items_c.append(QAItem(
            query_id=qa.query_id, query=qa.query,
            ground_truth_ids=mapped_gt,
        ))

    # Backdate aged subset
    aged_squad_ids = {sq for sq, _, is_aged in memories if is_aged}
    backdate = time.time() - args.backdate_days * 86400
    n_backdated = 0
    for sq_id in aged_squad_ids:
        for cid in squad_to_cognee.get(sq_id, []):
            if cid in mw._records:
                mw._records[cid].added_at = backdate
                mw._records[cid].last_access = backdate
                n_backdated += 1
    print(f"  backdated {n_backdated} docs by {args.backdate_days} days")
    print()

    print("Running queries BEFORE sweep...")
    t0 = time.time()
    before = _run_eval_via_cognee(mw, qa_items_c, when="before_sweep")
    print(f"  {len(qa_items)} queries in {time.time()-t0:.1f}s")
    print(f"  precision={before.avg_precision:.3f}, recall={before.avg_recall:.3f}, "
          f"F1={before.avg_f1:.3f}")
    print()

    print(f"Running sweep with {variant.name}...")
    t0 = time.time()
    n_before_sweep = len(mw._records)
    n_removed = mw.sweep(variant, current_time=time.time())
    sweep_seconds = time.time() - t0
    print(f"  swept {n_removed} of {n_before_sweep} in {sweep_seconds:.3f}s")
    reduction_pct = 100 * n_removed / max(1, n_before_sweep)
    print()

    print("Running queries AFTER sweep...")
    after = _run_eval_via_cognee(mw, qa_items_c, when="after_sweep")
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
        out_dir = ROOT / "runs" / "cognee_retrieval_f1"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    raw = {
        "experiment": "Real-Cognee retrieval F1 benchmark",
        "n_pairs": args.n_pairs,
        "aged_fraction": args.aged_fraction,
        "backdate_days": args.backdate_days,
        "variant": args.variant,
        "min_age_seconds": args.min_age_seconds,
        "n_records_before_sweep": n_before_sweep,
        "n_removed": n_removed,
        "n_remaining": len(mw._records),
        "reduction_pct": reduction_pct,
        "add_seconds": add_seconds,
        "sweep_seconds": sweep_seconds,
        "before": {
            "precision": before.avg_precision,
            "recall": before.avg_recall,
            "f1": before.avg_f1,
        },
        "after": {
            "precision": after.avg_precision,
            "recall": after.avg_recall,
            "f1": after.avg_f1,
        },
        "uc_gc_retrieval_gate": gate,
    }
    # Standardized dimension artifact (schema v1)
    from runner.artifacts import emit_dimension_artifact
    emit_dimension_artifact(
        opportunity="memory_lifecycle",
        dimension="memory.lifecycle",
        stage=5,
        experiment_name="Real-Cognee retrieval F1 benchmark",
        variants=[{"id": args.variant, "role": "candidate"}],
        workload={
            "archetype": "real-data-squad",
            "n": args.n_pairs,
            "seed": 42,
            "params": {
                "aged_fraction": args.aged_fraction,
                "backdate_days": args.backdate_days,
                "dataset_name": args.dataset_name,
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
            "min_age_seconds": args.min_age_seconds,
        },
        raw=raw,
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

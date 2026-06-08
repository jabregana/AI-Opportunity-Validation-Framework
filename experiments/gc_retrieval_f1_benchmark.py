"""Retrieval-quality F1 benchmark scaffold (Phase 3 of synthesis plan).

Replaces UC-GC-2's entity-survival proxy with a measured retrieval F1
metric. Workflow:

  1. Populate a memory store with N facts that have known canonical IDs.
  2. Generate Q queries with known ground-truth memory IDs (one or
     more "correct" memories per query).
  3. Run the queries BEFORE any GC sweep; record per-query F1.
  4. Run a GC sweep with the variant under test.
  5. Run the same queries AFTER the sweep; record per-query F1.
  6. Report: did the variant preserve retrieval F1 while reducing
     store size?

This is a SCAFFOLD: the real version plugs into a Mem0 / Graphiti
deployment with a real retrieval-quality dataset (HotpotQA subset,
or a custom Q&A corpus). The scaffold uses synthetic Q&A with
explicit ground-truth so the metric calculation is verified end-to-end.

Output: UC-GC-2-RETRIEVAL gate values (precision, recall, F1 before
+ after) which can replace the entity-survival proxy in future
benchmarks.
"""
from __future__ import annotations
import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.dimensions.memory.lifecycle import FACTORIES, GraphState


@dataclass
class QAItem:
    """One query with ground-truth memory IDs."""

    query_id: str
    query: str
    ground_truth_ids: set[str]


@dataclass
class RetrievalF1Result:
    """One run's retrieval-quality measurement."""

    when: str  # "before_sweep" or "after_sweep"
    n_queries: int
    avg_precision: float
    avg_recall: float
    avg_f1: float
    perfect_recall_pct: float  # fraction of queries with recall == 1.0
    zero_recall_pct: float  # fraction with recall == 0


def _generate_synthetic_corpus(
    n_memories: int = 200,
    n_queries: int = 50,
    seed: int = 42,
) -> tuple[list[tuple[str, str]], list[QAItem]]:
    """Generate (memories, qa_items) with known ground-truth links.

    Each memory has a deterministic ID. Each QA item has a query and
    a set of "correct" memory IDs that should be retrieved.

    For realistic ground-truth modeling: memories cluster by topic;
    queries target a specific cluster; the correct memories are those
    in the target cluster.
    """
    rng = random.Random(seed)
    topics = ["coffee", "engineering", "meetings", "travel", "books",
              "music", "fitness", "cooking"]
    memories: list[tuple[str, str]] = []  # (id, text)
    topic_memberships: dict[str, list[str]] = {t: [] for t in topics}

    for i in range(n_memories):
        topic = topics[i % len(topics)]
        mem_id = f"mem_{i:05d}"
        text = f"Memory about {topic}: synthetic content {i}"
        memories.append((mem_id, text))
        topic_memberships[topic].append(mem_id)

    qa_items: list[QAItem] = []
    for i in range(n_queries):
        topic = topics[i % len(topics)]
        # Ground truth = all memories of this topic
        qa_items.append(QAItem(
            query_id=f"q_{i:05d}",
            query=f"Tell me about {topic}",
            ground_truth_ids=set(topic_memberships[topic]),
        ))
    return memories, qa_items


def _populate_state(memories: list[tuple[str, str]]) -> GraphState:
    """Build a GraphState from the memory corpus (each memory is a fact).

    Mimics what a memory framework would have stored. Uses age=0 for
    all (caller can backdate to test sweep semantics).
    """
    state = GraphState()
    for mem_id, text in memories:
        state.nodes[mem_id] = {"kind": "fact", "added_at": 0.0}
        state.in_degree[mem_id] = 0
        state.out_degree[mem_id] = 0
        state.last_access[mem_id] = 0.0
        state.query_count[mem_id] = 0
    return state


def _retrieve(query: str, state: GraphState,
              memory_text: dict[str, str], top_k: int = 5) -> list[str]:
    """Naive retrieval: substring match against memory text.

    Real version plugs into Mem0/Graphiti search. The scaffold uses
    substring matching so the metric calculation is verified.
    """
    query_lower = query.lower()
    hits = [(mid, text) for mid, text in memory_text.items()
            if mid in state.nodes
            and any(word in text.lower() for word in query_lower.split())]
    return [mid for mid, _ in hits[:top_k]]


def _compute_f1(predicted: set[str], ground_truth: set[str]) -> tuple[float, float, float]:
    """Returns (precision, recall, f1)."""
    if not predicted:
        return 0.0, 0.0, 0.0
    if not ground_truth:
        return 1.0, 1.0, 1.0
    tp = len(predicted & ground_truth)
    precision = tp / len(predicted)
    recall = tp / len(ground_truth)
    if precision + recall == 0:
        return 0.0, 0.0, 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _run_retrieval_eval(
    state: GraphState,
    memory_text: dict[str, str],
    qa_items: list[QAItem],
    when: str,
) -> RetrievalF1Result:
    """Run all queries; aggregate F1."""
    precisions = []
    recalls = []
    f1s = []
    n_perfect = 0
    n_zero = 0
    for qa in qa_items:
        predicted = set(_retrieve(qa.query, state, memory_text, top_k=20))
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
    p = argparse.ArgumentParser(prog="gc-retrieval-f1-benchmark")
    p.add_argument("--n-memories", type=int, default=200)
    p.add_argument("--n-queries", type=int, default=50)
    p.add_argument("--variants", default="gc-v0.1.2-fact-only,gc-v0.1.8-comprehensive-tuned")
    p.add_argument("--backdate-days", type=float, default=10.0,
                   help="Backdate memories so they meet min_age for GC")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Retrieval-quality F1 benchmark scaffold (replaces UC-GC-2 proxy)")
    print("=" * 78)
    print(f"N memories: {args.n_memories}, N queries: {args.n_queries}")
    print(f"Variants: {args.variants}")
    print()

    memories, qa_items = _generate_synthetic_corpus(
        n_memories=args.n_memories, n_queries=args.n_queries, seed=args.seed,
    )
    memory_text = {mid: text for mid, text in memories}

    variant_ids = [v.strip() for v in args.variants.split(",") if v.strip()]

    # BEFORE-SWEEP baseline (same for all variants since no GC has happened)
    state = _populate_state(memories)
    before = _run_retrieval_eval(state, memory_text, qa_items, when="before_sweep")
    print(f"BEFORE GC: precision={before.avg_precision:.3f}, "
          f"recall={before.avg_recall:.3f}, F1={before.avg_f1:.3f}, "
          f"perfect-recall={before.perfect_recall_pct:.1f}%")
    print()

    # For each variant, run a sweep and re-evaluate
    per_variant: dict[str, dict] = {}
    for vid in variant_ids:
        # Backdate all memories so they meet min_age
        state = _populate_state(memories)
        backdate = time.time() - args.backdate_days * 86400
        for mem_id in state.nodes:
            state.nodes[mem_id]["added_at"] = backdate
            state.last_access[mem_id] = backdate

        variant_cls = FACTORIES[vid]
        try:
            variant = variant_cls(min_age_seconds=86400.0)
        except TypeError:
            variant = variant_cls()

        # Sweep
        now = time.time()
        candidates = variant.collect_candidates(state, now)
        for cand_id in candidates:
            variant.collect(cand_id, state, current_time=now)

        # Re-eval
        after = _run_retrieval_eval(state, memory_text, qa_items, when="after_sweep")
        n_remaining = sum(1 for mid in memory_text if mid in state.nodes)
        reduction_pct = 100 * (args.n_memories - n_remaining) / max(1, args.n_memories)
        per_variant[vid] = {
            "before": {
                "precision": before.avg_precision,
                "recall": before.avg_recall,
                "f1": before.avg_f1,
                "perfect_recall_pct": before.perfect_recall_pct,
                "zero_recall_pct": before.zero_recall_pct,
            },
            "after": {
                "precision": after.avg_precision,
                "recall": after.avg_recall,
                "f1": after.avg_f1,
                "perfect_recall_pct": after.perfect_recall_pct,
                "zero_recall_pct": after.zero_recall_pct,
            },
            "store_reduction_pct": reduction_pct,
            "memories_remaining": n_remaining,
            "f1_preservation_pct": 100 * (after.avg_f1 / max(0.001, before.avg_f1)),
        }
        print(f"{vid}:")
        print(f"  AFTER GC:  precision={after.avg_precision:.3f}, "
              f"recall={after.avg_recall:.3f}, F1={after.avg_f1:.3f}")
        print(f"  Store reduction: {reduction_pct:.1f}% "
              f"({args.n_memories - n_remaining} of {args.n_memories} removed)")
        print(f"  F1 preservation: {per_variant[vid]['f1_preservation_pct']:.1f}%")
        print()

    # Pareto: which variant is best on (reduction, F1 preservation)?
    print("=" * 78)
    print("UC-GC-RETRIEVAL: variants ranked by F1 preservation given reduction")
    print("=" * 78)
    ranked = sorted(
        per_variant.items(),
        key=lambda x: (
            -x[1]["store_reduction_pct"],
            -x[1]["f1_preservation_pct"],
        ),
    )
    for vid, data in ranked:
        verdict = (
            "EXCELLENT" if data["f1_preservation_pct"] >= 95
            else "ACCEPTABLE" if data["f1_preservation_pct"] >= 80
            else "POOR"
        )
        print(f"  {vid}: {data['store_reduction_pct']:.1f}% reduction at "
              f"{data['f1_preservation_pct']:.1f}% F1 preservation ({verdict})")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "gc_retrieval_f1_benchmark"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "GC retrieval-quality F1 benchmark scaffold",
        "n_memories": args.n_memories,
        "n_queries": args.n_queries,
        "before_baseline": {
            "precision": before.avg_precision,
            "recall": before.avg_recall,
            "f1": before.avg_f1,
        },
        "per_variant": per_variant,
        "notes": (
            "Scaffold uses synthetic Q&A with substring retrieval. "
            "Replace _retrieve() with real Mem0/Graphiti search() for "
            "production-grade measurement."
        ),
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

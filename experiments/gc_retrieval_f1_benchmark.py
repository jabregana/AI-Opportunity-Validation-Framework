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


def _load_squad_corpus(
    n_pairs: int = 200,
    aged_fraction: float = 0.4,
    seed: int = 42,
) -> tuple[list[tuple[str, str, bool]], list[QAItem]]:
    """Load a SQuAD subset as a real-data corpus.

    SQuAD's shape: each example has (id, question, context, answers).
    For the F1 benchmark: deduplicated contexts become memories; each
    question becomes a query whose ground truth is the contexts that
    contain its answer.

    SQuAD is a single-hop QA dataset, which makes ground truth direct
    (one context per question). HotpotQA would be multi-hop but is
    currently broken on HF (ValueError on load).

    Returns (memories, qa_items) in the same shape as
    _generate_synthetic_corpus.
    """
    from datasets import load_dataset
    ds = load_dataset("rajpurkar/squad", split="validation")
    # Shuffle so we sample diverse contexts (consecutive SQuAD examples
    # share contexts heavily; the first 50 examples typically come from
    # 1-2 paragraphs)
    rng = random.Random(seed)
    indices = list(range(len(ds)))
    rng.shuffle(indices)

    context_to_id: dict[str, str] = {}
    memories: list[tuple[str, str, bool]] = []
    qa_items: list[QAItem] = []
    # Stop when the framework has both n_pairs queries AND n_pairs unique
    # contexts (or runs out of dataset)
    for idx in indices:
        if len(qa_items) >= n_pairs and len(memories) >= n_pairs:
            break
        ex = ds[int(idx)]
        context = ex["context"]
        if context not in context_to_id:
            mem_id = f"squad_ctx_{len(context_to_id):05d}"
            context_to_id[context] = mem_id
            is_aged = rng.random() < aged_fraction
            memories.append((mem_id, context, is_aged))
        if len(qa_items) < n_pairs:
            ctx_id = context_to_id[context]
            qa_items.append(QAItem(
                query_id=f"squad_q_{len(qa_items):05d}",
                query=ex["question"],
                ground_truth_ids={ctx_id},
            ))
    return memories, qa_items


def _generate_synthetic_corpus(
    n_memories: int = 200,
    n_queries: int = 50,
    seed: int = 42,
    aged_fraction: float = 0.4,
) -> tuple[list[tuple[str, str, bool]], list[QAItem]]:
    """Generate (memories, qa_items) with known ground-truth links.

    Each memory has (id, text, is_aged) where is_aged marks the ones
    that will be backdated to trigger GC collection. Ground truth for
    each query includes BOTH aged and recent memories of its topic;
    F1 preservation after sweep measures how well the GC variant
    preserved the recent (non-aged) memories of each topic.

    `aged_fraction` is the proportion of each topic's memories that
    will be marked aged. Default 0.4 (40 percent aged, 60 percent
    recent). Real benchmarks tune to the deployment's actual age
    distribution.
    """
    rng = random.Random(seed)
    topics = ["coffee", "engineering", "meetings", "travel", "books",
              "music", "fitness", "cooking"]
    memories: list[tuple[str, str, bool]] = []  # (id, text, is_aged)
    topic_memberships: dict[str, list[str]] = {t: [] for t in topics}
    topic_aged: dict[str, list[str]] = {t: [] for t in topics}

    for i in range(n_memories):
        topic = topics[i % len(topics)]
        mem_id = f"mem_{i:05d}"
        text = f"Memory about {topic}: synthetic content {i}"
        # Mark roughly aged_fraction of each topic's memories as aged
        is_aged = rng.random() < aged_fraction
        memories.append((mem_id, text, is_aged))
        topic_memberships[topic].append(mem_id)
        if is_aged:
            topic_aged[topic].append(mem_id)

    qa_items: list[QAItem] = []
    for i in range(n_queries):
        topic = topics[i % len(topics)]
        # Ground truth: ALL memories of this topic (aged + recent).
        # F1 preservation after sweep measures how many of these the
        # GC variant kept retrievable.
        qa_items.append(QAItem(
            query_id=f"q_{i:05d}",
            query=f"Tell me about {topic}",
            ground_truth_ids=set(topic_memberships[topic]),
        ))
    return memories, qa_items


STOPWORDS = {
    "tell", "me", "about", "what", "is", "the", "a", "an", "and", "or",
    "of", "to", "in", "on", "for", "show", "any", "give",
}


def _populate_state(
    memories: list[tuple[str, str, bool]],
    backdate_seconds: float,
) -> GraphState:
    """Build a GraphState from the memory corpus.

    Recent memories use added_at=now (won't be collected at min_age=1d).
    Aged memories use added_at=now-backdate_seconds (will be collected
    if backdate exceeds the variant's min_age).
    """
    state = GraphState()
    now = time.time()
    for mem_id, text, is_aged in memories:
        added = now - backdate_seconds if is_aged else now
        state.nodes[mem_id] = {"kind": "fact", "added_at": added}
        state.in_degree[mem_id] = 0
        state.out_degree[mem_id] = 0
        state.last_access[mem_id] = added
        state.query_count[mem_id] = 0
    return state


def _retrieve(query: str, state: GraphState,
              memory_text: dict[str, str],
              top_k: int = 20) -> list[str]:
    """Retrieval with stopword filtering. Matches on remaining content
    words after removing common English stopwords. Closer to what a
    real semantic search would produce on this corpus.
    """
    content_words = [
        w for w in query.lower().split()
        if w not in STOPWORDS and len(w) > 1
    ]
    if not content_words:
        return []
    hits = [
        (mid, text) for mid, text in memory_text.items()
        if mid in state.nodes
        and any(w in text.lower() for w in content_words)
    ]
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
                   help="Backdate the AGED subset of memories")
    p.add_argument("--aged-fraction", type=float, default=0.4,
                   help="Fraction of memories that are 'old' (subject "
                        "to collection); rest are 'fresh' and survive")
    p.add_argument("--use-squad", action="store_true",
                   help="Use SQuAD validation subset for real-data Q&A "
                        "instead of synthetic corpus")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    print("=" * 78)
    print("Retrieval-quality F1 benchmark scaffold (replaces UC-GC-2 proxy)")
    print("=" * 78)
    print(f"N memories: {args.n_memories}, N queries: {args.n_queries}")
    print(f"Variants: {args.variants}")
    print()

    if args.use_squad:
        memories, qa_items = _load_squad_corpus(
            n_pairs=args.n_queries, aged_fraction=args.aged_fraction,
            seed=args.seed,
        )
        print(f"Corpus: SQuAD validation subset, {len(memories)} unique "
              f"contexts, {len(qa_items)} queries")
    else:
        memories, qa_items = _generate_synthetic_corpus(
            n_memories=args.n_memories, n_queries=args.n_queries,
            seed=args.seed, aged_fraction=args.aged_fraction,
        )
        print(f"Corpus: synthetic ({args.n_memories} memories, "
              f"{args.n_queries} queries)")
    memory_text = {mid: text for mid, text, _ in memories}
    n_aged = sum(1 for _, _, is_aged in memories if is_aged)
    print(f"  {n_aged} aged ({100*n_aged/max(1, len(memories)):.0f}%), "
          f"{len(memories) - n_aged} fresh")

    variant_ids = [v.strip() for v in args.variants.split(",") if v.strip()]

    # BEFORE-SWEEP baseline (same for all variants since no GC has happened)
    state = _populate_state(memories, backdate_seconds=args.backdate_days * 86400)
    before = _run_retrieval_eval(state, memory_text, qa_items, when="before_sweep")
    print(f"BEFORE GC: precision={before.avg_precision:.3f}, "
          f"recall={before.avg_recall:.3f}, F1={before.avg_f1:.3f}, "
          f"perfect-recall={before.perfect_recall_pct:.1f}%")
    print()

    # For each variant, run a sweep and re-evaluate
    per_variant: dict[str, dict] = {}
    for vid in variant_ids:
        # Fresh state with the same aged/fresh split as the baseline
        state = _populate_state(
            memories, backdate_seconds=args.backdate_days * 86400,
        )

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

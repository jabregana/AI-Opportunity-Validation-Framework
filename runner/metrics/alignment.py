"""Alignment metrics for schema-alignment use cases.

Pairwise F1 is the primary metric for UC-4.1: treat each pair of inputs
(i, j) as a binary problem ("should i and j map to the same canonical?")
and score the proxy's predicted clustering against the oracle's.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AlignmentResult:
    precision: float
    recall: float
    f1: float
    n: int  # number of input items
    n_pairs: int  # number of (i, j), i<j pairs scored
    tp: int
    fp: int
    fn: int


def pairwise_f1(
    predictions: list[tuple[str, str]],
    oracle: list[tuple[str, str]],
) -> AlignmentResult:
    """Compute pairwise clustering F1.

    `predictions` and `oracle` are aligned lists of (input, label) tuples
    with identical input ordering. Labels are arbitrary strings — only the
    equivalence classes they induce matter.
    """
    if len(predictions) != len(oracle):
        raise ValueError(
            f"predictions ({len(predictions)}) and oracle "
            f"({len(oracle)}) must be the same length"
        )
    pred_labels = [p for _, p in predictions]
    oracle_labels = [o for _, o in oracle]
    n = len(pred_labels)
    if n < 2:
        return AlignmentResult(0.0, 0.0, 0.0, n, 0, 0, 0, 0)

    tp = fp = fn = 0
    for i in range(n):
        for j in range(i + 1, n):
            same_pred = pred_labels[i] == pred_labels[j]
            same_oracle = oracle_labels[i] == oracle_labels[j]
            if same_pred and same_oracle:
                tp += 1
            elif same_pred and not same_oracle:
                fp += 1
            elif not same_pred and same_oracle:
                fn += 1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    n_pairs = n * (n - 1) // 2
    return AlignmentResult(precision, recall, f1, n, n_pairs, tp, fp, fn)


def per_item_correctness(
    predictions: list[tuple[str, str]],
    oracle: list[tuple[str, str]],
) -> list[int]:
    """Per-item correctness used for paired bootstrap.

    Each input is scored 1 if every other input that shares its oracle
    canonical also shares its predicted canonical AND no input outside that
    oracle bucket shares its predicted canonical — i.e., the item is in a
    perfectly clean predicted cluster. Else 0.

    This is intentionally strict (per-item perfection) so the bootstrap
    operates on a paired binary signal we can also test with McNemar.
    """
    n = len(predictions)
    if len(oracle) != n:
        raise ValueError("length mismatch")
    pred = [p for _, p in predictions]
    orc = [o for _, o in oracle]
    out: list[int] = []
    for i in range(n):
        pred_cluster = {j for j in range(n) if pred[j] == pred[i]}
        oracle_cluster = {j for j in range(n) if orc[j] == orc[i]}
        out.append(1 if pred_cluster == oracle_cluster else 0)
    return out

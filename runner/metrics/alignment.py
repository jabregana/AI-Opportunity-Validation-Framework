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
    """Compute pairwise clustering F1 in O(N) using contingency-table
    identities.

    `predictions` and `oracle` are aligned lists of (input, label) tuples
    with identical input ordering. Labels are arbitrary strings; only the
    equivalence classes they induce matter.

    For each cell (pred_cluster p, oracle_cluster o) with count n_{p,o}:
        TP_contribution = C(n_{p,o}, 2)
    For each predicted cluster of size n_p: pairs within = C(n_p, 2)
    For each oracle cluster of size n_o: pairs within = C(n_o, 2)
    Then TP = sum cells C(n, 2);  FP = pred_within - TP;  FN = oracle_within - TP.
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

    pred_sizes: dict[str, int] = {}
    oracle_sizes: dict[str, int] = {}
    cell: dict[tuple[str, str], int] = {}
    for p, o in zip(pred_labels, oracle_labels):
        pred_sizes[p] = pred_sizes.get(p, 0) + 1
        oracle_sizes[o] = oracle_sizes.get(o, 0) + 1
        key = (p, o)
        cell[key] = cell.get(key, 0) + 1

    def c2(x: int) -> int:
        return x * (x - 1) // 2

    tp = sum(c2(c) for c in cell.values())
    pred_within = sum(c2(s) for s in pred_sizes.values())
    oracle_within = sum(c2(s) for s in oracle_sizes.values())
    fp = pred_within - tp
    fn = oracle_within - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    n_pairs = c2(n)
    return AlignmentResult(precision, recall, f1, n, n_pairs, tp, fp, fn)


def per_item_bcubed_f1(
    predictions: list[tuple[str, str]],
    oracle: list[tuple[str, str]],
) -> list[float]:
    """Per-item B-cubed F1 (Bagga and Baldwin, 1998).

    For each item i:
      pred_cluster_i  = items sharing i's predicted label
      oracle_cluster_i = items sharing i's oracle label
      intersection    = pred_cluster_i ∩ oracle_cluster_i
      bcubed_P_i = |intersection| / |pred_cluster_i|
      bcubed_R_i = |intersection| / |oracle_cluster_i|
      bcubed_F1_i = 2 P R / (P + R)

    Each item gets a continuous score in [0, 1]. Mean over items is the
    standard B-cubed aggregate. The per-item array is the paired-continuous
    signal the bootstrap operates on; sidesteps the bootstrap-duplicates
    pathology of pair-level metrics (pairwise F1 inflates b-raw's TP from
    resampled duplicates because identity-clustered duplicates are trivially
    same-pred-same-oracle).
    """
    n = len(predictions)
    if len(oracle) != n:
        raise ValueError("length mismatch")
    if n == 0:
        return []
    pred = [p for _, p in predictions]
    orc = [o for _, o in oracle]

    pred_idx: dict[str, list[int]] = {}
    oracle_idx: dict[str, list[int]] = {}
    for i, (p, o) in enumerate(zip(pred, orc)):
        pred_idx.setdefault(p, []).append(i)
        oracle_idx.setdefault(o, []).append(i)

    out: list[float] = []
    for i in range(n):
        pred_cluster = set(pred_idx[pred[i]])
        oracle_cluster = set(oracle_idx[orc[i]])
        intersection = len(pred_cluster & oracle_cluster)
        p_i = intersection / len(pred_cluster)
        r_i = intersection / len(oracle_cluster)
        f1_i = 2 * p_i * r_i / (p_i + r_i) if (p_i + r_i) > 0 else 0.0
        out.append(f1_i)
    return out


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

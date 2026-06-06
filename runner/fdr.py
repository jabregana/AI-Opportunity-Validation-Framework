"""Online FDR control via LORD++.

Maintains a sequential alpha-wealth ledger over an ordered stream of
hypothesis tests. At each step n the ledger computes a level α_n the n-th
hypothesis must be tested at to maintain FDR ≤ q over the entire
(potentially unbounded) sequence.

References:
    Ramdas, Yang, Wainwright, Jordan (2017).
        "Online control of the false discovery rate with decaying memory."
        NeurIPS 2017.
    Javanmard & Montanari (2018).
        "Online rules for control of false discovery rate and
         false discovery exceedance." Annals of Statistics.

Standard formulation:

    α_n = γ_n · W_0
        + (q − W_0) · γ_{n − τ_1} · 1{τ_1 < n}
        + q · Σ_{j ≥ 2} γ_{n − τ_j} · 1{τ_j < n}

with wealth update on every step:

    W_n = W_{n−1} − α_n + q · 1{p_n ≤ α_n}

γ_n must be a non-increasing sequence with Σ γ_n ≤ 1. The default here is
γ_n = c / (n · log₂²(n+1)) with c ≈ 0.4412 so the partial sums approach 1
(the canonical discount used in the LORD literature).

Test ordering is *prescriptive* per experiments.md §5.4: kill-switches and
highest-stakes non-inferiority tests at positions 1–5, primary capability
metrics 6–10, stable secondary metrics 11–13. Late tests receive
exponentially less alpha-wealth and should not host critical signals.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

# γ_n constant ≈ 0.4412 so Σ_{n=1}^∞ c / (n · log₂²(n+1)) ≈ 1.
_GAMMA_CONSTANT = 0.4412


def gamma(n: int, c: float = _GAMMA_CONSTANT) -> float:
    """Default discount sequence: γ_n = c / (n · log₂²(n+1))."""
    if n < 1:
        raise ValueError(f"gamma is defined for n >= 1, got {n}")
    return c / (n * (math.log2(n + 1) ** 2))


@dataclass
class LordPlusPlusLedger:
    """Stateful LORD++ ledger. Append-only — record() mutates in place."""

    target_q: float = 0.10
    initial_wealth_ratio: float = 0.5  # W_0 = ratio · q
    gamma_constant: float = _GAMMA_CONSTANT
    rejections: list[int] = field(default_factory=list)  # 1-indexed test_seq_ids
    wealth_history: list[float] = field(default_factory=list)  # [W_0, W_1, ...]

    def __post_init__(self) -> None:
        if not (0 < self.initial_wealth_ratio <= 1):
            raise ValueError("initial_wealth_ratio must be in (0, 1]")
        if not (0 < self.target_q < 1):
            raise ValueError("target_q must be in (0, 1)")
        if not self.wealth_history:
            self.wealth_history.append(self.initial_wealth_ratio * self.target_q)

    @property
    def W_0(self) -> float:
        return self.initial_wealth_ratio * self.target_q

    @property
    def current_wealth(self) -> float:
        return self.wealth_history[-1]

    def alpha_at(self, n: int) -> float:
        """Compute α_n — the test level for the n-th hypothesis (1-indexed).

        Pure function of (n, self.rejections); does not mutate state.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        alpha = gamma(n, self.gamma_constant) * self.W_0
        for j, tau_j in enumerate(self.rejections):
            if n <= tau_j:
                break
            reward = (self.target_q - self.W_0) if j == 0 else self.target_q
            alpha += gamma(n - tau_j, self.gamma_constant) * reward
        return min(max(alpha, 0.0), self.target_q)

    def record(self, n: int, p_value: float) -> tuple[float, bool]:
        """Record outcome of the n-th test; returns (α_n, was_rejected)."""
        if n != len(self.wealth_history):
            raise ValueError(
                f"Tests must arrive in order; expected n={len(self.wealth_history)}, got {n}"
            )
        alpha_n = self.alpha_at(n)
        is_rejected = p_value <= alpha_n
        reward = self.target_q if is_rejected else 0.0
        self.wealth_history.append(self.current_wealth - alpha_n + reward)
        if is_rejected:
            self.rejections.append(n)
        return alpha_n, is_rejected


def run_ledger(
    test_executions: list[dict],
    target_q: float = 0.10,
    initial_wealth_ratio: float = 0.5,
) -> tuple[list[dict], LordPlusPlusLedger]:
    """Replay LORD++ over a prescriptively-ordered list of test dicts.

    Each test dict is expected to contain at least `test_seq_id` and
    `p_value`. The function mutates each dict in place adding
    `alpha_allocated` and `outcome_rejected`, and returns the final ledger
    so callers can inspect wealth + rejection history for the artifact's
    `sequential_fdr_ledger` block.
    """
    ledger = LordPlusPlusLedger(
        target_q=target_q, initial_wealth_ratio=initial_wealth_ratio
    )
    # Sort defensively — the prescriptive ordering must be honoured.
    ordered = sorted(test_executions, key=lambda t: t["test_seq_id"])
    for test in ordered:
        n = test["test_seq_id"]
        alpha_n, rejected = ledger.record(n, test["p_value"])
        test["alpha_allocated"] = alpha_n
        test["outcome_rejected"] = rejected
    return ordered, ledger

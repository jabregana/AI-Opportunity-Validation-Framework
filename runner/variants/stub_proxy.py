from __future__ import annotations
import hashlib
from .base import Variant


class StubRandomBucketProxy(Variant):
    """Sanity-check baseline — deterministic hash-to-bucket assignment.

    This is not a real schema-alignment proxy; it ignores relation semantics
    entirely and maps each surface form to one of n_buckets via SHA-256.
    Used to validate the harness end-to-end and to estimate the paired-diff
    standard deviation needed for the §5.3 power calculation in the
    experiments doc.

    Expected pairwise F1 ≈ 1 / n_buckets on a workload with that many
    canonical classes.
    """

    name = "stub-random-bucket-v0.0.1"

    def __init__(self, n_buckets: int = 34):
        self.n_buckets = n_buckets

    def align(self, input_relation: str) -> str:
        h = int(hashlib.sha256(input_relation.encode()).hexdigest(), 16)
        return f"BUCKET_{h % self.n_buckets:02d}"

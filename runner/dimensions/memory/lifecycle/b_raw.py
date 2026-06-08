"""b-raw-no-gc: the no-GC identity baseline.

Never collects anything. Used as the reference point for all UC gates:
  UC-GC-1 (store-size reduction): measured relative to b-raw
  UC-GC-2 (retrieval F1 preservation): non-inferiority margin set
    against b-raw's retrieval F1
  UC-GC-3 (false-collection rate): b-raw's rate is by definition 0
  UC-GC-4 (write-path latency): b-raw's latency is the floor
"""
from __future__ import annotations

from .base import GCVariant, GraphState


class BRawNoGC(GCVariant):
    name = "b-raw-no-gc"

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        return False

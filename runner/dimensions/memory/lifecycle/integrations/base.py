"""GCIntegrationShim ABC: the contract a downstream memory framework
needs to satisfy so a GCVariant can sweep its store.

The variant works against the dimension's normalized GraphState. The
shim translates between that normalized form and the downstream's
native API (Graphiti's Neo4j Cypher, Mem0's vector store, Cognee's
module-level interface, etc).

Contract:

  record_write(node_id, kind, metadata, t)
    Downstream wrote a node. Shim updates its internal state.

  record_edge(src, dst, t)
    Downstream created an edge. Shim updates in/out degree.

  record_remove_edge(src, dst, t)
    Downstream removed an edge (supersession, deduplication). Shim
    updates in/out degree.

  record_query(node_id, t)
    Downstream queried a node. Shim updates last_access / query_count
    for utility-based variants.

  pin(node_id)
    Mark a node as never-collectable.

  get_state() -> GraphState
    Return the normalized GraphState the variant should sweep against.
    Implementations may keep this incrementally maintained or compute
    it on demand.

  apply_sweep(node_ids_to_remove) -> int
    Actually delete the chosen nodes from the downstream store. Return
    the number of nodes successfully removed (may be less than the
    input if some nodes already gone or pinning conflicts).

  stats() -> IntegrationStats
    Diagnostic counters: how many writes, edges, sweeps, etc. Useful
    for finding docs and operational monitoring.

Concrete shims for Graphiti / Mem0 / Cognee live in sibling modules
that are not yet written (each requires the respective dependency
installed and a small adapter). The contract is designed to be
generic enough that any of those three can implement it.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..base import GraphState


@dataclass
class IntegrationStats:
    """Diagnostic counters for the shim's operational behavior."""

    n_writes: int = 0
    n_edges_added: int = 0
    n_edges_removed: int = 0
    n_queries: int = 0
    n_sweeps_invoked: int = 0
    n_nodes_actually_removed: int = 0
    n_pins: int = 0
    last_sweep_size_before: int = 0
    last_sweep_size_after: int = 0


class GCIntegrationShim(ABC):
    """A shim that connects a GCVariant to a downstream memory framework."""

    name: str = "unnamed-shim"
    contract_version: int = 1

    @abstractmethod
    def record_write(
        self,
        node_id: str,
        kind: str,
        metadata: dict | None,
        t: float,
    ) -> None:
        """Downstream wrote a node."""
        raise NotImplementedError

    @abstractmethod
    def record_edge(self, src: str, dst: str, t: float) -> None:
        """Downstream created an edge from src to dst."""
        raise NotImplementedError

    @abstractmethod
    def record_remove_edge(self, src: str, dst: str, t: float) -> None:
        """Downstream removed the edge from src to dst."""
        raise NotImplementedError

    @abstractmethod
    def record_query(self, node_id: str, t: float) -> None:
        """Downstream queried a node (updates last_access / query_count)."""
        raise NotImplementedError

    @abstractmethod
    def pin(self, node_id: str) -> None:
        """Mark a node as never-collectable."""
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> GraphState:
        """Return the normalized GraphState for variant evaluation."""
        raise NotImplementedError

    @abstractmethod
    def apply_sweep(self, node_ids_to_remove: list[str]) -> int:
        """Delete the chosen nodes from the downstream store.

        Returns the number actually removed.
        """
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> IntegrationStats:
        """Return current diagnostic counters."""
        raise NotImplementedError

"""Synthetic graph-churn workload for testing graph GC variants.

Produces a stream of graph operations (add_node, add_edge, remove_edge,
pin, query) that mimics agent-memory shape:

  - Entity nodes (long-lived): companies, people, products. Few.
  - Fact nodes (short-lived): timestamped statements that link entities.
    Many. Get superseded by newer facts on the same topic.
  - Edges go from fact -> entity (a fact mentions entities).
  - Pinned nodes: a small fraction tagged as "do not collect, ever."
  - Queries: occasional accesses against random entity nodes that
    update last_access timestamps (so utility-based GC has signal).

Churn pattern: each fact has a finite lifetime. After
fact_lifetime_seconds, the fact's edges to its entities are removed,
mimicking the fact being superseded. If an entity ends up with zero
incoming edges as a result, it becomes a candidate for collection by
reference-counted GC.

Output: ChurnWorkload with:
  - events: chronologically-sorted GraphEvents
  - pinned_nodes: set of node ids that should NEVER be collected
  - expected_survivors: set of node ids that should be present at end
    under a correct GC implementation (entities still referenced +
    pinned). Used by the runner for false-collection-rate computation.

The shape is deliberately simple. Stage 2's job is to surface whether
the mechanism works at all on controlled data. Stage 3 swaps in real
Mem0 ingestion traces.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


@dataclass
class GraphEvent:
    """A single operation in the workload stream."""

    op: str  # "add_node" | "add_edge" | "remove_edge" | "pin" | "query"
    timestamp: float  # seconds since workload start
    node_id: str | None = None
    node_kind: str | None = None  # "entity" | "fact" (only for add_node)
    edge_src: str | None = None
    edge_dst: str | None = None


@dataclass
class ChurnWorkload:
    """Full workload: event stream + ground-truth survivors."""

    events: list[GraphEvent]
    pinned_nodes: set[str] = field(default_factory=set)
    expected_survivors: set[str] = field(default_factory=set)
    n_entities: int = 0
    n_facts: int = 0


def generate_churn_workload(
    n_entities: int = 20,
    n_facts: int = 200,
    fact_lifetime_seconds: float = 7 * 86400,  # facts superseded after 7 days
    pin_fraction: float = 0.05,
    query_fraction: float = 0.10,  # queries per fact write
    edges_per_fact: tuple[int, int] = (1, 3),  # uniform[1, 3]
    seed: int = 0,
) -> ChurnWorkload:
    """Generate a deterministic churn workload.

    Timing model:
      - All n_entities are added at t=0 to t=10 seconds (effectively up
        front).
      - n_facts are added uniformly across the simulated period
        (~30 days by default).
      - Each fact's edges are added at the same timestamp as the fact.
      - At timestamp = fact_added + fact_lifetime_seconds, the fact's
        edges are removed (mimicking supersession). The fact node itself
        stays in the graph (it represents historical truth) but its
        outgoing edges to entities are gone.
      - A pin_fraction of entities is pinned (cannot be collected).
      - query_fraction * n_facts random queries hit random entities,
        updating their last_access. Spread across the period.

    Returns a workload whose `events` are chronologically sorted.
    """
    rng = random.Random(seed)
    total_period = 30 * 86400.0  # 30 simulated days

    # Allocate ids
    entity_ids = [f"e{i:04d}" for i in range(n_entities)]
    fact_ids = [f"f{i:05d}" for i in range(n_facts)]

    # Pin a fraction of entities
    n_pinned = max(0, int(round(n_entities * pin_fraction)))
    pinned_nodes = set(rng.sample(entity_ids, n_pinned))

    events: list[GraphEvent] = []

    # Phase 1: add all entities at t=0..10s
    for i, eid in enumerate(entity_ids):
        events.append(GraphEvent(
            op="add_node", timestamp=float(i) * 0.5,
            node_id=eid, node_kind="entity",
        ))

    # Phase 2: pin events right after entity adds
    pin_t = 11.0
    for pid in sorted(pinned_nodes):
        events.append(GraphEvent(
            op="pin", timestamp=pin_t, node_id=pid,
        ))
        pin_t += 0.1

    # Phase 3: facts spread across the period, each with edges and a
    # corresponding remove_edge event at fact_lifetime later.
    entity_references: dict[str, int] = {eid: 0 for eid in entity_ids}

    fact_start = 20.0
    fact_end = total_period - fact_lifetime_seconds - 100.0
    if fact_end <= fact_start:
        fact_end = total_period - 100.0

    for fact_id in fact_ids:
        t = rng.uniform(fact_start, fact_end)
        events.append(GraphEvent(
            op="add_node", timestamp=t,
            node_id=fact_id, node_kind="fact",
        ))
        n_edges = rng.randint(edges_per_fact[0], edges_per_fact[1])
        # Each fact links to n_edges distinct entities
        targets = rng.sample(entity_ids, min(n_edges, len(entity_ids)))
        for entity_target in targets:
            edge_t = t + 0.001  # immediately after node add
            events.append(GraphEvent(
                op="add_edge", timestamp=edge_t,
                edge_src=fact_id, edge_dst=entity_target,
            ))
            entity_references[entity_target] += 1
            # Schedule the edge removal at fact_lifetime later
            remove_t = t + fact_lifetime_seconds
            events.append(GraphEvent(
                op="remove_edge", timestamp=remove_t,
                edge_src=fact_id, edge_dst=entity_target,
            ))
            entity_references[entity_target] -= 1

    # Phase 4: queries against random entities
    n_queries = int(n_facts * query_fraction)
    for _ in range(n_queries):
        t = rng.uniform(fact_start, total_period)
        eid = rng.choice(entity_ids)
        events.append(GraphEvent(
            op="query", timestamp=t, node_id=eid,
        ))

    # Sort by timestamp (stable; ties broken by insertion order)
    events.sort(key=lambda e: e.timestamp)

    # Expected survivors: every entity node (conservative-survival
    # philosophy). Entities are the long-lived, semantically meaningful
    # nodes; the workload narrative is "entities persist, facts churn."
    # Pinned nodes are a strict subset (and so already included). Facts
    # are explicitly NOT survivors: they are the write-stream record
    # whose edges age out, and a correct GC should be free to collect
    # them once all their outgoing edges have been removed.
    # The earlier strict-survival philosophy (survivors == pinned only)
    # was found to contradict UC-GC-2's baseline-comparison logic; see
    # docs/finding-gc-stage2-baseline.md for the analysis.
    expected_survivors = set(entity_ids)

    return ChurnWorkload(
        events=events,
        pinned_nodes=pinned_nodes,
        expected_survivors=expected_survivors,
        n_entities=n_entities,
        n_facts=n_facts,
    )

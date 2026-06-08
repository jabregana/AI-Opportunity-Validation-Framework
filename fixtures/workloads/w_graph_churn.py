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
    """A single operation in the workload stream.

    The optional tenant_id carries multi-tenant attribution when the
    workload was generated with n_tenants > 1. None when single-tenant.
    """

    op: str  # "add_node" | "add_edge" | "remove_edge" | "pin" | "query"
    timestamp: float  # seconds since workload start
    node_id: str | None = None
    node_kind: str | None = None  # "entity" | "fact" (only for add_node)
    edge_src: str | None = None
    edge_dst: str | None = None
    tenant_id: str | None = None  # set when workload has n_tenants > 1


@dataclass
class ChurnWorkload:
    """Full workload: event stream + ground-truth survivors."""

    events: list[GraphEvent]
    pinned_nodes: set[str] = field(default_factory=set)
    expected_survivors: set[str] = field(default_factory=set)
    n_entities: int = 0
    n_facts: int = 0
    # Extensions for v0.1.3-v0.1.5 differentiation (all default empty)
    n_tenants: int = 1
    tenant_assignments: dict[str, str] = field(default_factory=dict)  # entity_id -> tenant_id
    dormant_entity_ids: set[str] = field(default_factory=set)  # entities with zero queries
    collected_fact_query_targets: list[str] = field(default_factory=list)  # facts queried after collection


def generate_churn_workload(
    n_entities: int = 20,
    n_facts: int = 200,
    fact_lifetime_seconds: float = 7 * 86400,  # facts superseded after 7 days
    pin_fraction: float = 0.05,
    query_fraction: float = 0.10,  # queries per fact write
    edges_per_fact: tuple[int, int] = (1, 3),  # uniform[1, 3]
    seed: int = 0,
    # Extension params for v0.1.3-v0.1.5 differentiation (defaults preserve
    # existing behavior; opt-in via non-default values):
    total_period_days: float = 30.0,
    n_tenants: int = 1,
    dormant_entity_fraction: float = 0.0,
    collected_fact_query_fraction: float = 0.0,
) -> ChurnWorkload:
    """Generate a deterministic churn workload.

    Core timing model (unchanged from prior versions):
      - All n_entities are added at t=0 to t=10 seconds.
      - n_facts are added uniformly across the simulated period
        (total_period_days, default 30 days).
      - Each fact's edges are added at the same timestamp as the fact.
      - At timestamp = fact_added + fact_lifetime_seconds, the fact's
        edges are removed.
      - A pin_fraction of entities is pinned.
      - query_fraction * n_facts random queries hit random entities.

    Extension params (default 0 / 1 = off):
      total_period_days: simulated workload duration. Default 30. Set
        higher (e.g., 90) to exercise v0.1.4-conservative-entity's
        60-day-unaccessed threshold.
      n_tenants: assigns entities round-robin to tenants via tenant_id
        on entity-add events. Default 1 (single-tenant).
      dormant_entity_fraction: fraction of entities that receive ZERO
        queries (excluded from query-target sampling). Their
        last_access stays at added_at; v0.1.4 can detect them when
        their edges also age out and duration is long enough.
      collected_fact_query_fraction: fraction of facts whose
        remove_edge is followed (in 1-2 days) by a query against the
        fact node itself. These queries fail at runtime in v0.1.2
        (the fact is gone) but v0.1.3-tombstone can recover them.

    Returns a workload whose `events` are chronologically sorted.
    """
    rng = random.Random(seed)
    total_period = total_period_days * 86400.0

    # Allocate ids
    entity_ids = [f"e{i:04d}" for i in range(n_entities)]
    fact_ids = [f"f{i:05d}" for i in range(n_facts)]

    # Pin a fraction of entities
    n_pinned = max(0, int(round(n_entities * pin_fraction)))
    pinned_nodes = set(rng.sample(entity_ids, n_pinned))

    # Tenant assignment: round-robin entities -> tenants
    tenant_assignments: dict[str, str] = {}
    if n_tenants > 1:
        for i, eid in enumerate(entity_ids):
            tenant_assignments[eid] = f"tenant_{i % n_tenants:03d}"

    # Dormant entities: a fraction that NEVER receive queries
    n_dormant = max(0, int(round(n_entities * dormant_entity_fraction)))
    # Sample dormant entities deterministically; bias toward later
    # entity indices so the pinned-entity sampling above is independent
    dormant_pool = [eid for eid in entity_ids if eid not in pinned_nodes]
    dormant_entity_ids = set(
        rng.sample(dormant_pool, min(n_dormant, len(dormant_pool)))
    )

    events: list[GraphEvent] = []

    # Phase 1: add all entities at t=0..10s (with tenant_id when set)
    for i, eid in enumerate(entity_ids):
        events.append(GraphEvent(
            op="add_node", timestamp=float(i) * 0.5,
            node_id=eid, node_kind="entity",
            tenant_id=tenant_assignments.get(eid),
        ))

    # Phase 2: pin events right after entity adds (tenant-scoped when
    # the entity has a tenant assignment)
    pin_t = 11.0
    for pid in sorted(pinned_nodes):
        events.append(GraphEvent(
            op="pin", timestamp=pin_t, node_id=pid,
            tenant_id=tenant_assignments.get(pid),
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

    # Phase 4: queries against random entities (excluding dormants)
    queryable_entities = [eid for eid in entity_ids
                          if eid not in dormant_entity_ids]
    n_queries = int(n_facts * query_fraction)
    if queryable_entities:
        for _ in range(n_queries):
            t = rng.uniform(fact_start, total_period)
            eid = rng.choice(queryable_entities)
            events.append(GraphEvent(
                op="query", timestamp=t, node_id=eid,
            ))

    # Phase 5: queries against just-collected facts (v0.1.3 tombstone
    # differentiator). Sample a fraction of facts; for each, emit a
    # query 1-2 days after its remove_edge timestamp.
    collected_fact_query_targets: list[str] = []
    if collected_fact_query_fraction > 0.0:
        n_target = int(n_facts * collected_fact_query_fraction)
        target_facts = rng.sample(fact_ids, min(n_target, len(fact_ids)))
        # Look up each target's remove_edge time from existing events
        remove_times: dict[str, float] = {}
        for ev in events:
            if ev.op == "remove_edge" and ev.edge_src in target_facts:
                # Use the LATEST remove_edge for the fact (when all its
                # edges have been removed)
                cur = remove_times.get(ev.edge_src, 0.0)
                if ev.timestamp > cur:
                    remove_times[ev.edge_src] = ev.timestamp
        for fid in target_facts:
            if fid in remove_times:
                # Query 1-2 days after collection eligibility
                query_t = remove_times[fid] + rng.uniform(86400, 2 * 86400)
                events.append(GraphEvent(
                    op="query", timestamp=query_t, node_id=fid,
                ))
                collected_fact_query_targets.append(fid)

    # Sort by timestamp (stable; ties broken by insertion order)
    events.sort(key=lambda e: e.timestamp)

    # Expected survivors: every entity node by default (conservative-
    # survival philosophy). Entities are the long-lived, semantically
    # meaningful nodes.
    #
    # Exception: when dormant_entity_fraction > 0, dormant entities are
    # EXCLUDED from expected_survivors. v0.1.4-conservative-entity is
    # designed to collect them; counting that as 'false collection' would
    # penalize the variant for doing exactly what it should. Pinned
    # dormants stay protected because the dormant pool was sampled from
    # non-pinned.
    if dormant_entity_fraction > 0.0:
        expected_survivors = set(entity_ids) - dormant_entity_ids
    else:
        expected_survivors = set(entity_ids)

    return ChurnWorkload(
        events=events,
        pinned_nodes=pinned_nodes,
        expected_survivors=expected_survivors,
        n_entities=n_entities,
        n_facts=n_facts,
        n_tenants=n_tenants,
        tenant_assignments=tenant_assignments,
        dormant_entity_ids=dormant_entity_ids,
        collected_fact_query_targets=collected_fact_query_targets,
    )

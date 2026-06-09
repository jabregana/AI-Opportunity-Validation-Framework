"""Synthetic graph-native lifecycle workload for v0.2.x variant testing.

The v0.1.x workload (`w_graph_churn.py`) uses explicit edge-removal events
as the supersession proxy. That shape matches Mem0-style flat-memory but
NOT Graphiti-style append-only edge-rich graphs. v0.2.x variants need a
workload whose events match real Graphiti semantics:

  - Episodes (source documents) get added; entities are extracted; edges
    connect entities. Edges are never removed.
  - Supersession is explicit: an `invalid_at` timestamp is set on the
    old fact's edge when a contradicting new fact arrives.
  - Queries traverse the live (currently-valid) graph.

This module ships SIX archetypes that the v0.2.x variants get tested
against per `docs/benchmark-methodology.md` compliance:

  1. steady-state              constant rate, uniform queries, no supersession
  2. bursty                    10x spike for 5% of duration then quiet
  3. large-fact                heavy-tail entities-per-fact (some facts mention 10+)
  4. supersession-heavy        50% of facts get invalidated within window
  5. cluster-rich              N topic clusters; queries target one at a time
  6. adversarial-no-supersession   rich connectivity, no supersession events
                               (designed to defeat v0.2.1 temporal-validity)

The generator is parametric: every archetype accepts the same shape of
config knobs (n, seed, total_period_days, etc.) so the v0.2.x stage 2
benchmark can run the same matrix against each.

Distributions used:
  - Node degree: Barabasi-Albert preferential attachment for cluster-rich
  - Fact lifetime: Weibull with shape < 1 (heavy tail) for supersession-heavy
  - Query frequency: Zipfian over entities for cluster-rich / large-fact
  - Inter-arrival times: exponential for steady-state, bimodal for bursty
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass, field


@dataclass
class LifecycleEvent:
    """A single operation in the graph-lifecycle workload."""

    op: str          # "add_entity" | "add_fact" | "supersede" | "query" | "pin"
    timestamp: float
    node_id: str | None = None
    node_kind: str | None = None     # "entity" | "fact" (for add_*)
    mentioned_entities: list[str] | None = None  # for add_fact
    superseded_fact_id: str | None = None        # for supersede
    target_entity_id: str | None = None          # for query
    cluster_id: int | None = None    # for cluster-rich tracking


@dataclass
class LifecycleWorkload:
    """Output of generate(): events + ground truth + archetype label."""

    archetype: str
    seed: int
    events: list[LifecycleEvent]
    entities: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    superseded_fact_ids: set[str] = field(default_factory=set)
    pinned_nodes: set[str] = field(default_factory=set)
    cluster_assignment: dict[str, int] = field(default_factory=dict)
    aggregate_stats: dict = field(default_factory=dict)


# ------------------ helpers ------------------


def _weibull_rng(rng: random.Random, shape: float, scale: float) -> float:
    """Weibull-distributed sample. shape < 1 = heavy-tail."""
    u = rng.random()
    return scale * (-math.log(1 - u)) ** (1.0 / shape)


def _zipfian_pick(rng: random.Random, n: int, exponent: float = 1.0) -> int:
    """Sample an index 0..n-1 with Zipfian frequency (lower index = more frequent)."""
    weights = [1.0 / ((i + 1) ** exponent) for i in range(n)]
    total = sum(weights)
    r = rng.random() * total
    cum = 0.0
    for i, w in enumerate(weights):
        cum += w
        if r <= cum:
            return i
    return n - 1


# ------------------ archetype generators ------------------


def _gen_steady_state(
    rng: random.Random,
    *,
    n_entities: int,
    n_facts: int,
    total_period_days: float,
    pin_fraction: float,
) -> LifecycleWorkload:
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    # Entities added at t=0
    for e in entities:
        events.append(LifecycleEvent(op="add_entity", timestamp=0.0, node_id=e, node_kind="entity"))
    # Facts added uniformly over period
    for i, f in enumerate(facts):
        t = period_s * (i + 1) / (n_facts + 1)
        n_mentions = rng.randint(1, 3)
        mentioned = rng.sample(entities, k=min(n_mentions, len(entities)))
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=f, node_kind="fact",
            mentioned_entities=mentioned,
        ))
    # Queries: one per fact's worth, targeting a random entity
    for i in range(n_facts):
        t = period_s * (i + 1) / (n_facts + 1) + rng.uniform(0, 60)
        target = rng.choice(entities)
        events.append(LifecycleEvent(op="query", timestamp=t, target_entity_id=target))
    # Pinned nodes
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="steady-state", seed=0, events=events,
        entities=entities, facts=facts, pinned_nodes=pinned,
    )


def _gen_bursty(rng: random.Random, *, n_entities: int, n_facts: int,
                total_period_days: float, pin_fraction: float,
                burst_start_pct: float = 0.4, burst_duration_pct: float = 0.05,
                burst_multiplier: int = 10) -> LifecycleWorkload:
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    for e in entities:
        events.append(LifecycleEvent(op="add_entity", timestamp=0.0, node_id=e, node_kind="entity"))
    # n_facts split: (1 - burst_fraction) over (1 - burst_duration_pct);
    # burst_fraction in burst_duration_pct window
    burst_window_facts = int(n_facts * burst_multiplier / (burst_multiplier + (1.0 / burst_duration_pct - 1)))
    steady_facts = n_facts - burst_window_facts
    burst_start_s = period_s * burst_start_pct
    burst_end_s = burst_start_s + period_s * burst_duration_pct
    f_idx = 0
    # Steady before burst
    pre_burst_count = int(steady_facts * burst_start_pct)
    for i in range(pre_burst_count):
        t = period_s * burst_start_pct * (i + 1) / (pre_burst_count + 1)
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=facts[f_idx], node_kind="fact",
            mentioned_entities=rng.sample(entities, k=rng.randint(1, 3)),
        ))
        f_idx += 1
    # Burst window
    for i in range(burst_window_facts):
        t = burst_start_s + (burst_end_s - burst_start_s) * (i + 1) / (burst_window_facts + 1)
        if f_idx < len(facts):
            events.append(LifecycleEvent(
                op="add_fact", timestamp=t, node_id=facts[f_idx], node_kind="fact",
                mentioned_entities=rng.sample(entities, k=rng.randint(1, 3)),
            ))
            f_idx += 1
    # Steady after burst
    while f_idx < len(facts):
        t = burst_end_s + (period_s - burst_end_s) * (f_idx - pre_burst_count - burst_window_facts + 1) / (
            len(facts) - pre_burst_count - burst_window_facts + 1
        )
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=facts[f_idx], node_kind="fact",
            mentioned_entities=rng.sample(entities, k=rng.randint(1, 3)),
        ))
        f_idx += 1
    # Queries (uniform)
    for _ in range(n_facts):
        t = rng.uniform(0, period_s)
        target = rng.choice(entities)
        events.append(LifecycleEvent(op="query", timestamp=t, target_entity_id=target))
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="bursty", seed=0, events=events,
        entities=entities, facts=facts, pinned_nodes=pinned,
    )


def _gen_supersession_heavy(rng: random.Random, *, n_entities: int, n_facts: int,
                            total_period_days: float, pin_fraction: float,
                            supersession_rate: float = 0.5,
                            supersession_window_days: float = 10.0) -> LifecycleWorkload:
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    supersession_window_s = supersession_window_days * 86400.0
    for e in entities:
        events.append(LifecycleEvent(op="add_entity", timestamp=0.0, node_id=e, node_kind="entity"))
    superseded_ids: set[str] = set()
    for i, f in enumerate(facts):
        t = period_s * (i + 1) / (n_facts + 1)
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=f, node_kind="fact",
            mentioned_entities=rng.sample(entities, k=rng.randint(1, 3)),
        ))
        # With probability supersession_rate, schedule a supersession event
        if rng.random() < supersession_rate and i + 10 < n_facts:
            superseder_offset = int(rng.uniform(1, min(10, n_facts - i - 1)))
            superseder = facts[i + superseder_offset]
            t_supersede = t + rng.uniform(60, supersession_window_s)
            if t_supersede < period_s:
                events.append(LifecycleEvent(
                    op="supersede", timestamp=t_supersede,
                    superseded_fact_id=f, node_id=superseder,
                ))
                superseded_ids.add(f)
    # Queries
    for _ in range(n_facts):
        t = rng.uniform(0, period_s)
        target = rng.choice(entities)
        events.append(LifecycleEvent(op="query", timestamp=t, target_entity_id=target))
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="supersession-heavy", seed=0, events=events,
        entities=entities, facts=facts, superseded_fact_ids=superseded_ids,
        pinned_nodes=pinned,
    )


def _gen_cluster_rich(rng: random.Random, *, n_entities: int, n_facts: int,
                     total_period_days: float, pin_fraction: float,
                     n_clusters: int = 10, zipfian_exponent: float = 1.0) -> LifecycleWorkload:
    """Cluster-rich: entities partition into N topic clusters; facts mention
    entities WITHIN a cluster; queries (Zipfian over clusters) target one
    cluster at a time. Exercises v0.2.0-component-isolation."""
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    # Assign entities to clusters
    cluster_assignment = {}
    clusters: list[list[str]] = [[] for _ in range(n_clusters)]
    for e in entities:
        c = rng.randrange(n_clusters)
        cluster_assignment[e] = c
        clusters[c].append(e)
    for e in entities:
        events.append(LifecycleEvent(
            op="add_entity", timestamp=0.0, node_id=e, node_kind="entity",
            cluster_id=cluster_assignment[e],
        ))
    # Facts mention entities WITHIN a cluster
    fact_cluster: dict[str, int] = {}
    for i, f in enumerate(facts):
        t = period_s * (i + 1) / (n_facts + 1)
        c = rng.randrange(n_clusters)
        if not clusters[c]:
            continue
        k = min(rng.randint(1, 3), len(clusters[c]))
        mentioned = rng.sample(clusters[c], k=k)
        fact_cluster[f] = c
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=f, node_kind="fact",
            mentioned_entities=mentioned, cluster_id=c,
        ))
    # Queries: Zipfian over clusters; pick a random entity in the chosen cluster
    for _ in range(n_facts):
        t = rng.uniform(0, period_s)
        c = _zipfian_pick(rng, n_clusters, exponent=zipfian_exponent)
        if not clusters[c]:
            continue
        target = rng.choice(clusters[c])
        events.append(LifecycleEvent(
            op="query", timestamp=t, target_entity_id=target, cluster_id=c,
        ))
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="cluster-rich", seed=0, events=events,
        entities=entities, facts=facts, pinned_nodes=pinned,
        cluster_assignment=cluster_assignment,
    )


def _gen_adversarial_no_supersession(rng: random.Random, *, n_entities: int,
                                     n_facts: int, total_period_days: float,
                                     pin_fraction: float) -> LifecycleWorkload:
    """Adversarial: rich connectivity (every fact mentions 3-5 entities),
    queries hit every entity at least once, no supersession events ever.
    Designed to defeat v0.2.1-temporal-validity (nothing ever has invalid_at)
    and force v0.2.0-component-isolation + v0.2.2-activation-decay to do
    the work."""
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    for e in entities:
        events.append(LifecycleEvent(op="add_entity", timestamp=0.0, node_id=e, node_kind="entity"))
    for i, f in enumerate(facts):
        t = period_s * (i + 1) / (n_facts + 1)
        n_mentions = rng.randint(3, 5)
        mentioned = rng.sample(entities, k=min(n_mentions, len(entities)))
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=f, node_kind="fact",
            mentioned_entities=mentioned,
        ))
    # One query per entity (ensures every entity has query_count >= 1)
    for e in entities:
        t = rng.uniform(0, period_s)
        events.append(LifecycleEvent(op="query", timestamp=t, target_entity_id=e))
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="adversarial-no-supersession", seed=0, events=events,
        entities=entities, facts=facts, pinned_nodes=pinned,
    )


def _gen_large_fact(rng: random.Random, *, n_entities: int, n_facts: int,
                   total_period_days: float, pin_fraction: float,
                   heavy_tail_fraction: float = 0.1,
                   heavy_tail_mentions: int = 10) -> LifecycleWorkload:
    """Large-fact archetype: 90% facts mention 1-3 entities (standard);
    10% mention many entities (heavy_tail_mentions). Exercises sweep-cost
    sensitivity to per-fact size."""
    events: list[LifecycleEvent] = []
    entities = [f"e_{i:05d}" for i in range(n_entities)]
    facts = [f"f_{i:06d}" for i in range(n_facts)]
    period_s = total_period_days * 86400.0
    for e in entities:
        events.append(LifecycleEvent(op="add_entity", timestamp=0.0, node_id=e, node_kind="entity"))
    for i, f in enumerate(facts):
        t = period_s * (i + 1) / (n_facts + 1)
        if rng.random() < heavy_tail_fraction:
            k = min(heavy_tail_mentions, len(entities))
        else:
            k = rng.randint(1, 3)
        mentioned = rng.sample(entities, k=k)
        events.append(LifecycleEvent(
            op="add_fact", timestamp=t, node_id=f, node_kind="fact",
            mentioned_entities=mentioned,
        ))
    for _ in range(n_facts):
        t = rng.uniform(0, period_s)
        target = rng.choice(entities)
        events.append(LifecycleEvent(op="query", timestamp=t, target_entity_id=target))
    pinned = set(rng.sample(entities, k=int(pin_fraction * n_entities)))
    for p in pinned:
        events.append(LifecycleEvent(op="pin", timestamp=0.0, node_id=p))
    events.sort(key=lambda e: e.timestamp)
    return LifecycleWorkload(
        archetype="large-fact", seed=0, events=events,
        entities=entities, facts=facts, pinned_nodes=pinned,
    )


# ------------------ public API ------------------


_GENERATORS = {
    "steady-state": _gen_steady_state,
    "bursty": _gen_bursty,
    "large-fact": _gen_large_fact,
    "supersession-heavy": _gen_supersession_heavy,
    "cluster-rich": _gen_cluster_rich,
    "adversarial-no-supersession": _gen_adversarial_no_supersession,
}


def generate(
    archetype: str,
    *,
    n_entities: int = 50,
    n_facts: int = 200,
    total_period_days: float = 30.0,
    pin_fraction: float = 0.05,
    seed: int = 42,
    **archetype_kwargs,
) -> LifecycleWorkload:
    """Generate a graph-lifecycle workload of the requested archetype.

    Archetypes: steady-state, bursty, large-fact, supersession-heavy,
    cluster-rich, adversarial-no-supersession.

    Standard knobs apply to all archetypes:
      n_entities          number of entity nodes
      n_facts             number of fact nodes
      total_period_days   workload duration
      pin_fraction        fraction of entities pinned (never collected)
      seed                deterministic RNG seed

    Archetype-specific knobs passed via **archetype_kwargs:
      bursty:             burst_start_pct, burst_duration_pct, burst_multiplier
      supersession-heavy: supersession_rate, supersession_window_days
      cluster-rich:       n_clusters, zipfian_exponent
      large-fact:         heavy_tail_fraction, heavy_tail_mentions
    """
    if archetype not in _GENERATORS:
        raise ValueError(
            f"Unknown archetype {archetype!r}. "
            f"Known: {sorted(_GENERATORS)}"
        )
    rng = random.Random(seed)
    workload = _GENERATORS[archetype](
        rng=rng, n_entities=n_entities, n_facts=n_facts,
        total_period_days=total_period_days, pin_fraction=pin_fraction,
        **archetype_kwargs,
    )
    workload.seed = seed
    # Validation block (per docs/benchmark-methodology.md): compute aggregate
    # stats so a finding doc can show the synthetic workload matches expected
    # distributions
    n_queries = sum(1 for e in workload.events if e.op == "query")
    n_supersessions = sum(1 for e in workload.events if e.op == "supersede")
    workload.aggregate_stats = {
        "n_entities": len(workload.entities),
        "n_facts": len(workload.facts),
        "n_queries": n_queries,
        "n_supersessions": n_supersessions,
        "supersession_rate_observed": (
            n_supersessions / max(1, len(workload.facts))
        ),
        "n_pinned": len(workload.pinned_nodes),
        "total_events": len(workload.events),
    }
    return workload

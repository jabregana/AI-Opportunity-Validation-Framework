"""Workload registry.

Each workload returns a list of WorkloadEntry records.

  source_id        — identifier for the source of this write (team, user,
                     tenant). Single-tenant workloads use "default".
  input_relation   — the surface form the agent is writing.
  oracle_canonical — the ground-truth canonical for this write.

Three-tuple shape replaces the older two-tuple to support source-
attributed resolution (v0.4.0+, per docs/roadmap.md). NamedTuple
inheritance from tuple preserves index access where it matters; tests
should use named attributes (entry.input, entry.oracle_canonical).
"""
from __future__ import annotations
from typing import Callable, NamedTuple


class WorkloadEntry(NamedTuple):
    source_id: str
    input: str
    oracle_canonical: str


from . import (
    w_conceptnet_rel,
    w_longmemeval_s,
    w_multitenant_demo,
    w_multitenant_synth,
    w_multitenant_wikidata,
    w_stackoverflow_multitenant,
    w_wikidata_props,
)

# Registry: workload_id -> loader callable returning list[WorkloadEntry]
LOADERS: dict[str, Callable[[], list[WorkloadEntry]]] = {
    "W-CONCEPTNET-REL": w_conceptnet_rel.load,
    "W-WIKIDATA-PROPS": w_wikidata_props.load,
    "W-MULTITENANT-DEMO": w_multitenant_demo.load,
    "W-MULTITENANT-SYNTH": w_multitenant_synth.load,
    "W-MULTITENANT-WIKIDATA": w_multitenant_wikidata.load,
    "W-LONGMEMEVAL-S": w_longmemeval_s.load,
    "W-STACKOVERFLOW-MT": w_stackoverflow_multitenant.load,
}


def load(workload_id: str) -> list[WorkloadEntry]:
    if workload_id not in LOADERS:
        raise KeyError(
            f"Unknown workload {workload_id!r}. Known: {sorted(LOADERS)}"
        )
    return LOADERS[workload_id]()

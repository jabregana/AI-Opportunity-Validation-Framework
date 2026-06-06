from __future__ import annotations
from typing import Callable

from . import w_conceptnet_rel

# Registry: workload_id -> loader callable returning list[(input_relation, oracle_canonical)]
LOADERS: dict[str, Callable[[], list[tuple[str, str]]]] = {
    "W-CONCEPTNET-REL": w_conceptnet_rel.load,
}


def load(workload_id: str) -> list[tuple[str, str]]:
    if workload_id not in LOADERS:
        raise KeyError(
            f"Unknown workload {workload_id!r}. Known: {sorted(LOADERS)}"
        )
    return LOADERS[workload_id]()

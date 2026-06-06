"""W-WIKIDATA-PROPS — WikiData property aliases workload.

For each WikiData property fetched by fixtures/generators/wikidata_aliases.py:
  - the canonical label is the oracle canonical
  - each English alias is one input write paired with that canonical
  - the label itself is also written (paired with itself, sanity)

The cached JSON file must exist before this loader is called. Regenerate
with `python -m fixtures.generators.wikidata_aliases --max-pid N`.

This workload exercises real paraphrase distribution and is the first
non-synthetic fixture in the registry. ConceptNet (W-CONCEPTNET-REL) is
dominated by case/underscore variants; WikiData has substantial true
paraphrase content that test the neural and hybrid embedders properly.
"""
from __future__ import annotations
import json
from pathlib import Path

_CACHE = Path(__file__).resolve().parent.parent / "data" / "wikidata_aliases.json"


def _ensure_cache() -> dict:
    if not _CACHE.exists():
        raise FileNotFoundError(
            f"WikiData cache not found at {_CACHE}. "
            "Run `python -m fixtures.generators.wikidata_aliases --max-pid 500` first."
        )
    return json.loads(_CACHE.read_text())


def load():
    """Return the deterministic workload stream.

    Each entry is one write event. Single-tenant workload, so source_id
    is "default" for every entry. The canonical label appears once paired
    with itself, then once per alias paired with the label.
    """
    from . import WorkloadEntry

    data = _ensure_cache()
    entries: list[WorkloadEntry] = []
    for prop in data["properties"]:
        label = prop["label"]
        entries.append(WorkloadEntry("default", label, label))
        for alias in prop["aliases"]:
            entries.append(WorkloadEntry("default", alias, label))
    return entries


def oracle_cardinality() -> int:
    data = _ensure_cache()
    return data["n_properties"]

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


def load() -> list[tuple[str, str]]:
    """Return the deterministic workload stream.

    Each (input_surface_form, canonical_label) pair is one write event.
    The canonical label appears once paired with itself, then once per
    alias paired with itself.
    """
    data = _ensure_cache()
    pairs: list[tuple[str, str]] = []
    for prop in data["properties"]:
        label = prop["label"]
        pairs.append((label, label))
        for alias in prop["aliases"]:
            pairs.append((alias, label))
    return pairs


def oracle_cardinality() -> int:
    data = _ensure_cache()
    return data["n_properties"]

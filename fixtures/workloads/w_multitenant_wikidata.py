"""W-MULTITENANT-WIKIDATA — KG-grounded multi-tenant workload.

Track 2 of the v0.4.1 evaluation data plan. Reads the cached JSON
produced by fixtures/generators/wikidata_disambiguation.py.

For each curated ambiguous surface form (Apple, Mercury, Oracle,
Mustang, etc.), the generator pulled multiple distinct WikiData
entities. Each entity is mapped to a "team domain" (automotive,
biology, music, tech_company, etc.) based on the entity's nature.
The workload represents the realistic scenario where, e.g., the
'automotive' team writes 'Mustang' meaning the Ford Mustang while the
'biology' team writes 'Mustang' meaning the feral horse.

Compared to Track 1 (W-MULTITENANT-SYNTH), Track 2's oracle is the
real WikiData label for the QID. The 'source domain' assignment is
the synthetic part; everything else is real KG data.

The cached JSON file must exist before this loader is called.
Regenerate with `python -m fixtures.generators.wikidata_disambiguation`.

Workload entries:
  source_id        = the mapped team domain (automotive, biology, ...)
  input            = an alias OR the canonical label
  oracle_canonical = the WikiData entity's canonical English label
"""
from __future__ import annotations
import json
from pathlib import Path


_CACHE = Path(__file__).resolve().parent.parent / "data" / "wikidata_disambiguation.json"


def _ensure_cache() -> dict:
    if not _CACHE.exists():
        raise FileNotFoundError(
            f"WikiData disambiguation cache not found at {_CACHE}. "
            "Run `python -m fixtures.generators.wikidata_disambiguation` first."
        )
    return json.loads(_CACHE.read_text())


def load():
    """Generate the deterministic workload stream."""
    from . import WorkloadEntry

    data = _ensure_cache()
    entries: list[WorkloadEntry] = []
    for surface_entry in data["surfaces"]:
        surface = surface_entry["surface"]
        for candidate in surface_entry["candidates"]:
            domain = candidate["domain"]
            canonical_label = candidate["actual_label"]
            # 1) the curated surface form itself (Apple, Mustang, ...)
            entries.append(WorkloadEntry(domain, surface, canonical_label))
            # 2) the actual WikiData label (if it differs from the curated surface)
            if canonical_label.lower() != surface.lower():
                entries.append(WorkloadEntry(domain, canonical_label, canonical_label))
            # 3) each English alias
            for alias in candidate["aliases"]:
                entries.append(WorkloadEntry(domain, alias, canonical_label))
    return entries


def disambiguated_surfaces() -> list[str]:
    """Surfaces with multiple distinct canonicals in the cache.
    Useful for v0.4.1 evaluation when source-aware metrics land."""
    data = _ensure_cache()
    return [
        s["surface"]
        for s in data["surfaces"]
        if len(s["candidates"]) > 1
    ]

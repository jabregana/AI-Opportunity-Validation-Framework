"""W-STACKOVERFLOW-MT — multi-tenant workload from Stack Overflow tag data.

Source = programming language tag (python, javascript, java, go, ruby, rust).
Input = a related tag for that language (fetched from the SO API).
Oracle = the related-tag name itself (assumed globally unambiguous in
the SO ecosystem; the same tag means the same concept regardless of
which language asks about it).

This is the second real-data multi-tenant workload, complementing
W-MULTITENANT-WIKIDATA. Where WIKIDATA tests disambiguation
(same surface, different meanings per source), Stack Overflow tests
cross-source consensus (same surface, same meaning across sources;
proxy should merge them).

Generate the cache with:
  python -m fixtures.generators.stackoverflow_tags
"""
from __future__ import annotations
import json
from pathlib import Path

_CACHE = (
    Path(__file__).resolve().parent.parent / "data" / "stackoverflow_tags.json"
)


def load():
    from . import WorkloadEntry

    if not _CACHE.exists():
        raise FileNotFoundError(
            f"Stack Overflow tag cache not found at {_CACHE}. "
            "Run `python -m fixtures.generators.stackoverflow_tags` first."
        )
    data = json.loads(_CACHE.read_text())
    entries: list[WorkloadEntry] = []
    for src in data["by_source"]:
        source_id = src["source"]
        for related in src["related_tags"]:
            entries.append(WorkloadEntry(source_id, related, related))
        # Synonyms add aliases: each from_tag maps to a to_tag canonical
        for from_tag, to_tag in src.get("synonyms", []):
            entries.append(WorkloadEntry(source_id, from_tag, to_tag))
    return entries

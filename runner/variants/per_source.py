"""v0.4.0 multi-tenant proxy: per-source namespace isolation.

Each source_id (team, user, tenant) gets its own inner variant instance
and its own canonical store. When source_id arrives in the context, the
proxy dispatches to that source's inner variant. Canonicals are
prefixed with the source_id ("sales::Apple_Inc") so the harness can
tell apart writes that happen to share an input string across sources.

This is the simplest correct architectural answer to the user's
scenario:

  "When a team of 8 is querying the same agent, 'Apple the company'
  might be authoritative from the sales team but ambiguous to the ops
  team who interacts with Apple the supplier and Apple the tech company
  in different contexts. The resolution engine now needs to track not
  just node identity but source identity."

Per-source isolation literally tracks source identity. Sales "Apple"
and ops "Apple" become distinct canonicals; they never alias.

Known limitation, surfaced by W-MULTITENANT-DEMO: this is too
aggressive on globally unambiguous entities. Sales "Microsoft" and ops
"Microsoft" both legitimately mean Microsoft_Corp; per-source isolation
keeps them apart. A v0.4.1 cross-source consensus variant would detect
unambiguous-across-sources entities and merge them into a "shared"
namespace.

Tracking the gap is intentional. v0.4.0 ships the architecture; v0.4.1
adds the smarter resolution policy.
"""
from __future__ import annotations
from typing import Callable

from .base import Variant


class PerSourceNamespaceProxy(Variant):
    """Maintain one inner variant per observed source_id.

    Inner variant factory defaults to v0.3.1 (hybrid + structural
    filter). Each source gets its own fresh instance, lazily
    constructed on first contact.
    """

    name = "embed-proxy-v0.4.0-per-source"

    def __init__(self, inner_factory: Callable[[], Variant] | None = None):
        if inner_factory is None:
            # Default inner: v0.3.1 hybrid + structural filter
            from .embed_proxy import StructurallyFilteredHybridSchemaProxy

            inner_factory = StructurallyFilteredHybridSchemaProxy
        self._inner_factory = inner_factory
        self._per_source: dict[str, Variant] = {}

    @property
    def known_sources(self) -> list[str]:
        return list(self._per_source.keys())

    def _inner_for(self, source_id: str) -> Variant:
        inner = self._per_source.get(source_id)
        if inner is None:
            inner = self._inner_factory()
            self._per_source[source_id] = inner
        return inner

    def align(self, input_relation: str) -> str:
        """Single-tenant fallback: route to a global namespace."""
        return self.align_with_context(input_relation, context=None)

    def align_with_context(
        self,
        input_relation: str,
        context: dict | None = None,
    ) -> str:
        source_id = (context or {}).get("source_id", "default")
        inner = self._inner_for(source_id)
        local_canonical = inner.align(input_relation)
        return f"{source_id}::{local_canonical}"

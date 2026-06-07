"""CogneePreNormalized — proxy as pre-normalization middleware for
Cognee memory.

Cognee (https://github.com/topoteretes/cognee) is an AI memory
framework that ingests free-form text via `cognee.add(...)` and
processes it into a knowledge graph via `cognee.cognify(...)`. Like
Mem0 and Graphiti, Cognee's downstream LLM extraction sees the raw
input text; without canonicalization, the same entity arriving under
different surface forms produces multiple nodes in the resulting
graph.

This wrapper mirrors Mem0PreNormalized and GraphitiPreNormalized: take
a Cognee module reference and pre-normalize entity mentions in the
text before forwarding to the module's `add()`. Downstream `cognify()`
then sees consistent canonicals and builds a coherent graph instead
of a fragmented one.

Notable API-shape difference from Mem0/Graphiti
-----------------------------------------------

Cognee exposes its API as module-level async functions, not as an
instance class. You call `await cognee.add(...)` directly, not
`memory.add(...)`. This wrapper still accepts the cognee module as a
constructor argument so tests can pass a fake stub; in production the
constructor defaults to importing the real `cognee` module.

Two extraction modes, same as the other wrappers:

  1. dict-based replacement via mention_map: alias -> canonical
  2. callable extractor via mention_extractor: text -> spans

NOTE: This integration depends on `cognee` being installed in
production. It is optional. The wrapper does not import cognee at
module load; only at construction (and only when a real module is
needed, i.e. when no test stub is provided).
"""
from __future__ import annotations
import re
from typing import Any, Callable

from ..normalizer import EntityNormalizer


class CogneePreNormalized:
    """Drop-in wrapper around the Cognee module. Public surface mirrors
    Cognee's ingestion API (`add`, `cognify`, plus passthrough to any
    other module-level callable via __getattr__).
    """

    def __init__(
        self,
        normalizer: EntityNormalizer,
        cognee_module: Any | None = None,
        *,
        mention_map: dict[str, str] | None = None,
        mention_extractor: Callable[[str], list[tuple[int, int, str]]] | None = None,
    ):
        if mention_map is None and mention_extractor is None:
            raise ValueError(
                "must provide mention_map (dict[alias, canonical]) or "
                "mention_extractor (callable returning spans)"
            )
        if cognee_module is None:
            try:
                import cognee  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "cognee not installed; install with `pip install cognee` "
                    "or pass a stub via the cognee_module argument (tests)"
                ) from e
            cognee_module = cognee
        self._cognee = cognee_module
        self._normalizer = normalizer
        self._mention_map = mention_map or {}
        self._extractor = mention_extractor

    async def add(self, data, dataset_name: str | None = None, **kwargs):
        """Pre-normalize entity mentions in `data` before forwarding to
        cognee.add(). The `dataset_name` is used as the multi-tenant
        source_id for the normalizer (so per-dataset variants see the
        right source).

        Cognee's `add()` accepts either a single string or a list of
        strings; the wrapper handles both shapes.
        """
        normalized = self._normalize_payload(data, dataset_name)
        if dataset_name is not None:
            return await self._cognee.add(
                normalized, dataset_name=dataset_name, **kwargs
            )
        return await self._cognee.add(normalized, **kwargs)

    async def cognify(self, *args, **kwargs):
        """Forward to cognee.cognify unchanged. The pre-normalization
        has already happened upstream during add()."""
        return await self._cognee.cognify(*args, **kwargs)

    def _normalize_payload(self, data, dataset_name: str | None):
        """Cognee's add() accepts a single string or a list of strings.
        Normalize each string element; pass through other shapes
        unchanged (the caller may be using cognee's file-path or
        binary-data modes, which the proxy does not touch)."""
        if isinstance(data, str):
            return self._normalize_text(data, dataset_name)
        if isinstance(data, list):
            return [
                self._normalize_text(item, dataset_name)
                if isinstance(item, str) else item
                for item in data
            ]
        return data

    def _normalize_text(self, text: str, dataset_name: str | None) -> str:
        """Apply mention_map first (single-pass regex, longest-first
        alternation) then run callable extractor. Mirrors the
        Mem0PreNormalized and GraphitiPreNormalized implementations
        exactly so all three wrappers share the same normalization
        semantics."""
        out = text
        if self._mention_map:
            aliases_longest_first = sorted(self._mention_map, key=len, reverse=True)
            pattern = re.compile(
                "|".join(re.escape(a) for a in aliases_longest_first)
            )

            def _sub(match):
                alias = match.group(0)
                canonical_raw = self._mention_map[alias]
                return self._normalizer.normalize(
                    canonical_raw,
                    context={"source_id": dataset_name} if dataset_name else None,
                )

            out = pattern.sub(_sub, out)
        if self._extractor is not None:
            spans = list(self._extractor(out))
            spans.sort(key=lambda s: -s[0])
            for start, end, surface in spans:
                canonical = self._normalizer.normalize(
                    surface,
                    context={"source_id": dataset_name} if dataset_name else None,
                )
                out = out[:start] + canonical + out[end:]
        return out

    def __getattr__(self, name):
        # Pass through other Cognee module-level entry points
        # (search, prune, visualize, etc.)
        return getattr(self._cognee, name)

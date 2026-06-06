"""GraphitiPreNormalized — proxy as pre-normalization middleware for
Graphiti graph memory.

Graphiti (https://github.com/getzep/graphiti) is a temporal knowledge
graph framework. Like Mem0, it accepts free-form text and writes
entity / relation triples to a graph backend (Neo4j by default).
Without canonicalization the same entity arriving under different
surface forms produces multiple nodes for one conceptual entity,
fragmenting the graph in the same way Mem0 does.

This wrapper mirrors Mem0PreNormalized: take a Graphiti client and
pre-normalize entity mentions in input text before forwarding to the
client's `add_episode()` (and other ingestion methods). The downstream
Graphiti pipeline sees consistent canonicals and produces a coherent
graph instead of a fragmented one.

Two extraction modes, same as Mem0PreNormalized:

  1. dict-based replacement via mention_map: alias -> canonical
  2. callable extractor via mention_extractor: text -> spans

NOTE: This integration depends on `graphiti-core` being installed. It
is optional. The import is guarded so the rest of the project keeps
running without graphiti-core present.

Graphiti's primary ingestion entry point is `Graphiti.add_episode()`
(with a few variants like `add_episode_bulk`). This wrapper proxies
those entry points and passes through other methods (`search`, etc.)
unchanged.
"""
from __future__ import annotations
import re
from typing import Any, Callable

from ..normalizer import EntityNormalizer


class GraphitiPreNormalized:
    """Drop-in wrapper around a Graphiti client. Public surface matches
    Graphiti's ingestion API so existing code can swap it in. Other
    Graphiti methods (search, get, delete, etc.) pass through via
    __getattr__.
    """

    def __init__(
        self,
        graphiti: Any,
        normalizer: EntityNormalizer,
        *,
        mention_map: dict[str, str] | None = None,
        mention_extractor: Callable[[str], list[tuple[int, int, str]]] | None = None,
    ):
        if mention_map is None and mention_extractor is None:
            raise ValueError(
                "must provide mention_map (dict[alias, canonical]) or "
                "mention_extractor (callable returning spans)"
            )
        self._graphiti = graphiti
        self._normalizer = normalizer
        self._mention_map = mention_map or {}
        self._extractor = mention_extractor

    async def add_episode(
        self,
        name: str,
        episode_body: str,
        *args,
        **kwargs,
    ):
        """Pre-normalize entity mentions in episode_body before forwarding
        to Graphiti's add_episode. Returns whatever Graphiti returns.

        Graphiti's add_episode is async (graphiti-core uses asyncio
        end-to-end). The wrapper preserves the contract."""
        normalized_body = self._normalize_text(
            episode_body,
            kwargs.get("group_id") or kwargs.get("source_id"),
        )
        return await self._graphiti.add_episode(
            name=name,
            episode_body=normalized_body,
            *args,
            **kwargs,
        )

    async def add_episode_bulk(
        self,
        episodes: list,
        *args,
        **kwargs,
    ):
        """Pre-normalize episode_body on every episode in the bulk list."""
        group_id = kwargs.get("group_id")
        normalized = []
        for ep in episodes:
            if hasattr(ep, "episode_body"):
                # graphiti-core's RawEpisode-like object
                new_body = self._normalize_text(ep.episode_body, group_id)
                # Best-effort: copy with the new body. If the type
                # supports `model_copy` (pydantic v2) use it; else
                # mutate in place.
                if hasattr(ep, "model_copy"):
                    normalized.append(ep.model_copy(update={"episode_body": new_body}))
                else:
                    ep.episode_body = new_body
                    normalized.append(ep)
            else:
                normalized.append(ep)
        return await self._graphiti.add_episode_bulk(
            episodes=normalized,
            *args,
            **kwargs,
        )

    def _normalize_text(self, text: str, group_id: str | None) -> str:
        """Apply mention_map first (single-pass regex, longest-first
        alternation) then run callable extractor. Mirrors the
        Mem0PreNormalized implementation exactly so both wrappers share
        the same normalization semantics."""
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
                    context={"source_id": group_id} if group_id else None,
                )

            out = pattern.sub(_sub, out)
        if self._extractor is not None:
            spans = list(self._extractor(out))
            spans.sort(key=lambda s: -s[0])
            for start, end, surface in spans:
                canonical = self._normalizer.normalize(
                    surface,
                    context={"source_id": group_id} if group_id else None,
                )
                out = out[:start] + canonical + out[end:]
        return out

    def __getattr__(self, name):
        # Pass through other Graphiti methods (search, build_communities,
        # remove_episode, etc.)
        return getattr(self._graphiti, name)

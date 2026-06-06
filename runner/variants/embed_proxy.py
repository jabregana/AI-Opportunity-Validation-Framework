"""v0.1.0 schema-alignment proxy: embed + nearest-canonical.

The proxy maintains a canonical store. For each incoming relation:
  1. Normalize and embed the surface form.
  2. Find the existing canonical with the highest cosine similarity.
  3. If that similarity is at or above the threshold, return that canonical.
  4. Otherwise mint a new canonical (the input surface form becomes its
     own canonical name; first writer wins).

The embedder is pluggable behind a Protocol. The v0.1.0 default is a
stdlib hashing-trick bag-of-tokens embedder. It catches the
case/underscore/camelCase class of synonyms (`WORKS_AT`, `works_at`,
`WorksAt`) but not paraphrase synonyms (`IS_A` vs `INSTANCE_OF`).
Paraphrase coverage is the job of a neural embedder, which can be
swapped in via the Embedder protocol.

Closest neural-embedder candidates (not implemented in v0.1.0 because of
PyTorch / Python 3.14 wheel availability):
  - sentence-transformers/all-MiniLM-L6-v2 (22M params, well-known)
  - BAAI/bge-small-en-v1.5 (33M params, strong on STS benchmarks)
  - model2vec (distilled static embeddings, no torch at inference)
"""
from __future__ import annotations
import hashlib
import re
from typing import Protocol

from .base import Variant


class Embedder(Protocol):
    """Embedder contract: text in, fixed-length dense vector out."""

    def embed(self, text: str) -> list[float]: ...

    @property
    def dim(self) -> int: ...


# Two-pass word-boundary detection for camelCase / PascalCase / acronyms.
# Pass A: APIKey -> API Key   (UPPER+ followed by UPPER+lower)
# Pass B: camelCase -> camel Case   (lower-or-digit followed by UPPER)
_CAMEL_ACRONYM_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")


def _tokens(text: str) -> list[str]:
    """Lowercase tokens. Split on camelCase boundaries, acronym boundaries
    (APIKey), underscores, hyphens, and whitespace."""
    text = _CAMEL_ACRONYM_RE.sub(r"\1 \2", text)
    text = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ")
    return [t.lower() for t in text.split() if t]


class HashedTokenEmbedder:
    """Hashing-trick bag-of-tokens embedder.

    Each token hashes (SHA-256) to a fixed-dim bucket with a signed
    contribution (the "feature hashing" technique). The resulting vector
    is L2-normalized. No external dependencies; deterministic across
    Python versions; constant memory; no vocab maintenance.

    Limitations:
      - Treats tokens as orthogonal. "works" and "employed" land in
        unrelated buckets.
      - Hash collisions reduce signal at low dim. Default dim=256 is
        fine for vocabularies under a few thousand unique tokens.
    """

    def __init__(self, dim: int = 256):
        if dim < 8:
            raise ValueError(f"dim must be >= 8, got {dim}")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in _tokens(text):
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm_sq = sum(v * v for v in vec)
        if norm_sq <= 0:
            return vec  # empty token list; zero vector
        inv_norm = 1.0 / (norm_sq**0.5)
        return [v * inv_norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for equal-length, ideally L2-normalized vectors."""
    return sum(x * y for x, y in zip(a, b))


class EmbeddingSchemaProxy(Variant):
    """v0.1.0 proxy. Embed-and-nearest-canonical with similarity threshold.

    Cache: identical input surface forms always return the same canonical
    (deterministic across replays).

    Mint policy: when no existing canonical is within threshold, the input
    surface form becomes its own canonical. First writer wins.
    """

    name = "embed-proxy-v0.1.0"

    def __init__(
        self,
        embedder: Embedder | None = None,
        similarity_threshold: float = 0.7,
    ):
        if not -1.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"threshold must be in [-1, 1], got {similarity_threshold}"
            )
        self.embedder = (
            embedder if embedder is not None else HashedTokenEmbedder()
        )
        self.threshold = similarity_threshold
        self._canonicals: list[str] = []
        self._embeddings: list[list[float]] = []
        self._cache: dict[str, str] = {}

    @property
    def canonical_count(self) -> int:
        return len(self._canonicals)

    def align(self, input_relation: str) -> str:
        cached = self._cache.get(input_relation)
        if cached is not None:
            return cached

        emb = self.embedder.embed(input_relation)

        if not self._embeddings:
            self._canonicals.append(input_relation)
            self._embeddings.append(emb)
            self._cache[input_relation] = input_relation
            return input_relation

        best_idx = 0
        best_sim = _cosine(emb, self._embeddings[0])
        for i in range(1, len(self._embeddings)):
            sim = _cosine(emb, self._embeddings[i])
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        if best_sim >= self.threshold:
            chosen = self._canonicals[best_idx]
        else:
            self._canonicals.append(input_relation)
            self._embeddings.append(emb)
            chosen = input_relation

        self._cache[input_relation] = chosen
        return chosen


class NeuralEmbeddingSchemaProxy(EmbeddingSchemaProxy):
    """v0.2.0 proxy: same algorithm as v0.1.0 but with a neural embedder.

    Default: model2vec potion-base-32M with the sentence template
    "the relation type called X". Threshold 0.75 — a compromise that
    captures most paraphrase synonyms (IsA <-> INSTANCE_OF: 0.71;
    Causes <-> leads_to: 0.75; Desires <-> wants: 0.90) at the cost of
    some false positives on antonyms and siblings (Synonym <-> Antonym:
    0.65 passes; LOCATED_IN <-> LOCATED_NEAR: 0.93 passes). UC-4.4 Tier
    A and Tier B are the gates that explicitly catch the false-positive
    class.
    """

    name = "embed-proxy-v0.2.0"

    def __init__(
        self,
        model_name: str = "minishlab/potion-base-32M",
        similarity_threshold: float = 0.75,
        template: str | None = "the relation type called {}",
    ):
        from .neural_embedder import Model2VecEmbedder

        super().__init__(
            embedder=Model2VecEmbedder(model_name, template=template),
            similarity_threshold=similarity_threshold,
        )

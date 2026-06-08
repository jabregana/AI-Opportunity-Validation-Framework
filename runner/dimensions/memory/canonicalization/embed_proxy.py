"""v0.1.0 schema-alignment proxy: embed + nearest-canonical.

The proxy maintains a canonical store. For each incoming relation:
  1. Normalize and embed the surface form.
  2. Find the existing canonical with the highest cosine similarity.
  3. If that similarity is at or above the threshold, optionally check a
     merge_guard callback; if either is unsatisfied, fall through to (4).
  4. Otherwise mint a new canonical (the input surface form becomes its
     own canonical name; first writer wins).

The embedder is pluggable behind a Protocol. The v0.1.0 default is a
stdlib hashing-trick bag-of-tokens embedder. It catches the
case/underscore/camelCase class of synonyms (`WORKS_AT`, `works_at`,
`WorksAt`) but not paraphrase synonyms (`IS_A` vs `INSTANCE_OF`).
Paraphrase coverage is the job of a neural embedder, which can be
swapped in via the Embedder protocol.

The merge_guard callback (added in v0.3.1) is a deterministic filter
that fires AFTER the embedding-based match. Returning False blocks the
merge and forces a new canonical. Used to encode structural rules
(digit content, prepositional asymmetry) that semantic similarity
cannot resolve.

Closest neural-embedder candidates (not implemented in v0.1.0 because of
PyTorch / Python 3.14 wheel availability):
  - sentence-transformers/all-MiniLM-L6-v2 (22M params, well-known)
  - BAAI/bge-small-en-v1.5 (33M params, strong on STS benchmarks)
  - model2vec (distilled static embeddings, no torch at inference)
"""
from __future__ import annotations
import hashlib
import re
from typing import Callable, Protocol

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

    def __init__(self, dim: int = 4096):
        # Default raised from 256 to 4096 after discovering token-pair
        # hash collisions at dim=256 caused 1.0 false-positive cosine
        # (e.g. account/vendor collide). See
        # docs/finding-multitenant-tier-b.md Bug 1.
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
        merge_guard: Callable[[str, str], bool] | None = None,
    ):
        if not -1.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"threshold must be in [-1, 1], got {similarity_threshold}"
            )
        self.embedder = (
            embedder if embedder is not None else HashedTokenEmbedder()
        )
        self.threshold = similarity_threshold
        # Default: always allow the embedding-based match.
        self.merge_guard = merge_guard or (lambda _input, _canonical: True)
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

        if best_sim >= self.threshold and self.merge_guard(
            input_relation, self._canonicals[best_idx]
        ):
            chosen = self._canonicals[best_idx]
        else:
            self._canonicals.append(input_relation)
            self._embeddings.append(emb)
            chosen = input_relation

        self._cache[input_relation] = chosen
        return chosen


class HybridConcatEmbedder:
    """Concatenate two or more sub-embedder outputs with optional weights,
    then L2-renormalize the result.

    Each sub-embedder is expected to return its own L2-normalized vector.
    The weighted concatenation has norm sqrt(sum(w_i^2)). After
    renormalization, the cosine between two hybrid vectors becomes:

        cos_hybrid(a, b) = sum_i w_i^2 * cos_i(a, b) / sum_i w_i^2

    So equal weights give the plain average of component cosines. Setting
    a sub-embedder's weight to zero drops it from the hybrid entirely.
    """

    def __init__(self, embedders_with_weights: list[tuple[Embedder, float]]):
        if not embedders_with_weights:
            raise ValueError("need at least one embedder")
        if any(w < 0 for _, w in embedders_with_weights):
            raise ValueError("weights must be non-negative")
        if sum(w for _, w in embedders_with_weights) <= 0:
            raise ValueError("at least one weight must be positive")
        self._parts = embedders_with_weights
        self._dim = sum(e.dim for e, _ in embedders_with_weights)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        out: list[float] = []
        for emb, w in self._parts:
            v = emb.embed(text)
            out.extend(x * w for x in v)
        norm_sq = sum(x * x for x in out)
        if norm_sq <= 0:
            return out
        inv = 1.0 / (norm_sq**0.5)
        return [x * inv for x in out]


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


class StructurallyFilteredHybridSchemaProxy(EmbeddingSchemaProxy):
    """v0.3.1 proxy: HybridSchemaProxy plus a deterministic structural
    merge guard.

    Identical embedding logic to v0.3.0 (token + neural concat with
    token-dominant weights, threshold 0.8). After the embedding match
    clears threshold, a deterministic filter runs:

      Rule 1: digit content differs       -> block the merge
      Rule 2: trailing preposition asymm. -> block the merge

    Both rules came directly from observed v0.3.0 failures on the
    WikiData Tier B gauntlet (ISO 639-X codes, "review score" vs
    "review score by"). Adding them is expected to reduce Tier B
    false-merge rate without sacrificing UC-4.1 wins.

    The filter is variant-specific: it is wired only into this variant,
    not into v0.3.0 itself, so the harness can compare them
    side-by-side and credit the filter's contribution explicitly.
    """

    name = "embed-proxy-v0.3.1"

    def __init__(
        self,
        token_weight: float = 2.0,
        neural_weight: float = 1.0,
        similarity_threshold: float = 0.8,
        model_name: str = "minishlab/potion-base-32M",
        template: str | None = "the relation type called {}",
    ):
        from .neural_embedder import Model2VecEmbedder
        from .structural_filter import structural_merge_guard

        token_emb = HashedTokenEmbedder()
        neural_emb = Model2VecEmbedder(model_name, template=template)
        hybrid = HybridConcatEmbedder(
            [(token_emb, token_weight), (neural_emb, neural_weight)]
        )
        super().__init__(
            embedder=hybrid,
            similarity_threshold=similarity_threshold,
            merge_guard=structural_merge_guard,
        )


class ANNSchemaProxy(EmbeddingSchemaProxy):
    """v0.5.5 proxy: same matching policy as v0.3.1 but the nearest-canonical
    lookup is delegated to an ANN index (HNSW if hnswlib is installed,
    else a numpy-vectorized linear scan).

    Motivation: the default `align()` does a pure-Python O(K) cosine
    scan against every canonical, which collapses throughput at the
    K~10k+ scale documented in `docs/finding-scale-stress.md`. The ANN
    index keeps lookups sub-linear (HNSW) or at least vectorized
    (numpy linear).

    Behavior parity with v0.3.1 is the design constraint: same
    structural filter, same threshold, same first-writer-wins canonical
    naming. The ANN index is wired so that insertion order matches the
    canonical list order; deterministic replays produce identical
    outputs.

    Approximation note: HNSW is approximate. For top-1 cosine lookup at
    the recall settings used here (M=16, ef_search=64) the top-1 match
    is within ~1% recall of the exact answer on typical embedding
    distributions. Below-threshold near-matches (which never trigger an
    alias anyway) are where the approximation error concentrates; this
    matters only for variants that gate behavior on borderline cosines.
    """

    name = "embed-proxy-v0.5.5-ann"

    def __init__(
        self,
        token_weight: float = 2.0,
        neural_weight: float = 1.0,
        similarity_threshold: float = 0.8,
        model_name: str = "minishlab/potion-base-32M",
        template: str | None = "the relation type called {}",
        ann_backend: str = "auto",
    ):
        from .ann_index import build_index
        from .neural_embedder import Model2VecEmbedder
        from .structural_filter import structural_merge_guard

        token_emb = HashedTokenEmbedder()
        neural_emb = Model2VecEmbedder(model_name, template=template)
        hybrid = HybridConcatEmbedder(
            [(token_emb, token_weight), (neural_emb, neural_weight)]
        )
        super().__init__(
            embedder=hybrid,
            similarity_threshold=similarity_threshold,
            merge_guard=structural_merge_guard,
        )
        self._ann = build_index(hybrid.dim, backend=ann_backend)
        self._ann_backend = ann_backend

    @property
    def ann_backend_name(self) -> str:
        return type(self._ann).__name__

    def align(self, input_relation: str) -> str:
        cached = self._cache.get(input_relation)
        if cached is not None:
            return cached

        emb = self.embedder.embed(input_relation)

        if self._ann.size == 0:
            self._canonicals.append(input_relation)
            self._embeddings.append(emb)
            self._ann.add(0, emb)
            self._cache[input_relation] = input_relation
            return input_relation

        best_idx, best_sim = self._ann.nearest(emb)

        if best_sim >= self.threshold and self.merge_guard(
            input_relation, self._canonicals[best_idx]
        ):
            chosen = self._canonicals[best_idx]
        else:
            new_idx = len(self._canonicals)
            self._canonicals.append(input_relation)
            self._embeddings.append(emb)
            self._ann.add(new_idx, emb)
            chosen = input_relation

        self._cache[input_relation] = chosen
        return chosen


class HybridSchemaProxy(EmbeddingSchemaProxy):
    """v0.3.0 proxy: hybrid token + neural embedder.

    Concatenates HashedTokenEmbedder and Model2VecEmbedder vectors with
    configurable weights, then L2-renormalizes. Effective cosine is the
    weighted average of component cosines (with weights squared in the
    averaging).

    Goal: keep v0.1.0's perfect case/underscore signal (token cosine = 1.0
    on surface variants of the same canonical) AND add paraphrase signal
    from the neural embedder where it is strong enough to clear the
    threshold.

    Default config: token_weight=2.0, neural_weight=1.0, threshold=0.8.
    Quadratic weighting puts 80% of the cosine on the token component and
    20% on the neural. A parameter sweep over W-CONCEPTNET-REL showed
    this beats v0.1.0 by ~0.04 on B-cubed F1; equal-weight concat
    regresses by 0.08 because the neural cosine acts as a veto on case
    variants where it is weak.

    Known limitation: the neural embedder gives HIGHER cosine on hard
    negatives (MadeOf <-> PartOf: 0.925) than on true paraphrases
    (IsA <-> INSTANCE_OF: 0.71). No threshold cleanly separates the two
    classes. The default config does NOT attempt to catch most
    paraphrases; it preserves v0.1.0's case-variant strength and picks
    up a small amount of additional signal from neural where token is
    nearly-but-not-quite at threshold. UC-4.4 Tier B is the explicit
    gate for measuring the false-positive cost of any threshold drop.
    """

    name = "embed-proxy-v0.3.0"

    def __init__(
        self,
        token_weight: float = 2.0,
        neural_weight: float = 1.0,
        similarity_threshold: float = 0.8,
        model_name: str = "minishlab/potion-base-32M",
        template: str | None = "the relation type called {}",
    ):
        from .neural_embedder import Model2VecEmbedder

        token_emb = HashedTokenEmbedder()
        neural_emb = Model2VecEmbedder(model_name, template=template)
        hybrid = HybridConcatEmbedder(
            [(token_emb, token_weight), (neural_emb, neural_weight)]
        )
        super().__init__(
            embedder=hybrid, similarity_threshold=similarity_threshold
        )

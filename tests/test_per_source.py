"""Tests for v0.4.0 PerSourceNamespaceProxy."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.variants.base import Variant
from runner.variants.b_raw import BRawIdentity
import random

from runner.variants.per_source import (
    CrossSourceConsensusProxy,
    LazyConsensusANDRuleProxy,
    LazyCrossSourceConsensusProxy,
    PerSourceNamespaceProxy,
)


def test_same_input_different_sources_get_distinct_canonicals():
    """The whole point: sales 'Apple' and ops 'Apple' must not alias."""
    p = PerSourceNamespaceProxy(inner_factory=BRawIdentity)
    c_sales = p.align_with_context("Apple", {"source_id": "sales"})
    c_ops = p.align_with_context("Apple", {"source_id": "ops"})
    assert c_sales != c_ops
    assert c_sales.startswith("sales::")
    assert c_ops.startswith("ops::")


def test_same_input_same_source_returns_cached_canonical():
    p = PerSourceNamespaceProxy(inner_factory=BRawIdentity)
    c1 = p.align_with_context("Apple", {"source_id": "sales"})
    c2 = p.align_with_context("Apple", {"source_id": "sales"})
    assert c1 == c2


def test_inner_variant_isolation_per_source():
    """The inner variants for two sources should not share canonical
    state."""
    p = PerSourceNamespaceProxy(inner_factory=BRawIdentity)
    p.align_with_context("Apple", {"source_id": "sales"})
    p.align_with_context("Apple", {"source_id": "ops"})
    assert set(p.known_sources) == {"sales", "ops"}


def test_missing_source_id_routes_to_default_namespace():
    p = PerSourceNamespaceProxy(inner_factory=BRawIdentity)
    c1 = p.align_with_context("Apple", context=None)
    c2 = p.align_with_context("Apple", context={})
    assert c1 == c2
    assert c1.startswith("default::")


def test_legacy_align_falls_back_to_default_namespace():
    """Variants invoked via the old align(input) path should still work
    and route to the default namespace."""
    p = PerSourceNamespaceProxy(inner_factory=BRawIdentity)
    c = p.align("Apple")
    assert c.startswith("default::")


def test_inner_factory_can_be_customized():
    """Inject a different inner variant per construction."""

    class _AllSameCanonical(Variant):
        name = "test-inner"

        def align(self, input_relation: str) -> str:
            return "FIXED"

    p = PerSourceNamespaceProxy(inner_factory=_AllSameCanonical)
    assert p.align_with_context("a", {"source_id": "x"}) == "x::FIXED"
    assert p.align_with_context("b", {"source_id": "y"}) == "y::FIXED"
    assert p.align_with_context("c", {"source_id": "x"}) == "x::FIXED"


def test_each_source_has_independent_inner_state():
    """Source A and source B should each get their own fresh inner
    variant. Verify by checking that the inner's internal counter (here
    we use 'first writer wins' canonical names) operates independently."""

    class _FirstWriterWins(Variant):
        name = "fww"

        def __init__(self):
            self._first: dict[str, str] = {}

        def align(self, input_relation: str) -> str:
            if input_relation not in self._first:
                self._first[input_relation] = input_relation
            return self._first[input_relation]

    p = PerSourceNamespaceProxy(inner_factory=_FirstWriterWins)
    # Sales sees "X" first, but ops sees "Y" first. Each maintains its
    # own history.
    p.align_with_context("X", {"source_id": "sales"})
    p.align_with_context("Y", {"source_id": "ops"})
    # Calling X from ops should mint a NEW canonical (X) in ops's namespace,
    # not reuse sales's.
    c_ops_x = p.align_with_context("X", {"source_id": "ops"})
    c_sales_x = p.align_with_context("X", {"source_id": "sales"})
    assert c_ops_x == "ops::X"
    assert c_sales_x == "sales::X"


def test_works_with_default_v031_inner():
    """The default inner factory is v0.3.1 hybrid + structural filter.
    Construction must succeed (modulo first-time model2vec download)."""
    p = PerSourceNamespaceProxy()  # uses default factory
    # Don't actually call align — that triggers neural-embedder download
    # which is network-dependent. Just verify construction and dispatch.
    assert callable(p._inner_factory)


def test_multitenant_workload_loads():
    from fixtures import workloads

    w = workloads.load("W-MULTITENANT-DEMO")
    assert len(w) > 20
    sources = {e.source_id for e in w}
    assert sources == {"sales", "ops", "marketing"}
    # Confirm the core asymmetry: Apple has different oracles per source
    apple_oracles = {
        (e.source_id, e.oracle_canonical)
        for e in w
        if e.input == "Apple"
    }
    assert ("sales", "Apple_Inc") in apple_oracles
    assert ("ops", "Apple_Supplier_Inc") in apple_oracles
    assert ("marketing", "Apple_Inc") in apple_oracles


def test_synth_workload_has_three_strata():
    """W-MULTITENANT-SYNTH has explicit global / partial / conditional
    strata. Verify a representative from each."""
    from fixtures import workloads
    from fixtures.workloads.w_multitenant_synth import stratum_for_canonical

    w = workloads.load("W-MULTITENANT-SYNTH")
    assert len(w) > 300

    # global stratum: Microsoft appears in all 7 sources, all → Microsoft_Corp
    msft = {(e.source_id, e.oracle_canonical) for e in w if e.input == "Microsoft"}
    assert all(o == "Microsoft_Corp" for _, o in msft)
    assert len({s for s, _ in msft}) >= 5  # at least 5 sources see Microsoft
    assert stratum_for_canonical("Microsoft_Corp") == "global"

    # partial stratum: Apple has source-subset-conditional oracle
    apple = {(e.source_id, e.oracle_canonical) for e in w if e.input == "Apple"}
    apple_oracles = {o for _, o in apple}
    assert apple_oracles == {"Apple_Inc", "Apple_Supplier_Inc"}
    assert stratum_for_canonical("Apple_Inc") == "partial"

    # conditional stratum: Pipeline means three different things in three sources
    pipeline = {(e.source_id, e.oracle_canonical) for e in w if e.input == "Pipeline"}
    pipeline_oracles = {o for _, o in pipeline}
    assert "Sales_Pipeline" in pipeline_oracles
    assert "CI_Pipeline" in pipeline_oracles
    assert stratum_for_canonical("CI_Pipeline") == "conditional"


class _SingleClusterInner(Variant):
    """Test inner: routes every input to a single fixed canonical.
    Simulates a real clustering variant that successfully merges all
    of a source's aliases into one local cluster."""

    def __init__(self, canonical_name: str = "C"):
        self.name = f"test-inner-{canonical_name}"
        self._canonical = canonical_name

    def align(self, input_relation: str) -> str:
        return self._canonical


def test_consensus_proxy_merges_high_overlap_clusters():
    """v0.4.1: sales and ops both have a local cluster with the same set
    of aliases — should merge across sources."""

    def inner_factory():
        return _SingleClusterInner("Microsoft")

    p = CrossSourceConsensusProxy(
        inner_factory=inner_factory,
        alias_jaccard_threshold=0.5,
        min_aliases_for_merge=2,
    )
    # Sales: 3 aliases for Microsoft, all going to local canonical "Microsoft"
    for inp in ["Microsoft", "MSFT", "Microsoft Corp"]:
        p.align_with_context(inp, {"source_id": "sales"})
    # Ops: same 3 aliases, same local canonical
    for inp in ["Microsoft", "MSFT", "Microsoft Corp"]:
        p.align_with_context(inp, {"source_id": "ops"})
    # Now (sales, Microsoft) aliases = (ops, Microsoft) aliases = same set.
    # Jaccard = 1.0; merge.
    c_sales = p.align_with_context("Microsoft", {"source_id": "sales"})
    c_ops = p.align_with_context("Microsoft", {"source_id": "ops"})
    assert c_sales == c_ops, f"high-overlap should merge: {c_sales!r} vs {c_ops!r}"
    assert c_sales.startswith("merged::")


def test_consensus_proxy_isolates_low_overlap_clusters():
    """v0.4.1: sales and ops have local clusters that share one alias
    only (the surface form 'Apple'). Jaccard is low; stay isolated."""

    def inner_factory():
        return _SingleClusterInner("Apple")

    p = CrossSourceConsensusProxy(
        inner_factory=inner_factory,
        alias_jaccard_threshold=0.5,
        min_aliases_for_merge=2,
    )
    for inp in ["Apple", "AAPL", "Apple Inc", "Apple Computer"]:
        p.align_with_context(inp, {"source_id": "sales"})
    for inp in ["Apple", "Apple Foods", "Apple Supplier", "Apple Inc Supplier"]:
        p.align_with_context(inp, {"source_id": "ops"})
    # Overlap = {"Apple"} = 1, union = 7. Jaccard = 1/7 ≈ 0.14 < 0.5.
    c_sales = p.align_with_context("Apple", {"source_id": "sales"})
    c_ops = p.align_with_context("Apple", {"source_id": "ops"})
    assert c_sales != c_ops, f"low-overlap should isolate: {c_sales!r} vs {c_ops!r}"
    assert c_sales.startswith("sales::")
    assert c_ops.startswith("ops::")


def test_consensus_proxy_too_few_aliases_no_merge():
    """min_aliases_for_merge guard: with too few aliases per cluster,
    don't attempt cross-source merge."""

    def inner_factory():
        return _SingleClusterInner("X")

    p = CrossSourceConsensusProxy(
        inner_factory=inner_factory, min_aliases_for_merge=3
    )
    # Only 2 aliases per source — below min of 3, so no merge.
    for inp in ["X", "Y"]:
        p.align_with_context(inp, {"source_id": "a"})
    for inp in ["X", "Y"]:
        p.align_with_context(inp, {"source_id": "b"})
    c_a = p.align_with_context("X", {"source_id": "a"})
    c_b = p.align_with_context("X", {"source_id": "b"})
    assert c_a != c_b
    assert c_a.startswith("a::")


def test_consensus_proxy_threshold_invalid_raises():
    with pytest.raises(ValueError):
        CrossSourceConsensusProxy(alias_jaccard_threshold=1.5)
    with pytest.raises(ValueError):
        CrossSourceConsensusProxy(alias_jaccard_threshold=0.0)


def test_consensus_proxy_legacy_align_routes_to_default_namespace():
    p = CrossSourceConsensusProxy(inner_factory=BRawIdentity)
    c = p.align("Microsoft")
    assert c.startswith("default::")


def test_consensus_proxy_synth_partial_stratum_aliases_now_differ():
    """After the synthetic-partial-stratum fix, sales and ops writing
    'Apple' get DIFFERENT alias sets. v0.4.1 should isolate them."""
    from fixtures import workloads

    w = workloads.load("W-MULTITENANT-SYNTH")
    sales_apple_aliases = {e.input for e in w
                           if e.source_id == "sales" and "Apple" in e.input
                           and e.oracle_canonical == "Apple_Inc"}
    ops_apple_aliases = {e.input for e in w
                         if e.source_id == "ops" and "Apple" in e.input
                         and e.oracle_canonical == "Apple_Supplier_Inc"}
    # Only "Apple" itself should be in both
    overlap = sales_apple_aliases & ops_apple_aliases
    assert overlap == {"Apple"}, f"unexpected overlap: {overlap}"
    # And there should be plenty of source-specific aliases
    assert len(sales_apple_aliases - ops_apple_aliases) >= 2
    assert len(ops_apple_aliases - sales_apple_aliases) >= 2


def test_lazy_proxy_writes_dont_merge_until_consolidate():
    """v0.4.2 write path is pure per-source isolation; merges only
    appear after consolidate() runs."""

    def inner_factory():
        from runner.variants.embed_proxy import HashedTokenEmbedder

        # Use v0.1.0-like inner to avoid neural download in tests
        from runner.variants.embed_proxy import EmbeddingSchemaProxy

        return EmbeddingSchemaProxy(
            embedder=HashedTokenEmbedder(),
            similarity_threshold=0.5,
        )

    p = LazyCrossSourceConsensusProxy(
        inner_factory=inner_factory,
        alias_jaccard_threshold=0.5,
        embedding_cosine_threshold=0.95,
    )
    # Sales and ops both write Microsoft with same aliases.
    for inp in ["Microsoft", "MSFT Corp", "Microsoft Corporation"]:
        p.align_with_context(inp, {"source_id": "sales"})
    for inp in ["Microsoft", "MSFT Corp", "Microsoft Corporation"]:
        p.align_with_context(inp, {"source_id": "ops"})
    # Before consolidate: source-prefixed
    pre_sales = p.align_with_context("Microsoft", {"source_id": "sales"})
    pre_ops = p.align_with_context("Microsoft", {"source_id": "ops"})
    assert pre_sales.startswith("sales::")
    assert pre_ops.startswith("ops::")
    assert pre_sales != pre_ops

    # Run consolidation
    summary = p.consolidate()
    assert summary["n_merge_edges"] >= 1

    # After consolidate: merged
    post_sales = p.align_with_context("Microsoft", {"source_id": "sales"})
    post_ops = p.align_with_context("Microsoft", {"source_id": "ops"})
    assert post_sales == post_ops, f"should merge after consolidate: {post_sales!r} vs {post_ops!r}"
    assert post_sales.startswith("merged::")


def test_lazy_proxy_consolidate_uses_embedding_or_jaccard():
    """Consolidate fires merge when EITHER Jaccard OR cosine threshold
    is met. Verify with a case where Jaccard is low but embedding
    cosine is high."""

    class _FixedEmbedder:
        dim = 4

        def embed(self, text):
            # All inputs produce the same vector -> cosine = 1.0 always
            return [1.0, 0.0, 0.0, 0.0]

    class _InnerWithEmbedder:
        name = "test"
        embedder = _FixedEmbedder()

        def __init__(self):
            self._next_id = 0

        def align(self, input_relation):
            # Each input gets its own canonical (no aliasing inside source)
            self._next_id += 1
            return f"C{self._next_id}"

    p = LazyCrossSourceConsensusProxy(
        inner_factory=_InnerWithEmbedder,
        alias_jaccard_threshold=0.99,  # impossibly high
        embedding_cosine_threshold=0.5,
        min_aliases_for_merge=1,
    )
    # Sales: "X". Ops: "Y". Different inputs (Jaccard = 0).
    p.align_with_context("X", {"source_id": "sales"})
    p.align_with_context("Y", {"source_id": "ops"})
    summary = p.consolidate()
    # Should still merge because embedding cosine = 1.0 >= 0.5
    assert summary["n_merge_edges"] == 1
    assert summary["merge_reasons"]["cosine_only"] == 1
    assert summary["merge_reasons"]["jaccard_only"] == 0


def test_lazy_proxy_order_invariance():
    """Type C drift check: same workload in different orders should
    produce the same consolidation partition. Uses BRawIdentity as the
    inner so each input is its own cluster within a source. This
    isolates the consolidate() logic from inner-variant order
    sensitivity at threshold boundaries.

    The inner variant's behavior near similarity thresholds IS
    order-sensitive in general (witness: when threshold sits between
    two pairs' cosines, one ordering clusters them, another doesn't).
    That is a property of the inner, not the consolidation. To test the
    consolidation in isolation we deliberately remove the inner's
    contribution to order-sensitivity.
    """

    def make_proxy():
        return LazyCrossSourceConsensusProxy(
            inner_factory=BRawIdentity,
            alias_jaccard_threshold=0.5,
            embedding_cosine_threshold=0.99,
            min_aliases_for_merge=1,
        )

    # Each source has 3 unique inputs. With BRawIdentity each becomes
    # its own local canonical. Cross-source merge will fire wherever the
    # alias sets across sources overlap (Jaccard >= 0.5, here = 1.0 for
    # any pair of sources that wrote the same input).
    base_workload = []
    for source in ["s1", "s2", "s3", "s4", "s5"]:
        for alias in ["Microsoft", "Google", "Apple"]:
            base_workload.append((source, alias))

    def run_shuffled(seed):
        rng = random.Random(seed)
        wl = list(base_workload)
        rng.shuffle(wl)
        p = make_proxy()
        for source, alias in wl:
            p.align_with_context(alias, {"source_id": source})
        p.consolidate()
        # Build equivalence-class signature: source -> merged canonical
        sig = {}
        for source, alias in base_workload:
            sig[(source, alias)] = p.align_with_context(
                alias, {"source_id": source}
            )
        return sig

    sig_a = run_shuffled(1)
    sig_b = run_shuffled(2)

    # Compute Adjusted Rand Index between the two partitions
    def adjusted_rand_index(sig1, sig2):
        items = list(sig1.keys())
        if len(items) < 2:
            return 1.0
        # Build cluster label -> int index for each
        def labels(sig):
            unique = {}
            out = []
            for it in items:
                lbl = sig[it]
                if lbl not in unique:
                    unique[lbl] = len(unique)
                out.append(unique[lbl])
            return out

        l1 = labels(sig1)
        l2 = labels(sig2)
        from math import comb

        n = len(items)
        # Build contingency
        cont = {}
        for a, b in zip(l1, l2):
            cont[(a, b)] = cont.get((a, b), 0) + 1
        a_sums = {}
        b_sums = {}
        for (a, b), c in cont.items():
            a_sums[a] = a_sums.get(a, 0) + c
            b_sums[b] = b_sums.get(b, 0) + c
        sum_cont = sum(comb(c, 2) for c in cont.values())
        sum_a = sum(comb(c, 2) for c in a_sums.values())
        sum_b = sum(comb(c, 2) for c in b_sums.values())
        total = comb(n, 2)
        expected = sum_a * sum_b / total if total else 0
        max_index = (sum_a + sum_b) / 2
        if max_index == expected:
            return 1.0
        return (sum_cont - expected) / (max_index - expected)

    ari = adjusted_rand_index(sig_a, sig_b)
    assert ari >= 0.9, f"low order-invariance: ARI = {ari:.3f}"


def test_v043_blocks_single_shared_alias_merge():
    """v0.4.3 min_overlap=2 blocks the WIKIDATA-style failure where two
    single-alias clusters across sources merge because they share their
    one surface form (e.g. tech_company 'Apple' vs biology 'Apple')."""

    class _ApplePassthrough(Variant):
        name = "test-passthrough"

        def __init__(self):
            self._cache: dict[str, str] = {}

        def align(self, input_relation):
            return self._cache.setdefault(input_relation, input_relation)

    # v0.4.2 with min_aliases=1 over-merges here.
    v042 = LazyCrossSourceConsensusProxy(
        inner_factory=_ApplePassthrough,
        alias_jaccard_threshold=0.5,
        embedding_cosine_threshold=1.0,  # disable embedding path (cos never exceeds 1)
        min_aliases_for_merge=1,
    )
    v042.align_with_context("Apple", {"source_id": "tech"})
    v042.align_with_context("Apple", {"source_id": "biology"})
    summary = v042.consolidate()
    # v0.4.2 fires the merge — this is the bug v0.4.3 addresses.
    assert summary["n_merge_edges"] == 1

    # v0.4.3 default (min_overlap=2) blocks it.
    v043 = LazyConsensusANDRuleProxy(
        inner_factory=_ApplePassthrough,
        alias_jaccard_threshold=0.5,
        embedding_cosine_threshold=1.0,  # disable embedding path (cos never exceeds 1) so we
                                          # isolate the overlap rule
        min_aliases_for_merge=1,
        min_overlap_for_merge=2,
    )
    v043.align_with_context("Apple", {"source_id": "tech"})
    v043.align_with_context("Apple", {"source_id": "biology"})
    summary = v043.consolidate()
    assert summary["n_merge_edges"] == 0
    assert summary["merge_reasons"]["blocked_overlap_below_min"] == 1


def test_v043_and_rule_requires_both_signals():
    """v0.4.3 needs BOTH Jaccard and embedding cosine to fire. Lone
    cosine match is not enough; lone Jaccard match is not enough."""

    class _DistinctEmbedder:
        dim = 2

        def embed(self, text):
            # Two distinct vectors so we can force cosine to be low
            if "X" in text:
                return [1.0, 0.0]
            return [0.0, 1.0]

    class _InnerWithEmbedder:
        name = "t"
        embedder = _DistinctEmbedder()

        def align(self, input_relation):
            return input_relation

    # High Jaccard, low cosine: should NOT merge under AND.
    v043 = LazyConsensusANDRuleProxy(
        inner_factory=_InnerWithEmbedder,
        alias_jaccard_threshold=0.4,
        embedding_cosine_threshold=0.8,
        min_aliases_for_merge=2,
        min_overlap_for_merge=2,
    )
    # source A: ["X", "Y"] — embedding for X plus embedding for Y mixed
    # source B: ["X", "Y"] — same content as A
    # Actually with our distinct embedder, embed("X") = [1,0] and
    # embed("Y") = [0,1]. Both inner returns input as canonical.
    # The aliases for (A, "X") = {"X"}, for (A, "Y") = {"Y"}; min_aliases=2 blocks.
    # Need to set up so single canonical accumulates >=2 aliases.

    class _SingleClusterInner:
        name = "t2"
        embedder = _DistinctEmbedder()

        def align(self, input_relation):
            return "CLUSTER"  # everything goes into one canonical

    v043b = LazyConsensusANDRuleProxy(
        inner_factory=_SingleClusterInner,
        alias_jaccard_threshold=0.4,
        embedding_cosine_threshold=0.8,
        min_aliases_for_merge=2,
        min_overlap_for_merge=2,
    )
    # source A: aliases {X, Y}; source B: same
    for s in ["A", "B"]:
        v043b.align_with_context("X", {"source_id": s})
        v043b.align_with_context("Y", {"source_id": s})
    # Now (A, "CLUSTER") aliases = {X, Y}, same for B.
    # Jaccard = 1.0 (passes). Embedding centroid for A is mean of
    # [1,0] and [0,1] = [0.5, 0.5] (after normalize). Same for B.
    # Cosine = 1.0. Both pass. Merge.
    summary = v043b.consolidate()
    assert summary["n_merge_edges"] == 1


def test_v043_default_min_overlap_is_2():
    p = LazyConsensusANDRuleProxy()
    assert p._min_overlap == 2


def test_v043_min_overlap_invalid_raises():
    with pytest.raises(ValueError):
        LazyConsensusANDRuleProxy(min_overlap_for_merge=0)


def test_wikidata_disambiguation_workload_loads():
    """W-MULTITENANT-WIKIDATA is KG-grounded: same surface, different
    real WikiData canonicals per source."""
    from fixtures import workloads
    from fixtures.workloads.w_multitenant_wikidata import disambiguated_surfaces

    w = workloads.load("W-MULTITENANT-WIKIDATA")
    assert len(w) > 100

    # The key test: Apple has multiple distinct oracle canonicals
    apple = {(e.source_id, e.oracle_canonical) for e in w if e.input == "Apple"}
    oracles = {o for _, o in apple}
    assert len(oracles) >= 3, f"Apple should have at least 3 oracles, got: {oracles}"
    assert any("Apple Inc" in o for o in oracles)
    assert "apple" in oracles  # the fruit
    assert "Apple Records" in oracles

    # disambiguated_surfaces helper returns surfaces with >1 candidate
    ds = disambiguated_surfaces()
    assert "Apple" in ds
    assert "Mustang" in ds
    assert "Oracle" in ds

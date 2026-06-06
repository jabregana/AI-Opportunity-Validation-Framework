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
from runner.variants.per_source import PerSourceNamespaceProxy


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

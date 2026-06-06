"""Tests for the public service API (EntityNormalizer, AdvisoryConsolidator)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.service import EntityNormalizer, AdvisoryConsolidator


# -- EntityNormalizer ----


def test_normalizer_builds_from_variant_id():
    n = EntityNormalizer("b-raw-identity")
    assert n.variant_name == "b-raw-identity"


def test_normalizer_rejects_unknown_variant_id():
    with pytest.raises(KeyError):
        EntityNormalizer("nonexistent-variant")


def test_normalizer_normalizes_single_tenant():
    n = EntityNormalizer("b-raw-identity")
    assert n.normalize("WORKS_AT") == "WORKS_AT"


def test_normalizer_batch_normalize_returns_list():
    n = EntityNormalizer("b-raw-identity")
    out = n.batch_normalize(["A", "B", "C"])
    assert out == ["A", "B", "C"]


def test_normalizer_multi_tenant_uses_source_context():
    n = EntityNormalizer("embed-proxy-v0.4.0-per-source")
    a = n.normalize("Apple", context={"source_id": "sales"})
    b = n.normalize("Apple", context={"source_id": "ops"})
    assert a != b
    assert a.startswith("sales::")
    assert b.startswith("ops::")


def test_normalizer_supports_consolidate_flag():
    assert EntityNormalizer("b-raw-identity").supports_consolidate is False
    assert EntityNormalizer("embed-proxy-v0.4.2-lazy-consensus").supports_consolidate is True


def test_normalizer_consolidate_noop_on_eager_variants():
    n = EntityNormalizer("b-raw-identity")
    assert n.consolidate() is None


def test_normalizer_can_take_pre_built_variant():
    from runner.variants.b_raw import BRawIdentity
    n = EntityNormalizer(variant=BRawIdentity())
    assert n.normalize("X") == "X"


# -- AdvisoryConsolidator ----


def test_advisory_rejects_non_consolidatable_variant():
    n = EntityNormalizer("b-raw-identity")
    with pytest.raises(ValueError):
        AdvisoryConsolidator(n)


def test_advisory_tracks_writes_until_consolidate():
    n = EntityNormalizer("embed-proxy-v0.4.2-lazy-consensus")
    ac = AdvisoryConsolidator(n)
    assert ac.write_count_since == 0
    for _ in range(5):
        n.normalize("test", context={"source_id": "default"})
    assert ac.write_count_since == 5
    assert ac.schedule_required(min_writes=3) is True
    ac.run()
    assert ac.write_count_since == 0


def test_advisory_records_last_consolidation_summary():
    n = EntityNormalizer("embed-proxy-v0.4.2-lazy-consensus")
    ac = AdvisoryConsolidator(n)
    n.normalize("test", context={"source_id": "s1"})
    n.normalize("test", context={"source_id": "s2"})
    summary = ac.run()
    assert ac.last_consolidation is not None
    assert ac.last_consolidation == summary


def test_advisory_schedule_threshold():
    n = EntityNormalizer("embed-proxy-v0.4.2-lazy-consensus")
    ac = AdvisoryConsolidator(n)
    n.normalize("x", context={"source_id": "default"})
    assert ac.schedule_required(min_writes=2) is False
    n.normalize("y", context={"source_id": "default"})
    assert ac.schedule_required(min_writes=2) is True

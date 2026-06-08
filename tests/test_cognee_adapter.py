"""Tests for the Cognee integration adapter.

Uses a FakeCognee module-like object that mimics cognee.add /
cognify / search / delete so the adapter can be exercised without
a real Cognee install.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import (
    CogneeGCMiddleware,
    CogneeNodeRecord,
    GCIntegrationShim,
)


class FakeCognee:
    """Simulates the cognee module surface the adapter needs."""

    def __init__(self):
        self.docs: dict[str, str] = {}
        self.cognify_calls: int = 0
        self.search_calls: int = 0
        self.delete_calls: list[str] = []
        self._next = 0

    def add(self, text, dataset_name=None, **kwargs):
        self._next += 1
        cid = f"fake_doc_{self._next}"
        self.docs[cid] = text
        return cid  # real cognee returns various shapes; adapter generates own id

    async def cognify(self, datasets=None, **kwargs):
        self.cognify_calls += 1
        # Return fake entity/edge structure for the adapter to inspect
        return {
            "nodes": [
                {"id": f"ent_{i}", "name": f"entity_{i}"}
                for i in range(2)
            ],
            "edges": [
                {"source": "ent_0", "target": "ent_1"}
            ],
        }

    async def search(self, query_type, query_text, **kwargs):
        self.search_calls += 1
        # Return matched nodes
        return [{"id": "ent_0", "score": 0.95}]

    async def delete(self, doc_id):
        self.delete_calls.append(doc_id)
        return True


# ---------------- Adapter instantiation ----------------


def test_adapter_instantiates_with_fake_cognee():
    f = FakeCognee()
    mw = CogneeGCMiddleware(f)
    assert mw.cognee is f
    assert mw.contract_version == 1
    assert mw.name == "cognee-adapter"


def test_adapter_starts_with_empty_state():
    mw = CogneeGCMiddleware(FakeCognee())
    state = mw.get_state()
    assert state.nodes == {}
    assert mw.stats().n_writes == 0


# ---------------- add() interception ----------------


def test_add_records_doc_in_sidecar():
    mw = CogneeGCMiddleware(FakeCognee())
    result = mw.add("User likes coffee.", dataset_name="user_a")
    assert "doc_id" in result
    state = mw.get_state()
    assert result["doc_id"] in state.nodes


def test_add_with_dataset_name_carries_tenant():
    mw = CogneeGCMiddleware(FakeCognee())
    result = mw.add("Some preference", dataset_name="tenant_a")
    rec = mw._records[result["doc_id"]]
    assert rec.dataset_name == "tenant_a"


# ---------------- cognify() ----------------


def test_cognify_records_extracted_entities():
    mw = CogneeGCMiddleware(FakeCognee())
    mw.cognify(datasets=["user_a"])
    state = mw.get_state()
    # FakeCognee returns 2 entities + 1 edge
    assert "ent_0" in state.nodes
    assert "ent_1" in state.nodes
    assert state.in_degree.get("ent_1", 0) >= 1
    assert state.out_degree.get("ent_0", 0) >= 1


# ---------------- search() ----------------


def test_search_records_query_against_hits():
    mw = CogneeGCMiddleware(FakeCognee())
    mw.cognify()  # ensures ent_0 exists
    pre = mw.stats().n_queries
    result = mw.search("similarity", "coffee")
    assert len(result) == 1
    assert mw.stats().n_queries > pre


# ---------------- pin() ----------------


def test_pin_adds_to_pinned_set():
    mw = CogneeGCMiddleware(FakeCognee())
    r = mw.add("important", dataset_name="u1")
    doc_id = r["doc_id"]
    mw.pin(doc_id)
    state = mw.get_state()
    assert doc_id in state.pinned


def test_apply_sweep_refuses_pinned():
    mw = CogneeGCMiddleware(FakeCognee())
    r = mw.add("pinned-doc", dataset_name="u1")
    doc_id = r["doc_id"]
    mw.pin(doc_id)
    removed = mw.apply_sweep([doc_id])
    assert removed == 0


# ---------------- End-to-end sweep with v0.1.2 ----------------


def test_sweep_with_v012_collects_aged_facts():
    mw = CogneeGCMiddleware(FakeCognee())
    variant = build("gc-v0.1.2-fact-only")

    now = time.time()
    old = now - 2 * 86400
    doc_ids = []
    for i in range(3):
        r = mw.add(f"doc {i}", dataset_name="u1")
        did = r["doc_id"]
        mw._records[did].added_at = old
        mw._records[did].last_access = old
        doc_ids.append(did)

    # No edges for these docs (out_degree==0), so v0.1.2 should collect them
    n_removed = mw.sweep(variant, current_time=now)
    assert n_removed == 3
    for did in doc_ids:
        assert did not in mw._records


def test_sweep_with_v018_tenant_pin_protects():
    mw = CogneeGCMiddleware(FakeCognee())
    variant = build("gc-v0.1.8-comprehensive-tuned")

    r = mw.add("tenant pinned doc", dataset_name="tenant_a")
    doc_id = r["doc_id"]
    mw._records[doc_id].added_at = time.time() - 10 * 86400
    mw._records[doc_id].last_access = time.time() - 10 * 86400
    variant.pin_for_tenant("tenant_a", doc_id)

    state = mw.get_state()
    cands = variant.collect_candidates(state, current_time=time.time())
    assert doc_id not in cands


def test_sweep_with_v013_records_tombstones():
    mw = CogneeGCMiddleware(FakeCognee())
    variant = build("gc-v0.1.3-fact-only-tombstone")

    now = time.time()
    old = now - 2 * 86400
    r = mw.add("aged doc", dataset_name="u1")
    doc_id = r["doc_id"]
    mw._records[doc_id].added_at = old
    mw._records[doc_id].last_access = old

    n = mw.sweep(variant, current_time=now)
    assert n == 1
    assert doc_id in variant.tombstones
    assert variant.was_recently_collected(doc_id, current_time=now + 60)


# ---------------- Contract conformance ----------------


def test_adapter_is_a_gc_integration_shim():
    mw = CogneeGCMiddleware(FakeCognee())
    assert isinstance(mw, GCIntegrationShim)


def test_stats_track_full_activity():
    mw = CogneeGCMiddleware(FakeCognee())
    mw.add("doc 1", dataset_name="u1")
    mw.add("doc 2", dataset_name="u1")
    mw.cognify()  # records entities
    mw.search("topic", "preferences")
    stats = mw.stats()
    assert stats.n_writes >= 4  # 2 docs + 2 entities from cognify
    assert stats.n_queries >= 1

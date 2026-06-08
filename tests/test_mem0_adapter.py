"""Tests for the Mem0 integration adapter.

These tests use a FAKE Mem0 (a small in-memory simulator that mimics
the Mem0 v2 API surface) so the adapter can be exercised without
needing a real LLM-backed Mem0 deployment.
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
    Mem0GCMiddleware,
    Mem0MemoryRecord,
)


# ---------------- Fake Mem0 (in-memory simulator) ----------------


class FakeMem0:
    """Mimics the Mem0 v2 API surface we depend on."""

    def __init__(self):
        self._mems: dict[str, dict] = {}
        self._next_id = 0

    def _new_id(self) -> str:
        self._next_id += 1
        return f"mem_{self._next_id:06d}"

    def add(self, messages, *, user_id=None, **kwargs) -> dict:
        # Treat each call as adding a single memory. Real Mem0 may
        # split into multiple facts via LLM extraction; we keep it
        # simple here.
        text = messages if isinstance(messages, str) else str(messages)
        mid = self._new_id()
        self._mems[mid] = {
            "id": mid,
            "memory": text,
            "user_id": user_id,
        }
        return {"results": [{"id": mid, "memory": text, "event": "ADD"}]}

    def search(self, query: str, *, top_k=20, **kwargs) -> dict:
        # Naive substring search
        hits = [
            {"id": mid, "memory": m["memory"]}
            for mid, m in self._mems.items()
            if query.lower() in m["memory"].lower()
        ]
        return {"results": hits[:top_k]}

    def get(self, memory_id):
        return self._mems.get(str(memory_id))

    def get_all(self, **kwargs) -> dict:
        return {"results": list(self._mems.values())}

    def update(self, memory_id, data, **kwargs):
        if memory_id in self._mems:
            self._mems[memory_id]["memory"] = data
        return self._mems.get(memory_id)

    def delete(self, memory_id):
        return self._mems.pop(memory_id, None)


# ---------------- Adapter instantiation ----------------


def test_adapter_instantiates_with_fake_mem0():
    fake = FakeMem0()
    mw = Mem0GCMiddleware(fake)
    assert mw.memory is fake
    assert mw.contract_version == 1
    assert mw.name == "mem0-adapter"


def test_adapter_starts_with_empty_state():
    mw = Mem0GCMiddleware(FakeMem0())
    state = mw.get_state()
    assert state.nodes == {}
    assert mw.stats().n_writes == 0


# ---------------- add() interception ----------------


def test_add_records_new_memory_in_sidecar():
    mw = Mem0GCMiddleware(FakeMem0())
    result = mw.add("User likes coffee", user_id="user_1")
    assert "results" in result
    mem_id = result["results"][0]["id"]
    state = mw.get_state()
    assert mem_id in state.nodes
    assert state.nodes[mem_id]["kind"] == "fact"
    assert mw.stats().n_writes == 1


def test_add_with_user_id_carries_tenant():
    mw = Mem0GCMiddleware(FakeMem0())
    result = mw.add("Some preference", user_id="tenant_a")
    mem_id = result["results"][0]["id"]
    rec = mw._records[mem_id]
    assert rec.user_id == "tenant_a"


# ---------------- search() interception ----------------


def test_search_records_query_against_hits():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("User likes coffee", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    pre_query_count = mw._records[mem_id].query_count

    search_result = mw.search("coffee")
    assert len(search_result["results"]) == 1

    post_query_count = mw._records[mem_id].query_count
    assert post_query_count == pre_query_count + 1
    assert mw.stats().n_queries == 1


def test_search_with_no_matches_does_not_inflate_counts():
    mw = Mem0GCMiddleware(FakeMem0())
    mw.add("User likes coffee", user_id="u1")
    mw.search("xyzzy")
    assert mw.stats().n_queries == 0


# ---------------- get() / update() / delete() ----------------


def test_get_records_query():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("preference", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    pre = mw._records[mem_id].query_count
    mw.get(mem_id)
    assert mw._records[mem_id].query_count == pre + 1


def test_update_refreshes_last_access():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("preference", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    pre_access = mw._records[mem_id].last_access
    time.sleep(0.01)
    mw.update(mem_id, "new preference")
    post_access = mw._records[mem_id].last_access
    assert post_access > pre_access


def test_delete_removes_from_sidecar():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("preference", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    assert mem_id in mw._records
    mw.delete(mem_id)
    assert mem_id not in mw._records


# ---------------- pin() ----------------


def test_pin_adds_to_pinned_set():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("important", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    mw.pin(mem_id)
    state = mw.get_state()
    assert mem_id in state.pinned


def test_apply_sweep_refuses_pinned():
    mw = Mem0GCMiddleware(FakeMem0())
    add_result = mw.add("pinned-memory", user_id="u1")
    mem_id = add_result["results"][0]["id"]
    mw.pin(mem_id)
    removed = mw.apply_sweep([mem_id])
    assert removed == 0
    assert mem_id in mw._records


# ---------------- End-to-end sweep with v0.1.2 ----------------


def test_sweep_with_v012_collects_aged_facts():
    """Add some old facts, sweep with v0.1.2 (1 day min_age), verify
    that aged facts get collected."""
    fake = FakeMem0()
    mw = Mem0GCMiddleware(fake)
    variant = build("gc-v0.1.2-fact-only")

    # Add 5 memories; backdate them to 2 days ago to satisfy min_age
    now = time.time()
    old_time = now - 2 * 86400  # 2 days old
    for i in range(5):
        r = mw.add(f"old memory {i}", user_id="u1")
        mid = r["results"][0]["id"]
        # Backdate the record manually
        mw._records[mid].added_at = old_time
        mw._records[mid].last_access = old_time

    # Add 2 more fresh memories (within min_age)
    for i in range(2):
        mw.add(f"fresh memory {i}", user_id="u1")

    assert len(mw._records) == 7

    # Sweep with v0.1.2; fresh memories survive, old ones collected
    n_removed = mw.sweep(variant, current_time=now)
    assert n_removed == 5
    assert len(mw._records) == 2  # the 2 fresh
    # Sidecar matches Mem0
    assert len(fake._mems) == 2


def test_sweep_with_v018_uses_tenant_pinning():
    """v0.1.8 supports tenant pinning. Verify pinned memories survive
    sweeps even when otherwise collectible."""
    mw = Mem0GCMiddleware(FakeMem0())
    variant = build("gc-v0.1.8-comprehensive-tuned")

    # Add a memory, age it, pin via variant API
    r = mw.add("important pinned memory", user_id="tenant_a")
    mem_id = r["results"][0]["id"]
    mw._records[mem_id].added_at = time.time() - 10 * 86400
    mw._records[mem_id].last_access = time.time() - 10 * 86400

    variant.pin_for_tenant("tenant_a", mem_id)

    # Sweep: variant should NOT collect the pinned memory
    state = mw.get_state()
    candidates = variant.collect_candidates(state, current_time=time.time())
    assert mem_id not in candidates


def test_sweep_with_v013_records_tombstones():
    """v0.1.3 records tombstones for collected memories."""
    mw = Mem0GCMiddleware(FakeMem0())
    variant = build("gc-v0.1.3-fact-only-tombstone")

    # Add and age 3 memories
    now = time.time()
    old = now - 2 * 86400
    mem_ids = []
    for i in range(3):
        r = mw.add(f"memory {i}", user_id="u1")
        mid = r["results"][0]["id"]
        mw._records[mid].added_at = old
        mw._records[mid].last_access = old
        mem_ids.append(mid)

    # Sweep
    n_removed = mw.sweep(variant, current_time=now)
    assert n_removed == 3

    # All 3 should be in the variant's tombstone log
    assert len(variant.tombstones) == 3
    for mid in mem_ids:
        assert variant.was_recently_collected(mid, current_time=now + 60)


# ---------------- Contract conformance ----------------


def test_adapter_is_a_gc_integration_shim():
    from runner.dimensions.memory.lifecycle.integrations import GCIntegrationShim
    mw = Mem0GCMiddleware(FakeMem0())
    assert isinstance(mw, GCIntegrationShim)


def test_stats_track_full_activity():
    mw = Mem0GCMiddleware(FakeMem0())
    mw.add("memory 1", user_id="u1")
    mw.add("memory 2", user_id="u1")
    mw.search("memory")
    mw.pin("mem_000001")
    assert mw.stats().n_writes == 2
    assert mw.stats().n_queries >= 1
    assert mw.stats().n_pins == 1

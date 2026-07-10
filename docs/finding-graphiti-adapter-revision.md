---
type: finding
opportunity: agent memory lifecycle management
stage: 5
status: RETRACTION + REVISION
date: 2026-07-10 (fix committed 2026-06-11, commit 45f4596)
artifact: commit 45f4596; N=5 and N=30 runs described below
supersedes: finding-graphiti-f1-stage5.md (the central "v0.1.x architectural wall" claim; the observed 0% numbers were real measurements but misattributed)
---

# Graphiti adapter revision: the 0% reductions were an adapter bug, not an architectural wall

This doc closes the follow-up promised in commit `45f4596`. It retracts the central claim of [`finding-graphiti-f1-stage5.md`](finding-graphiti-f1-stage5.md) and documents what the corrected evidence shows.

This is the framework's fourth self-correction, and the first one where the framework caught its own infrastructure rather than its own statistics. The measured 0% numbers were real. The diagnosis built on top of them was wrong.

## What the original finding claimed

Three end-to-end Graphiti scenarios showed every v0.1.x variant returning 0% reduction. The finding attributed this to an architectural assumption: the `in_degree == 0` orphan-node check at the heart of every v0.1.x rule rarely triggers on Graphiti's edge-rich graph. That diagnosis spawned the v0.2.x graph-topology design.

## What actually happened

The Graphiti adapter called `graphiti.delete_episode(uuid=...)` and `graphiti.delete_node(uuid=...)`. Neither method exists on graphiti-core 0.29.2. The real API is `remove_episode(episode_uuid=...)` plus `EntityNode.delete_by_uuids(driver, [uuids])`.

Every sweep delete raised AttributeError immediately. The adapter's broad `except` swallowed the error, popped the record from `_records`, and never credited `n_removed`. The sweep reported 0 removals with 0.000s of delete wall time, run after run, with no error surfaced anywhere.

The test suite could not catch this. `FakeGraphiti` carried the same wrong method names as the adapter, so 512 tests passed for months on an API contract the real library never had.

## How it was caught

The phantom signature gave it away on close reading: uniform 0% across all variants and all scenarios, paired with 0.000s of delete time. A real N=5 smoke against Neo4j with the corrected calls deleted 13 of 14 candidate nodes in 0.954s of wall time. The variants had been producing correct collection candidates the whole time. Nothing was reaching Neo4j.

## What the corrected evidence shows

| Run | Config | Result |
|---|---|---|
| N=5 smoke | finance-aggressive, aged_fraction=0.4 | 13 of 14 candidates deleted from Neo4j, 0.954s sweep wall time |
| N=30 | finance-aggressive, aged_fraction=0.2 | 26.4% reduction; UC-GC-RETRIEVAL gate FAILS at 58.6% F1 preservation |

The N=30 gate failure has a specific cause: the workload has high cross-component entity sharing, which amplifies F1 sensitivity to reduction by roughly 1.7x. The variant behaves as designed; the aged_fraction needs to drop to about 0.1 for the gate to pass cleanly on this workload shape. That run has not been done. A `finance-aggressive-no-iso` profile (component_isolation disabled) was added during diagnosis and kept as inventory for workloads with this sharing pattern.

## What is retracted and what stands

Retracted:

- "Every v0.1.x variant returns 0% reduction on edge-rich graphs because of the `in_degree == 0` check." The 0% was the adapter. Whether v0.1.x reduces on edge-rich graphs is now an open question pending a re-run with the fixed adapter. That re-run has not happened.

Stands:

- The Mem0 numbers. The Mem0 adapter used the correct API throughout.
- The v0.2.x design rationale on its own merits. Graph-topology signals (component isolation, temporal validity, edge decay, evidence counts, supersession) are still the right vocabulary for graph-native GC. What is gone is the claim that v0.1.x is architecturally incapable on graphs.
- The three prior self-corrections. This doc adds a fourth; it does not touch the others.

## The lesson, applied

When an adapter wraps an external library, the test double's method contract must be verified against the real library, not written from memory of it. The repair pattern now in the adapter: deletion routes through `_remove_episode` / `_delete_entities` helpers with runtime detection and a fallback to the legacy names, so unit tests keep passing while the real path is exercised by smoke runs. The standing rule this creates: no Stage 3+ claim about an adapter-mediated framework counts until a real-API smoke has confirmed the adapter's write path does what it reports.

The same audit applied to the Cognee adapter found three distinct API mismatches against cognee 1.1.2 (delete signature, search query_type enum, async add). The Cognee adapter needs a structural rewrite before its benchmark numbers can be trusted. Documented in commit `753f11b`; deferred.

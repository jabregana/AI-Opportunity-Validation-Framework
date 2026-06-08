# Opportunity scan: real-time graph GC for agent memory

**Status:** Stage 1 (theoretical / landscape scan) for Niche 3, applying the framework.
**Author:** Jerome Abregana
**Background:** Niche 3 was identified but parked as a backup in the original [opportunity.md](opportunity.md) scan (June 2026). The schema alignment proxy (Niche 4) completed all four stages and the project narrative reframed around the framework as the durable asset. This doc revisits Niche 3 as a candidate second opportunity to run through the same framework.

## The question I want to answer

Can I find a lightweight, deterministic real-time graph GC architecture for agent memory that:

1. Solves a concrete problem the incumbents have not closed
2. Is structurally better than the LLM-in-the-loop or cron-job alternatives
3. Has a defensible strategic position (on-record incumbent stance to compete against)
4. Has an addressable surface wide enough to matter commercially
5. Can be demoed in days, not weeks

The same five-test bar I applied to Niche 4 in the original scan.

## The problem in concrete terms

Agent memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph) accumulate nodes and edges every time text gets ingested. Pruning is weak across the board:

- Mem0 patched explicit-delete sync (PR #4505) but that only handles `Memory.delete(memory_id)` calls. Nothing collects garbage from the write path itself.
- The community plugin `mem0-lifecycle` (later renamed `mem0-agentic-enhancement-plugin`) implements Ebbinghaus decay but is solo-maintained and not graph-store-aware.
- Graphiti exposes `remove_episode` but does not chase dangling nodes left behind.
- Cognee has manual `prune` commands. No automatic write-path collection.
- Neo4j Agent Memory leaves graph cleanup to the operator.

Over time, the graph grows. Multi-hop retrieval drags in noisy edges. Downstream LLM context fills with junk. The user perception is "the agent's memory is getting worse over time, not better." This was the original opportunity framing in the June 2026 scan and it has not changed.

The December 2025 arXiv survey (Liu et al., 47 authors, arXiv 2512.13564) listed "memory automation" as the top open research frontier in its enumeration. The problem is recognized, the slot is open, and the incumbents are not closing it.

## Survey of GC techniques I can borrow from

Garbage collection has 60+ years of academic and production engineering behind it. Most of the hard problems have well-understood solutions. Here is the menu, with each technique's translation to agent memory.

### Java-style GC techniques

**1. Reference counting (CPython, Swift ARC, Objective-C, COM)**
- Each node tracks how many references point to it. When the count hits 0, collect.
- Pros: deterministic, O(1) per increment/decrement, no stop-the-world.
- Cons: cycles leak; need a separate cycle collector.
- Translation: graph stores already maintain edge counts. A middleware layer can watch for incoming-edge count drops to 0 and collect orphaned nodes immediately on the write path. Cycles in agent memory are rare in practice (entity nodes link to fact nodes, not back).

**2. Generational GC (HotSpot, V8, .NET, Go)**
- Most objects die young. Allocate into a "young generation," promote survivors to "old generation," GC the young gen frequently and the old gen rarely.
- Pros: dramatically lower amortized cost.
- Cons: needs write barriers to track cross-generation references.
- Translation: most agent memory IS short-lived (chat turn context, ephemeral facts). A small fraction is persistent (user preferences, key decisions, learned patterns). Two-tier memory with explicit promotion rules maps directly.

**3. Mark-and-sweep with tri-color marking (classic, used in Go, modern collectors)**
- Walk from roots, mark reachable, sweep unmarked. Tri-color (white/grey/black) makes it incremental.
- Pros: handles cycles, well-understood.
- Cons: O(N) walk; can be slow at scale without concurrency.
- Translation: in agent memory, roots are active session IDs + recent query results. Mark from there, sweep unmarked nodes after a grace period. Tri-color allows incremental walks without stopping writes.

**4. Region-based / G1 collector (Oracle G1, OpenJDK ZGC)**
- Divide the heap into regions. Collect regions with the most garbage first.
- Pros: predictable pause times, scales to terabyte heaps.
- Cons: implementation complexity.
- Translation: regions in agent memory could be per-user, per-time-window, or per-topic. Collect the regions where utility-per-byte is lowest. Naturally maps to multi-tenant deployments.

**5. Concurrent / pauseless GC (ZGC, Shenandoah, Azul C4)**
- Mark and compact while the application keeps running. Sub-millisecond pauses.
- Pros: no application stalls.
- Cons: requires read barriers (ZGC uses colored pointers; complex implementation).
- Translation: agent memory cannot tolerate write-path stalls during compaction. Any production-grade GC for this space needs to be concurrent by default.

### More current architectures

**6. Rust ownership / borrow checker**
- Static lifetime analysis at compile time. No runtime GC.
- Pros: zero runtime overhead, no pause times.
- Cons: requires the application to express ownership explicitly. Hard to apply to a dynamic graph at runtime.
- Translation: the IDEA translates even if the mechanism does not. Express memory ownership explicitly. "This fact belongs to this session and dies when the session ends, unless explicitly promoted." See BEAM below for a runtime version of this idea.

**7. BEAM (Erlang/Elixir) per-process heaps**
- Each lightweight process has its own heap. When the process dies, the heap dies with it. No GC across processes; the actor model isolates state.
- Pros: zero GC cost for ephemeral computations. Memory lifetime is process lifetime.
- Cons: requires the application to be structured around isolated processes.
- Translation: **this is the strongest architectural fit for agent memory.** Each conversation, each session, each user query naturally has a finite lifetime. Allocate ephemeral memory into a per-session "process heap." When the session ends, the heap is reclaimed. No GC needed for ephemeral content. Only promoted memory survives.

**8. Region inference (ML, MLton, Cyclone)**
- Allocate objects into regions tied to lexical scope. Deallocate the region when the scope exits.
- Pros: predictable, fast, no GC pauses.
- Cons: requires program structure that maps to regions.
- Translation: same idea as BEAM but at a finer granularity. Could apply per-query (each retrieval is a transient region) or per-conversation.

**9. Tracing GC with epochs (modern databases, ZGC's colored pointers)**
- Tag each allocation with an epoch number. Periodically advance the epoch. Reclaim epochs not referenced by recent operations.
- Pros: time-window-based collection, no per-node bookkeeping.
- Cons: needs an epoch-advancement protocol.
- Translation: time-bucket agent memories (daily/weekly epochs). If no recent query touched an epoch, collect it. Maps cleanly to "facts the user has not referenced in 90 days are probably stale."

**10. Utility-score-driven collection (cache eviction, PathRAG, HippoRAG)**
- Each item has a utility score combining recency, frequency, and explicit weight. Collect items below threshold.
- Pros: explicit and tunable.
- Cons: requires score maintenance on every access.
- Translation: existing retrieval-time pruners (PathRAG, HippoRAG) already do this at READ time. The wedge is moving it to WRITE time so the graph never bloats in the first place.

**11. CRDT-style lifecycle tags (modern distributed databases)**
- Mark items with logical-clock tombstones. Eventually consistent reclamation.
- Pros: works across distributed multi-tenant deployments.
- Cons: requires logical clock infrastructure.
- Translation: useful for federated agent memory (multi-region, multi-tenant) but overkill for single-instance deployments.

## What's already taken in the agent memory space

To confirm the wedge is still open, here is what each incumbent has shipped:

| Approach | Mem0 | Graphiti | Cognee | Neo4j AM | Memgraph |
|---|---|---|---|---|---|
| Explicit delete sync | yes (PR #4505) | yes | yes | manual | manual |
| Reference-counted write-path GC | no | no | no | no | no |
| Generational two-tier memory | no | no | no | no | no |
| Session-scoped allocation | no | partial (via `remove_episode`) | no | no | no |
| Epoch-based time bucket GC | no | no | no | no | no |
| Utility-score write-path collection | no | no | no | no | no |

The only thing shipped across the board is "delete what the user explicitly asked to delete." Everything else is open.

## Three candidate wedges, ranked

After mapping the GC techniques to agent memory, three approaches are differentiated, lightweight, and feasible as middleware:

### Wedge A: Reference-counted write-path GC middleware

**Premise.** A proxy in front of the graph store. On every write, increment the in-degree of the target node and decrement on every edge removal. When in-degree hits 0 AND the node has not been accessed in N days, collect immediately.

**Why it works.** Graph stores already track edge counts. The middleware just acts on count=0 instead of waiting for a manual prune. O(1) per write, no scan needed.

**Why it's defensible.** Same "deterministic, no LLM in hot path" thesis as the schema alignment proxy. Sits in front of Mem0/Graphiti/Cognee without modifying them. Mem0 maintainer's stated stance on issue #4896 ("contradictions handled by the LLM, not by an UPDATE path") suggests they would not build this either.

**Demo path.** Build the in-degree counter on top of an existing store (Neo4j or Kuzu). Show graph size before and after on a synthetic workload with churn. Should be demoable in days.

**Risk.** Cycle leak. Need a separate cycle collector or accept cycles as permanent. In practice agent memory has few cycles (entity nodes point to fact nodes, not back to entities). Acceptable risk.

### Wedge B: Generational two-tier memory (working + long-term)

**Premise.** Two tiers. Working memory is short-lived, TTL-bounded (e.g., 7 days). Long-term memory is persistent. New memories go into working tier. Promotion to long-term happens on three signals: explicit user pin, repeat reference (memory queried 3+ times in the TTL window), or LLM-tagged importance.

**Why it works.** Most agent memory IS short-lived. Treating it that way amortizes cost. Promotion logic is simple and inspectable.

**Why it's defensible.** No incumbent has shipped two-tier memory. The promotion logic itself is the value (and could be vertical-specific, like the alias maps in the schema alignment case study). Inspired by Java young-gen / old-gen but adapted for natural agent usage patterns.

**Demo path.** Build a wrapper that classifies new writes into working vs long-term, applies TTL to working, and runs promotion logic on each access. Show that a 90-day chat history has 10x fewer memories under this scheme vs flat-store baseline.

**Risk.** Wrong promotion threshold loses important memories. Tunable but needs careful per-vertical defaults.

### Wedge C: Session-scoped memory regions (BEAM-inspired)

**Premise.** Each conversation (or session, or user task) gets its own allocation region. Memories written during the session live in that region. When the session ends, the region is reclaimed UNLESS specific memories are explicitly promoted to a persistent global store.

**Why it works.** Maps to how production AI assistants actually work. Most chat content IS ephemeral. Explicit promotion is already a UX pattern (the "remember this" button in Claude, ChatGPT memory features). This formalizes the architecture around what users already do.

**Why it's defensible.** No incumbent has session-scoped memory regions as a primitive. Mem0/Graphiti store everything globally per user_id. This is a different architectural shape that they cannot trivially add without breaking existing APIs.

**Demo path.** Build a `SessionMemoryRegion` primitive that wraps Mem0. Show that ephemeral chat memories die with the session, while explicitly-promoted ones persist. The before/after metric: a user's persistent-memory store is 10-100x smaller and 10x more queryable.

**Risk.** Requires the integrator to think about promotion. Higher integration effort than the proxy approach. May be too architectural a change to drop in without buy-in from the agent framework team.

## My pick: Wedge A, with Wedge B as a near-term extension

Wedge A (reference-counted write-path GC) is the closest analog to the schema alignment proxy:
- Same architectural shape (deterministic middleware in front of the graph store)
- Same "no LLM in hot path" thesis
- Same demonstrable before/after metric (graph size, retrieval F1)
- Same potential moat structure (curated vertical rulesets layered on the proxy)

Wedge B (generational two-tier) is a natural extension once Wedge A ships. The promotion logic is where the vertical alias map equivalent lives.

Wedge C is the most ambitious but also the highest integration cost. Best pursued after one or two paying customers exist for Wedge A or B.

## Why this is the right next opportunity for the framework

Three reasons:

**1. The framework will work.** The four-stage progression (theoretical, synthetic, real, substantial real) is the right shape for graph GC too. Synthetic workloads can be generated (random graph + churn pattern). Real workloads exist (ingest Mem0 demo data, measure store growth). Substantial real workloads can scale up.

**2. The harness transfers directly.** The statistical gates, multi-model ladder, integration shim pattern, and finding-doc culture all carry over. No new infrastructure needed.

**3. The story changes if Wedge A works.** A reference-counted write-path GC middleware would be the second case study tested through the framework. Two case studies establish a pattern. The framework's reusability claim goes from "I did it once" to "I did it twice in two different problem spaces."

## What stage 2 would build

If pursuing Wedge A:

1. **Variant abstraction.** Define a `GCVariant` ABC similar to the `Variant` ABC in the schema alignment proxy. Methods: `on_write(edge)`, `on_remove(edge)`, `should_collect(node, current_time)`, `collect(node)`.

2. **Pilot variants.** Build three to start:
   - `b-raw-no-gc`: identity baseline, no collection ever
   - `gc-v0.1.0-ref-count`: simple reference counting, collect when in-degree=0 and node-age > 7 days
   - `gc-v0.1.1-ref-count-with-utility`: reference counting plus utility score; collect when in-degree=0 OR utility < threshold

3. **Synthetic workloads.** Generate random graphs with controlled churn patterns. Measure: store size over time, retrieval F1 (does GC hurt or help retrieval quality), false-collection rate (Tier B: nodes that should NOT have been collected).

4. **Statistical gates.** UC-equivalents:
   - UC-GC-1: store-size reduction (higher is better)
   - UC-GC-2: retrieval F1 preservation (must not regress vs no-GC baseline)
   - UC-GC-3: false-collection rate (must stay below 1%)
   - UC-GC-4: write-path latency (must stay under 10ms p99)

5. **Finding docs per iteration.** Same culture as the schema alignment proxy.

Expected stage 2 duration: 1-2 weeks. If the synthetic workload shows promising store-size reduction without retrieval degradation, proceed to stage 3 (real Mem0 data).

## Open questions

1. **Cycle handling.** Reference counting leaks cycles. Do real agent memory graphs have cycles? Need to measure on a real Mem0 store before committing to pure ref-counting.

2. **Access tracking overhead.** Recording every access (for "node not accessed in N days") has its own cost. Is the bookkeeping cheap enough to put in the write path?

3. **Multi-tenant coordination.** If two tenants share a global canonical store (like the schema alignment proxy supports), how does GC coordinate across tenants? Probably the same per-source isolation pattern from v0.4.x.

4. **Operator override.** Production teams need to override automatic collection. What's the right API for "do not collect this node, ever"?

These are stage 2 questions, not stage 1 blockers.

## What it would take to start

1. Read the current state of each incumbent's prune / delete behavior to confirm the wedge is still open (about 2 hours).
2. Build the synthetic graph + churn workload generator (about 1 day).
3. Define the `GCVariant` ABC and the three pilot variants (about 1 day).
4. Wire the statistical harness for the four UC gates (about 1 day, mostly reusing the existing harness).
5. Run the first synthetic benchmark and write the first finding doc (about 1 day).

Total: about 4-5 days to a working stage 2 baseline. If those numbers look good, proceed.

## Pointers

- Original landscape scan: [`opportunity.md`](opportunity.md)
- Framework meta-narrative: [`../FRAMEWORK.md`](../FRAMEWORK.md)
- Roadmap: [`roadmap.md`](roadmap.md) (this would be item 6, "second opportunity")
- The first case study that proved the framework worked: schema alignment proxy. See [`../CASE-STUDY.md`](../CASE-STUDY.md).

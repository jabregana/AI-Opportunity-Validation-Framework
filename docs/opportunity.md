# Opportunity Analysis

**Status:** Stage 1 artifact (theoretical / landscape scan). Preserved as written for the historical record. See the postscript at the bottom for what stages 2-4 found about the picked wedge.

This repo addresses one slot in the agent-memory infrastructure stack. This document records why that slot, why now, and what was ruled out.

## The shared weakness in production memory graphs

Five production-grade frameworks dominate the space as of mid-2026: Mem0, Graphiti (by Zep), Cognee, Neo4j Agent Memory, and Memgraph. They share five structural weaknesses, all visible in their public issues and documentation:

1. Fragmented extraction. Each system extracts nodes and edges via isolated chunk-by-chunk LLM calls with no persistent global memory state. The resulting graph is structurally fragmented and logically inconsistent across documents.

2. Graph explosion. Pruning is weak. Graphs grow exponentially. Multi-hop retrieval drags in noisy edges, overwhelming the downstream LLM context.

3. Ontology rigidity versus semantic drift. Fixed schemas cannot evolve into new domains. Schema-less mode hallucinates dozens of near-duplicate relations (`WORKS_AT`, `EMPLOYED_BY`, `JOB_AT`), shattering structural integrity.

4. Cold extraction tax. Every memory update pays a heavy upfront LLM-extraction cost. Real-time streaming updates are prohibitively slow and expensive.

5. No native reasoning memory. The graphs store facts and timelines but not decision traces (which tools were called, which alternatives were rejected, how human feedback changed the plan).

Of these, weaknesses 2, 3, and 5 are the ones a new proxy or middleware layer can address without rebuilding a graph backend.

## The four candidate niches

A 90-day scan in early June 2026 evaluated four candidate wedges against current incumbent activity. The results below are the headline findings; raw cited evidence lives in the project notes alongside this repo.

### Niche 1. Deterministic LSP code memory graph

Premise: an ultra-fast LSP-based memory graph for code that uses Language Server Protocol AST signals deterministically, reserving LLMs only for human-intent mapping. Targets IDE agents (Cursor, Windsurf, Claude Code).

Verdict: closed. The `Jakedismo/codegraph-rust` project (786 GitHub stars at time of evaluation) ships the exact pipeline described in the wedge framing. AST plus LSP resolution plus a graph plus embeddings, exposed via MCP to Cursor, Claude Code, Codex, and Gemini CLI. Cognee committed to a different direction (tree-sitter plus an opaque-blob LLM strategy) in the November 2025 Universal CodeGraph PRD, confirming the LSP slot will not be filled from that direction either. The technical wedge is occupied.

### Niche 2. Reasoning memory as embedded event sourcing

Premise: a lightweight, embedded (SQLite or DuckDB) immutable event-sourcing layer for agent decision traces, with replay, audit, and self-optimize. Not a heavy graph DB.

Verdict: partially closed. Neo4j Agent Memory shipped eight PyPI releases between March and May 2026 (0.0.5 to 0.5.0) implementing a named Reasoning Memory layer with `:TOUCHED` audit edges and `TraceOutcome` indexable audits. The capability is now occupied by a well-resourced incumbent. The form-factor wedge survives (Neo4j requires a 5.20+ install, with no SQLite or DuckDB alternative documented) but it is a narrower bet on deploy ergonomics than on a missing capability.

### Niche 3. Real-time graph garbage collector

Premise: middleware in front of Neo4j, Memgraph, or Graphiti that prunes graph nodes and edges in real time using reference counts and utility scores, modeled on traditional memory managers (JVM, Go GC). Not retrieval-time filtering and not asynchronous cron.

Verdict: still open. Mem0's delete-sync hole was patched via PR #4505, but the scope is explicit `Memory.delete(memory_id)` calls only, across Neo4j, Memgraph, Kuzu, Neptune, and Apache AGE. This is delete-sync, not GC. No reference-counted write-path collector has shipped. A community lifecycle plugin (`mem0-lifecycle`, later renamed `mem0-agentic-enhancement-plugin`) implements Ebbinghaus decay as a bridge layer but is solo-maintained and not graph-store-aware. The December 2025 47-author memory survey (arXiv 2512.13564) lists "memory automation" first in its enumeration of open research frontiers.

### Niche 4. Dynamic schema alignment proxy

Premise: a proxy in front of any property-graph store that intercepts new relation writes (`EMPLOYED_BY`), vector-matches them against existing properties (`WORKS_AT`), and auto-aliases before the write hits the database. No LLM in the hot path, no rigid hand-coded schema.

Verdict: still open and the strongest signal of all four niches. Five reasons this is the best opportunity:

**1. The pain is concrete and quantifiable.** When agent memory frameworks ingest text, the LLM extracts entities and writes them as graph nodes. Same entity, different surface form (AAPL vs Apple Inc vs Apple Computer), means three separate nodes. A query for "Apple Inc" finds one of three. Downstream retrieval F1 degrades. The user's perception is "the assistant forgets what I told it." We measured this directly in our live Mem0 deployment test: without canonicalization, 0 of 5 memories about Alphabet matched a query for "Alphabet Inc." With canonicalization, 3 of 5 matched. Same store, same memories, different retrieval result.

**2. The current incumbent fix is structurally bad.** All five memory frameworks handle this with an LLM call inside the write path. Per-call cost ranges from $0.005 (gpt-4o) to $0.05 (Opus). Per-call latency is 500 to 2000 ms. Output is non-deterministic. Audit teams cannot inspect why a specific canonical was chosen. A workload of 1 million entity writes per month costs $5,000 to $50,000 in normalization LLM calls alone. At enterprise scale this becomes a major line item.

**3. A deterministic alternative is structurally better on every axis.** Sit in front of the memory framework. Match incoming surface forms against existing canonicals via regex (for known aliases) or embedding cosine (for new ones). Substitute the canonical before the write commits. Cost drops to roughly $0 (microseconds of regex). Latency drops to about 30 ms p99. Output is deterministic and reproducible. The integrator controls the alias rules, not the LLM. No new infrastructure, just middleware in front of the existing graph store.

**4. The strategic position is durable.** Mem0 deduplication is MD5-hash-only (exact byte-for-byte). Mem0 SDK v2.0.0 (Python) and v3.0.0 (TypeScript) shipped April 14, 2026 with hybrid retrieval and entity linking, but the entity linking is proper-noun boosting for retrieval ranking, not relation normalization at write time. Same release explicitly removed graph memory from the OSS distribution. Maintainer kartik-mem0 confirmed on issue #4896 (April 21, 2026): "our v3 SDK handles contradictions by design through the extraction prompt and memory linking, not through an explicit UPDATE/conflict resolution code path." PR #4911 (a contributor's attempt to add deterministic UPDATE-side conflict resolution) was rejected as off-design.

That is not a roadmap gap to be filled next quarter. It is a design philosophy commitment. An alternative architecture cannot be trivially absorbed by Mem0 because Mem0 has publicly committed to the opposite design. The same logic applies to Graphiti, Cognee, and Neo4j Agent Memory.

**5. The addressable surface is wide.** Every memory framework user is a potential customer. Every per-tenant deployment (the dominant B2B SaaS / agent platform pattern) benefits directly. Vertical markets (fintech, pharma, legal, customer support) where entity normalization is high-volume and the curated alias map matters add up to a real business. The proxy itself is ~50 lines of regex (low moat), but the curated vertical alias maps as a data subscription are defensible (high moat). Same playbook as Datadog/Sentry: open-source the engine, sell the data and the service.

## Why Niche 4 and not Niche 3

Both 3 and 4 sit in the proxy/middleware layer. The capability layer (graph backends, retrieval, reasoning traces) is where every major framework is shipping fast. Capability layers have incumbents now. Middleware layers do not. The choice between 3 and 4 came down to four things:

**Signal strength.** Niche 4 has the strongest possible signal: a public, on-record maintainer rejection of the architecture an alternative product would compete on. Niche 3's signal is weaker. The arXiv survey legitimizes the problem framing, but Mem0 is creeping in via delete-sync patches.

**Problem clarity.** Niche 4's problem (fragmented entity nodes hurting retrieval) is concrete, measurable, and visible to any user of the memory framework. Niche 3's problem (graph bloat over time) is real but takes weeks or months to manifest in a way the user notices.

**Time to demo.** A schema alignment proxy can be demoed in days: ingest text, query before and after, show the canonical reduction. A graph GC needs a long-running workload to show meaningful before/after.

**Operational definition.** "Real-time graph GC" actually splits into three distinct products: write-path inline collection, post-task batch compaction, and background reference-counted decay. Each has different design constraints. The wedge needs sharpening before it can be built. Schema alignment has one clear product shape.

Niche 3 stays as a backup. If the Niche 4 prototype hit a structural wall, Niche 3 was the next move. It did not, so Niche 3 stays parked.

## Niche 1 and Niche 2: what disqualified them

Niche 1 was disqualified by direct competition with a working product that has both the architecture and the integration surface the wedge proposed. Whether `codegraph-rust` keeps actively shipping is a separate question, but the niche is no longer empty.

Niche 2 was disqualified as a capability play but stays alive as a form-factor play. If the pursuit thesis becomes "embedded over server" for memory infrastructure broadly, then a SQLite-backed reasoning-memory primitive becomes the wedge of a different bet. That is a strategy decision, not a memory-graph one, and it is parked until the broader thesis firms up.

## Cross-cutting observations

Three other observations shaped the bet:

- Incumbents are choosing LLM-in-the-loop architectures as a deliberate design stance, not a stopgap. Mem0 v3's maintainer rejection of UPDATE-side conflict resolution is explicit on this. That is a durable opening for a deterministic, non-LLM-in-hot-path proxy.

- MCP is the standard agent integration surface now. `codegraph-rust` ships MCP tools first-class. Any memory-graph proxy product should expose MCP from day one.

- Tree-sitter has won the structural extraction battle for code in the open-source memory ecosystem. LSP remains a higher-fidelity but heavier option. This is what makes Cognee's tree-sitter stance defensible and what makes the LSP wedge narrow rather than wide. It is also unrelated to Niche 4.

## What this repo builds

The repo holds the test workloads, statistical framework, and CI gates that any candidate proxy must pass before it is taken seriously. The harness exists first so that the first real proxy attempt has nothing to argue with on methodology. See [experiments.md](experiments.md).

## Postscript (added 2026-06-07): what the framework found about Niche 4

This document was written at stage 1 of the four-stage evaluation framework. Since then, stages 2 through 4 ran end-to-end on the schema-alignment proxy. Here is the honest summary of what they found.

### Niche 4 is real but narrower than this document framed

The original framing was "deterministic, no-LLM-in-hot-path schema-alignment proxy that out-competes Mem0's LLM-in-extraction-prompt approach on agent memory graphs." That framing was too broad. After all four stages:

- **What survived.** The slot exists. The proxy delivers statistically significant accuracy lift across 14 LLMs from 5 providers. A free local 7B model with proxy ties frontier APIs (gpt-4o) at fraction of the cost on entity-extraction workloads.
- **What was narrowed.** "Agent memory" was the wrong scope. The proxy works specifically on entity normalization where entities appear under multiple alias surface forms in property-graph stores or LLM extraction pipelines. It does NOT generalize to long-form conversational memory (LongMemEval regression), singleton-heavy workloads (Stack Overflow tags), or general agent reasoning.
- **What was retracted.** The small-benchmark "free local 3B beats every frontier" headline collapsed at substantial N (836 tweets, 125 entities) to "free local 7B ties frontier at fraction of cost." Smaller models drop more at scale because they have less world knowledge for long-tail entities.

### What this means for the original landscape scan

The other three niches in this document still bear scrutiny:

- **Niche 1 (LSP code memory).** Still closed by `Jakedismo/codegraph-rust` per the original verification.
- **Niche 2 (reasoning memory).** Neo4j Agent Memory has continued shipping. The form-factor wedge (embedded SQLite or DuckDB) remains uncontested but narrower than originally framed.
- **Niche 3 (real-time graph GC).** Still open as of late June 2026, to our knowledge. If the framework is applied to a second opportunity, this is a candidate.

### The framework's value

Whatever the final commercial outcome of the proxy, the framework that evaluated it is reusable. The harness, statistical gates, four-stage progression, multi-model ladder runner, and finding-doc culture all carry forward to the next AI/ML/LLM opportunity. See [`../FRAMEWORK.md`](../FRAMEWORK.md) for the meta-narrative.

### Where to read next

- [`../FRAMEWORK.md`](../FRAMEWORK.md). The framework meta-narrative.
- [`finding-substantial-N-revision.md`](finding-substantial-N-revision.md). The headline correction at substantial N.
- [`finding-full-ladder-sweep.md`](finding-full-ladder-sweep.md). The original 14-model ladder (small N).
- [`../GAPS-AND-LIMITATIONS.md`](../GAPS-AND-LIMITATIONS.md). What's closed, what remains.
- [`roadmap.md`](roadmap.md). What's next, with Path A (proxy as product) vs Path B (framework as asset) split.

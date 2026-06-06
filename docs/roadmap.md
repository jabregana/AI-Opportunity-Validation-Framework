# Roadmap

What is planned beyond the current state.

## v0.4.0+: Source-attributed resolution (multi-tenant)

**The problem.** A team of N people shares one agent. "Apple" from the sales team is authoritatively Apple Inc; "Apple" from the ops team could be Apple Inc, Apple Supplier Ltd, or the fruit. The current proxy treats every input as global and context-free, so it cannot tell sales "Apple" apart from ops "Apple".

This is a real and important capability gap. Production agent memory in shared-knowledge settings (customer-support bots, internal knowledge agents, team-shared assistants) looks exactly like this. Mem0's design punts to "use a different user_id per user," which works for isolated personalization but not for shared graphs where the same surface form has source-conditional truth.

**The architectural extension.** Five layers change:

| Layer | Current | Multi-tenant target |
|---|---|---|
| Workload tuple | `(input, oracle_canonical)` | `(source_id, context, input, oracle_canonical_per_source)` |
| Variant interface | `align(input: str) -> canonical: str` | `align(input: str, context: dict = {}) -> canonical: str` |
| Canonical store | Global, single namespace | Per-tenant namespace OR shared store with disambiguation |
| Oracle | One canonical per input | Source-conditional canonical; ambiguity-aware (multiple acceptable canonicals when context is insufficient) |
| Metrics | F1 over a flat clustering | Adds intra-tenant consistency, cross-tenant divergence, ambiguity-handling rate |

**Backward compatibility.** Designed right, this is additive. The workload tuple grows but the loader can default `source_id="global"` and `context={}` for existing fixtures. The variant interface gains an optional `context` parameter that existing variants ignore. v0.4.0 is the first variant that actually consumes the context.

**Workload needed.** No public "agent memory with team attribution" dataset exists. We will need to synthesize one, probably by taking an existing knowledge-graph dataset (Wikidata entities) and constructing scenarios where the same surface form has different correct resolutions per team. The Tier B generator can then mine cross-team adversarials (same surface, different oracle per source).

**Sequencing.** This lands after the current single-tenant track produces a variant that meets the §7 Beta bar across UC-4.1, UC-4.4, UC-4.6, and UC-4.7. Smuggling multi-tenant into the single-tenant track now would couple two changes and complicate evaluation. The right milestone is "single-tenant Beta first, then v0.4.0 multi-tenant on the same harness."

## Other open work (smaller)

- **UC-4.7 Downstream Retrieval Preservation runner.** Spec exists, no runner yet. Lower urgency than multi-tenant because the current Tier B already catches the worst over-clustering damage.
- **Always-valid CIs (§5.5).** Needed for sequential within-test peeking. At current sample sizes the fixed-N bootstrap is fine; this matters once the gauntlet runs on hundreds of pairs per night and we want to stop early.
- **SAFFRON ledger.** Currently only the recommendation gate exists. Needed once the rolling-30d null proportion approaches 0.7.
- **Niche 3 (Real-Time Graph GC).** Backup wedge. Stays parked until the Niche 4 proxy passes Beta or hits a structural wall.
- **Pre-registration log at `runs/registry.md`.** Process hygiene. Required before any external claim.

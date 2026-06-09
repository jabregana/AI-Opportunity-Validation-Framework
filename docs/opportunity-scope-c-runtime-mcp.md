---
type: opportunity
stage: 1
date: 2026-06-09
status: DESIGNED-GATED-ON-V0.2.X
opportunity_id: opp-003-scope-c
parent: Agent Memory Lifecycle Management product (Opportunity 2)
prerequisites: v0.2.x build complete (see docs/opportunity-v0.2.x-graph-topology-gc.md)
---

# Opportunity 3 (Scope C): Runtime control plane MCP for memory-lifecycle decisions

## Wedge summary

Today, every memory-GC system runs on **static configuration**. The customer reads the runbook ("sweep every 4 hours"), wires up cron, monitors gates, and rolls back manually if a gate fails. The decision logic lives in PDFs and human heads, not in the runtime.

The wedge: expose the framework's variant-selection + sweep-decision + impact-projection logic as an **MCP server** so an agent at runtime can query it dynamically. The agent doing memory operations queries the MCP and gets adaptive answers based on current load, workload shape, and the framework's profile system (the configurability v0.2.x introduces).

This turns the framework from an evaluation tool into a **runtime decision service**. New positioning in the agent-memory tooling space.

## Is this already shipped?

Landscape check as of 2026-06-09:

| Project | What they ship | Runtime decision service for memory GC? |
|---|---|---|
| **Mem0 MCP server** (community) | Wraps Mem0's add / search / get / update / delete as MCP tools | NO. The MCP server exposes the storage operations; no decision tools (sweep cadence, variant selection, impact projection). Agents can READ/WRITE memory through MCP but cannot ASK the system "should I sweep now?" |
| **Memgraph MCP** (emerging) | Cypher query execution + schema introspection | NO. Database-shape tools only; no GC policy logic. |
| **Neo4j MCP** (community) | Cypher + graph algorithms exposure | NO. Same shape as Memgraph MCP. |
| **LangSmith MCP** | Trace recording + observability | NO. Read-only observability; no decision tools. |
| **Phoenix MCP** | Same shape as LangSmith | NO. |
| **Graphiti MCP** | Unverified (Stage 1 task to check) | Probably NO. Graphiti is at the data-model layer, not the operational-policy layer. |

**Conclusion: the wedge is open.** No incumbent ships memory-GC decision-making as a runtime service. The closest competitors expose storage operations (Mem0 MCP) or read-only observability (LangSmith / Phoenix); none expose policy decisions.

## The five candidate tools

These are the tools the MCP server exposes. Each is a stateless function call from the agent's perspective; the server computes the answer using the framework's existing decision logic.

```python
# Tool 1: dynamic sweep decision
should_sweep_now(
    deployment_id: str,
    current_metrics: {
        n_writes_since_last_sweep: int,
        hours_since_last_sweep: float,
        recent_query_volume: int,
        current_store_size: int,
    },
) -> {
    decision: "sweep" | "wait",
    reason: str,
    projected_f1_impact_pct: float,
    recommended_min_age_seconds_override: int | None,
}

# Tool 2: adaptive cadence recommendation
recommend_sweep_cadence(
    deployment_metrics: {
        hourly_write_rate_p50: float,
        hourly_write_rate_p99: float,
        current_store_size: int,
        target_max_store_size: int,
    },
    workload_pattern: "steady-state" | "bursty" | "supersession-heavy" | ...,
) -> {
    recommended_hours_between_sweeps: float,
    reasoning: str,
    confidence: float,
}

# Tool 3: profile-driven variant selection
which_variant_for(
    domain: "general" | "finance" | "clinical" | "conversations" | "local-model",
    downstream_framework: "mem0" | "graphiti" | "cognee",
    llm_class: "frontier" | "local-7b-class" | "local-32b-class",
    setup: "single-tenant" | "multi-tenant-saas" | "enterprise-batch",
) -> {
    variant_id: str,
    config: dict,
    profile_yaml_url: str,
}

# Tool 4: closed-loop collection guardrail
evaluate_proposed_collection(
    deployment_id: str,
    node_ids_to_collect: list[str],
) -> {
    projected_f1_drop_pct: float,
    projected_reduction_pct: float,
    projected_storage_savings_usd_month: float,
    recommendation: "proceed" | "defer" | "abort",
    reason: str,
}

# Tool 5: health monitoring
monitor_health(
    deployment_id: str,
    lookback_hours: int = 24,
) -> {
    recent_gate_verdicts: dict[uc_gate_id, "PASS" | "FAIL" | "NA"],
    f1_preservation_trend: list[float],
    reduction_trend: list[float],
    incident_signals: list[str],
    recommended_actions: list[str],
}
```

## State management: stateless v1, stateful v2

**v1 (stateless)**: every tool call includes all the context the tool needs. The MCP server is pure functions. The agent (or the customer's monitoring system) holds deployment history and passes it in. No database, no auth complexity.

**v2 (stateful)**: the MCP server tracks deployment IDs, their sweep history, recent gate verdicts. Needs SQLite. Worth building only when a customer asks for it (likely to come up when the same agent fleet needs consistent monitoring across many machines).

Ship v1 first. v2 is a Scope D extension.

## The three Stage 1 verification questions

Each is roughly half a day of work.

### Q1: Does the MCP protocol itself fit this use case?

MCP tools are stateless request/response over JSON-RPC. The decision logic (variant selection, gate checks) is exactly that shape. The only friction would be tool result size limits. Verify by drafting one tool with realistic input/output payloads and checking against the MCP spec's size constraints.

### Q2: Will Mem0's MCP server interop be clean?

A customer using both Mem0's MCP server (for storage ops) and this MCP server (for decisions) needs the two to coexist without tool-name collisions in the agent's tool registry. Verify the tool naming conventions and namespace expectations.

### Q3: What's the right granularity for `deployment_id`?

Per-tenant? Per-customer? Per-instance? Affects how the customer maps their fleet to the MCP server. Verify by sketching what an example deployment registration would look like across the three common shapes (single tenant, multi-tenant SaaS, enterprise batch).

## Why this depends on v0.2.x

Tools 1, 2, 3, and 4 all rely on the **profile system** that v0.2.x introduces (domain × model × setup configurability). Without v0.2.x:

- `which_variant_for(domain, llm_class, setup)` would always return v0.1.8 with default config. Not very "adaptive."
- `should_sweep_now()` would just check time elapsed. No profile-driven thresholds.
- `evaluate_proposed_collection()` would have nothing to project against. The profile system provides the F1 / reduction trade-off curves.
- `monitor_health()` would only report what v0.1.x gates say.

Scope C is interesting BECAUSE v0.2.x's profile work. It is the deployment vehicle for v0.2.x's configurability. Without v0.2.x first, Scope C is a thin wrapper around v0.1.8.

**Sequencing**: v0.2.x ships (5-6 weeks); then Scope C MCP (3-5 days). Total: 6-7 calendar weeks of focused work for the combined offering.

## Configurability (the customer-facing surface)

The 5 profile axes from v0.2.x carry through directly:

```yaml
# config/scope_c/example_deployment.yaml
deployment_id: customer_acme_prod_useast1
profile_axes:
  domain: finance
  downstream_framework: graphiti
  llm_class: frontier
  setup: multi-tenant-saas

mcp_behavior:
  state_mode: stateless        # v1; switch to "stateful" when v2 ships
  decision_confidence_floor: 0.7
  include_projected_savings: true   # currency conversion uses domain default

monitoring:
  lookback_hours_default: 24
  alert_on_consecutive_gate_failures: 3
```

The customer registers a deployment ID + profile axes once. Every subsequent MCP tool call references the deployment ID; the server looks up the profile and applies the right decision logic.

## Why this could fail (risk register)

1. **MCP protocol changes break the integration.** MCP is an evolving spec. Mitigation: pin the MCP SDK version; track spec releases.
2. **Customers prefer static config.** Some teams want predictable, runbook-driven behavior because it's easier to debug. Mitigation: the MCP server's tools are advisory; customers can ignore the recommendations and follow the static runbook. Don't force runtime adaptation.
3. **Tool-name collisions with other MCP servers.** If a customer has Mem0's MCP server and this MCP server both registered in Claude Desktop, two `should_sweep_now`-shape tools might collide. Mitigation: namespace all tools with `framework_` prefix (e.g., `framework_should_sweep_now`).
4. **Stateless mode is too chatty.** If every decision requires the agent to pass all deployment history each call, the prompt context bloats. Mitigation: ship v2 stateful mode once usage patterns confirm the chattiness is a real problem.
5. **Decision logic disagrees with the runbook.** The runbook says "sweep every 4 hours"; the MCP says "wait" because traffic is low. Customers get confused about which to trust. Mitigation: the runbook gets a "see MCP for dynamic mode" section once Scope C ships; runbook becomes the conservative default and MCP is the adaptive override.

## Decision criteria: when to fund vs kill

Fund Scope C when:
- v0.2.x has shipped and produced measured numbers
- A customer pilot for the Mem0 path is in motion OR a Graphiti prospect has expressed interest in dynamic cadence
- No incumbent has shipped a memory-GC decision-service MCP in the meantime

Kill Scope C when:
- v0.2.x fails (no graph-native variants to wrap)
- An incumbent (Mem0, Memgraph, Graphiti, or similar) ships a memory-decision MCP during the v0.2.x build window
- Customer feedback is overwhelmingly "we want static config, not runtime decisions"

## Cost estimate

Assumes v0.2.x has already shipped.

| Phase | Effort | Output |
|---|---|---|
| Stage 1 verification (Q1, Q2, Q3) | 1-2 eng-days | Updates to this doc |
| MCP server scaffold + stateless mode | 2 eng-days | `mcp_server/lifecycle_decision/`, 5 tools registered |
| Decision-logic wrappers (call into existing variant + profile code) | 1 eng-day | Tool implementations |
| Test harness with MCP test client | 1 eng-day | `tests/test_mcp_server.py` |
| Example Claude Desktop config + demo recording | 0.5 eng-day | `docs/scope-c-mcp-demo.md` |
| Runbook updates (advisory MCP mode section) | 0.5 eng-day | Updates to `docs/runbook-mem0-v0.1.8-deploy.md` |

**Total: 5-7 engineer-days, roughly 1-1.5 weeks after v0.2.x.**

## What this changes operationally

If funded:
- The framework's product surface expands from "library + runbook" to "library + runbook + runtime decision MCP"
- Sales conversations gain a 30-second demo (open Claude Desktop, ask the MCP a decision question, get a live answer)
- The Mem0 + Graphiti customers can deploy in either static-runbook mode (today's recipe) or MCP-adaptive mode (Scope C)
- The framework gains a distribution mechanism that doesn't require customers to install Python or run benchmarks

If killed:
- Customers continue with the static runbook
- The framework remains a Python library with documentation, not a deployable service
- The configurability work in v0.2.x is still valuable for the static-runbook path; it just isn't queryable at runtime

## Pointers

- Parent opportunity: [`opportunity-v0.2.x-graph-topology-gc.md`](opportunity-v0.2.x-graph-topology-gc.md)
- Methodology compliance (Scope C will need its own pre-registration block per Stage 3+ requirements): [`benchmark-methodology.md`](benchmark-methodology.md)
- Runbook that Scope C augments: [`runbook-mem0-v0.1.8-deploy.md`](runbook-mem0-v0.1.8-deploy.md)
- Synthesis plan (Scope C would update the Phase 5 entry to read "v0.2.x + Scope C MCP"): [`synthesis-memory-lifecycle-management.md`](synthesis-memory-lifecycle-management.md)
- MCP protocol spec: [modelcontextprotocol.io](https://modelcontextprotocol.io)

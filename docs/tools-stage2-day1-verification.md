---
type: stage-note
opportunity: agent tools dimension
stage: 2
day: 1
date: 2026-06-07
---

# Tools Stage 2 Day 1: incumbent verification

Goal: spot-check the two incumbents most directly relevant to the Wedge A pick (tool-set composition benchmark suite). Day 1 of the Stage 2 plan in [`opportunity-tools.md`](opportunity-tools.md). Verified via WebFetch on 2026-06-07.

## Verified: Anthropic tool_use API

Source: `platform.claude.com/docs/en/agents-and-tools/tool-use/overview` (WebFetch, 2026-06-07).

What it ships:

| Mechanism | What it does |
|---|---|
| `tools: list[dict]` | Pass any number of tool definitions (each with `name`, `description`, `input_schema`) |
| `tool_choice: {"type": "auto"\|"any"\|"tool"\|"none"}` | Force tool use or not. `auto` is default. |
| `strict: true` on tool definitions | Guaranteed schema conformance on tool args |
| `disable_parallel_tool_use` | Disable concurrent multi-tool calls (steerability knob) |
| Server tools (web_search, code_execution, web_fetch, tool_search) | Anthropic-hosted tools that run on Anthropic infra |

**Pricing data confirms the wedge.** From the official pricing table:

| Model | tool_choice=auto/none | tool_choice=any/tool |
|---|---|---|
| Claude Opus 4.8 | 290 tokens | 410 tokens |
| Claude Opus 4.7 | 675 tokens | 804 tokens |
| Claude Opus 4.6 | 497 tokens | 589 tokens |
| Claude Sonnet 4.6 | 497 tokens | 589 tokens |
| Claude Haiku 4.5 | 496 tokens | 588 tokens |

Every tool definition added to the `tools` parameter adds more tokens (its name + description + JSON schema). With 50 tools at ~100 tokens each, you have ~5000 tokens of context spent just on tool descriptions BEFORE any user input. **At Opus pricing, this is a meaningful cost-per-call delta as a function of tool-set size.** This is exactly what Wedge A's UC-TOOL-4 (per-task latency / cost) is designed to measure.

What it does NOT ship:

- **No tool-set composition guidance.** The docs say "tool access is one of the highest-leverage primitives" but offer no advice on which subset of N tools to expose when you have more than the model can use effectively. App developer reinvents.
- **No tool-description quality benchmark.** Wedge B in the opportunity scan. Folklore exists ("be concise," "include examples") but no measured comparison.
- **No tool-selection accuracy benchmark across set sizes.** No published Anthropic data on "at N tools, selection accuracy drops by X%". The LAB-Bench and SWE-bench mentions are task benchmarks, not tool-selection benchmarks.

## Verified: Model Context Protocol (MCP) specification

Source: `github.com/modelcontextprotocol/specification` (WebFetch, 2026-06-07).

The MCP specification provides:

- `tools/list` for tool discovery from one server
- `tools/call` for single-tool invocation
- Server capability declaration

The MCP specification does NOT provide:

> "implementations are free to expose tools through any interface pattern that suits their needs — the protocol itself does not mandate any specific user interaction model."

Translated: MCP is a transport, not an evaluation framework. When a client (Claude Desktop, Cursor, others) connects to N MCP servers exposing M tools each, the spec is silent on:

- Tool deduplication across servers (two servers might both expose a `search` tool)
- Tool ranking (which server's tool to prefer when names collide)
- Tool aggregation budgets (how many tools to expose to the model out of the total available)
- Tool-selection accuracy under N-server load

This is exactly the Wedge C territory the opportunity scan flagged. The Wedge A foundation (tool-set composition benchmark) is the prerequisite that lets these multi-server aggregation strategies be compared.

## What is still open

After both verifications, the three gaps from the opportunity scan are all confirmed:

1. **No tool-set composition benchmark.** Anthropic / OpenAI / MCP all ship tool primitives; none ship "given N tools, which subset should be exposed for task class K?" benchmark or comparison framework. Wedge A directly.
2. **No tool-description quality benchmark.** Wedge B. Confirmed absent at Anthropic (no published methodology) and absent at the MCP layer (out of scope).
3. **No cross-MCP aggregation benchmark.** Wedge C. The MCP spec explicitly defers this to clients; no client today benchmarks its aggregation strategy publicly.

## Not yet live-verified (deferred)

- OpenAI function calling docs (parallel coverage to Anthropic; likely same gap)
- LangChain `BaseTool` source (parallel to LangGraph `RetryPolicy` from the recovery Day 1, exception-class style filtering)
- AutoGen / CrewAI tool-registration source
- Inspect AI agent_bench evaluations

These were covered from training knowledge in the opportunity scan. A deep-research workflow call would expand and consolidate; not in this batch.

## Decision

The wedge is intact. Proceed to Day 2 (build the synthetic task-completion workload). No edits needed to the opportunity scan's Wedge A pick.

---
type: opportunity
dimension: tools
stage: 1
status: WEDGE-CANDIDATE
date: 2026-06-07
---

# Stage 1 opportunity scan: agent tool dimension

This is the Stage 1 landscape scan for the **tools** dimension, the second non-memory dimension scanned. Recovery scan was [`opportunity-recovery.md`](opportunity-recovery.md); this scan is its sibling for the tools dimension.

The tools dimension covers everything about which tools the agent can see, how it selects among them, how it argments them, what it does when one fails, and how tool composition affects task outcomes. The dimension already has scaffolding (`ToolVariant` ABC, `ToolCall` dataclass, `b-allow-all-tools` baseline at `runner/dimensions/tools/`).

## What the incumbents do today

| Tool / framework | Tool primitives shipped | Gap relevant to a benchmark |
|---|---|---|
| **Anthropic SDK tool_use** | `tools: list[dict]` parameter with JSON-schema-validated arguments; `tool_choice` with `auto`, `any`, `tool` modes; `disable_parallel_tool_use` knob | No A/B comparison across tool-set compositions; no harness for measuring whether tool ordering / naming / description quality affects selection rates |
| **OpenAI function calling** | `tools: list[function]` + `tool_choice` + `parallel_tool_calls` + `strict` mode for structured args | Same gap. Single-call evaluation only. |
| **Model Context Protocol (MCP)** | Standardized server protocol: clients (Claude Desktop, Cursor, others) connect to MCP servers that expose tools | MCP is a transport, not an evaluation framework. Aggregating tools from N MCP servers has no benchmark for "does the agent pick the right tool when 100 are exposed?" |
| **LangChain Tool wrappers** | `BaseTool`, `StructuredTool`, `@tool` decorator; `args_schema` Pydantic validation; `handle_tool_error` for catch-and-recover | Per-tool error handling but no policy comparison across tool sets. |
| **LangGraph** | Tool execution via nodes; conditional edges can route on tool errors | Same recovery gap as the recovery-dimension scan flagged. No tool-set policy primitive. |
| **AutoGen / AG2** | Function-registration on agent; conversational tool routing | No benchmark surface. |
| **CrewAI** | Tools registered per-agent role; role-based tool isolation | Role-tool mapping is hand-curated; no measurement of whether the curation is right. |
| **Guardrails AI / Pydantic AI** | Output schema validation that interacts with tool args | Validation only, no selection comparison. |
| **Inspect AI** | Tool-use benchmarks (e.g., agent_bench evaluations) | Eval surface exists but each task tests one fixed tool set; no comparison primitive. |
| **Toolformer-style learned-tool literature** | Models trained to insert tool calls in-context | Training-time concern, not evaluation-time. |
| **Routing systems (Martian, RouteLLM, Not Diamond)** | Route between models (not between tools) | Wrong axis. |

## What is missing

Three concrete gaps, none filled by any of the above:

1. **No benchmark for tool-set composition.** Given 3 candidate tool descriptions for "search the web" (verbose, terse, with one example, with three examples), which produces the highest task-completion rate? Which produces the lowest hallucinated-arguments rate? No tool today A/B tests these.
2. **No benchmark for tool-selection policy.** Given 50 tools and a task, does narrowing the visible tool set (e.g., budget-aware: only expose the 10 cheapest tools; intent-aware: only expose tools matching a classifier prediction) beat exposing all 50? At what tool-set size does selection accuracy degrade? Nobody knows in any rigorous way.
3. **No benchmark for tool-failure handling.** Adjacent to the recovery dimension but distinct: how should tool-level errors (HTTP 503, malformed response, refused permission) be propagated to the agent loop? Retry the same tool, try a different tool, hand to user? Same evaluation gap as recovery but specifically at the tool layer.

## Three candidate wedges

### Wedge A: Tool-set composition benchmark suite (variant ABC + statistical comparison)

Build `ToolVariant` implementations that expose different tool-set compositions (full, narrow, budget-bucketed, role-bucketed) and benchmark each on a task-completion workload with controlled failure injection. Same harness shape as the recovery dimension.

- **Pros**: The `ToolVariant` ABC already exists. The harness (paired bootstrap, LORD++ FDR, UC gates) carries over. Synthetic task workload is buildable in days.
- **Cons**: Needs a task-completion simulator (analogous to the failure-injection simulator). Realistic synthesis is harder for tool selection than for failure injection because tool-relevance depends on task content. Could fall back to "given a tool the task needs, did the agent pick it?" which is a narrower but cleaner metric.
- **Incumbent overlap**: None directly. Inspect AI's tool-use evals are single-configuration; this would let you compare configurations.

### Wedge B: Tool-description quality benchmark

Generate multiple descriptions for the same tool (verbose, terse, with examples, with constraints) and benchmark which produces highest selection accuracy and lowest hallucinated-argument rate. This is essentially "what's the best way to write a tool description?" answered with statistics rather than vibes.

- **Pros**: Highly actionable result. Every framework that uses tools immediately benefits.
- **Cons**: Description quality interacts with the model, so the result needs the multi-model ladder to be defensible. Smaller scope than A but the recurring question every framework user has.
- **Incumbent overlap**: None. There is folklore ("write concise descriptions," "add examples to args") but no measured comparison.

### Wedge C: Cross-MCP-server tool aggregation benchmark

With MCP now widely supported (Claude Desktop, Cursor, others), an agent can suddenly see hundreds of tools from N MCP servers. Benchmark how aggregation strategies (round-robin, server-priority, intent-classify-then-route, budget-capped) affect selection accuracy.

- **Pros**: Hottest current pain point. MCP makes this concrete in a way it was not 12 months ago.
- **Cons**: Requires actual MCP servers to test against. Higher infrastructure cost. The wedge depends on MCP adoption holding (a real risk if a competing protocol replaces it).
- **Incumbent overlap**: MCP ecosystem is moving fast; this wedge could be partially closed by a tool that ships in the next 90 days. Higher risk of becoming irrelevant.

## Pick: Wedge A (tool-set composition benchmark)

For three reasons:

1. **It matches the framework's current capability most closely.** `ToolVariant` ABC already ships. Adding pilot variants that expose different tool-set compositions is the same shape as adding GC variants or recovery variants.
2. **It is the prerequisite for B and C.** Both description-quality benchmarking (B) and MCP aggregation (C) need a way to compare tool sets statistically. Wedge A is the foundation.
3. **No incumbent has it.** Wedge A's gap is structural to how every tool framework today is designed: they all ship single-configuration tool sets and let the user worry about whether the configuration is right.

This mirrors the wedge-pick logic from the schema-alignment proxy ([`opportunity.md`](opportunity.md)) and recovery ([`opportunity-recovery.md`](opportunity-recovery.md)): pick the foundational benchmark wedge, build the tooling, then use the tooling for the more specific wedges (B and C) in later opportunities.

## Out-of-scope for Stage 1

- **Real MCP server integration** (Wedge C concern, deferred)
- **Training data / agent fine-tuning for tool selection** (different problem space)
- **Tool security / sandboxing** (orthogonal axis; would be its own opportunity scan)

## Stage 2 plan sketch (not committed)

If Wedge A holds up, Stage 2 would look like:

**Day 1**: Verify the incumbent state. WebFetch / read source for Anthropic SDK `tool_choice` behavior, MCP spec's selection guidance, LangChain `BaseTool` source.

**Day 2**: Build the synthetic task-completion workload. Each task = (goal, ground_truth_required_tools, optional_helper_tools, distractor_tools). Workload sweep tests variants on completion rate, selection precision (did agent pick a required tool?), and selection recall (did agent skip distractors?). Deterministic with seed.

**Day 3**: Build three pilot tool variants:
- `b-allow-all-tools` (already in `runner/dimensions/tools/b_noop.py`)
- `tool-v0.1.0-budget-bucketed` (only expose tools whose cost is under a budget threshold)
- `tool-v0.1.1-intent-classified` (use a simple classifier to pre-filter tools by intent match)

**Day 4**: Build the recovery runner with UC gates:
- UC-TOOL-1: task-completion rate >= baseline + threshold
- UC-TOOL-2: selection precision (true required tool selected / total tools selected)
- UC-TOOL-3: selection recall (true required tools selected / true required tools available)
- UC-TOOL-4: per-task latency (tool-set size affects context length and inference time)

**Day 5**: Run benchmark + write finding doc.

If Day 5 passes, Stage 3 hooks the pilot variants into a real agent loop (LangGraph or a Claude tool-use loop with curated tools) and runs on a small set of real tasks.

## Pointers

- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Existing scaffolding: `runner/dimensions/tools/{base.py, b_noop.py, __init__.py}`
- Framework narrative: [`../FRAMEWORK.md`](../FRAMEWORK.md)
- Precedents for this scan's shape: [`opportunity.md`](opportunity.md) (proxy wedge), [`opportunity-graph-gc.md`](opportunity-graph-gc.md) (graph-GC wedge), [`opportunity-recovery.md`](opportunity-recovery.md) (recovery wedge)

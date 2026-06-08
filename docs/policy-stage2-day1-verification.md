---
type: stage-note
opportunity: agent execution-policy dimension
stage: 2
day: 1
date: 2026-06-08
---

# Policy Stage 2 Day 1: incumbent verification

Goal: spot-check the incumbents most relevant to the Wedge A pick (policy-comparison benchmark with model x policy interaction). Day 1 of the Stage 2 plan in [`opportunity-policy.md`](opportunity-policy.md). Verified via WebFetch on 2026-06-08.

## Verified: LangGraph StateGraph

Source: `langchain-ai/langgraph` repo, `libs/langgraph/langgraph/graph/state.py` (raw GitHub fetch, 2026-06-08).

What it ships:

| Primitive | What it does |
|---|---|
| `StateGraph(state_schema)` | Define a graph of nodes operating on a shared state |
| `add_node(name, action, *, retry_policy, cache_policy)` | Add a node with optional retry policy attached |
| `add_conditional_edges(source, path, path_map)` | Branch on the output of a node (this is how error routing is hand-coded) |
| `interrupt(value)` | Pause execution for human-in-the-loop |
| `compile(checkpointer)` | Produce an executable Pregel graph |

What it does NOT ship:

- **No reusable policy modules**. LangGraph provides the building blocks (state, nodes, edges, interrupt) but ships no `ReActPolicy` or `PlanExecutePolicy` or `ReflectLoopPolicy` as standalone modules. Every agent's policy is hand-coded by composing nodes and edges.
- **No policy-comparison surface**. Two policies expressed as two different graphs cannot be A/B tested with one harness call. Comparison is bespoke per-graph.
- **No model x policy interaction benchmark**. The library is model-agnostic but does not surface "this policy works at model size X but not Y" data.

## Verified: LangChain pre-built agent constructors

Source: `langchain-ai/langchain` repo, `libs/langchain/langchain/agents/` (from training knowledge, not live-fetched this round).

Known pre-built constructors:
- `create_react_agent(llm, tools)` - ReAct pattern
- `create_openai_functions_agent(llm, tools, prompt)` - tool-use loop with parallel function calls
- `create_structured_chat_agent(llm, tools, prompt)` - structured input/output variant

What is shipped:
- One executable agent per constructor. Pick the constructor that matches the model + tool style; run it.

What is NOT shipped:
- **No benchmark layer.** No "given this task class, which constructor produces highest completion?" tooling.
- **No reflection / self-critique constructor.** Reflexion-style policies are in research papers, not in LangChain's pre-built set.
- **No multi-agent constructor in core LangChain.** Multi-agent patterns are in LangGraph examples (hand-coded) or in AutoGen / CrewAI / OpenAI Swarm.

## Inferred: Reflexion (not live-verified this round)

The Reflexion paper and follow-up implementations (madaan/self-refine, etc.) ship reflection loops where the agent generates an output, critiques it, then revises. From training knowledge:
- Most implementations target one task class (math reasoning, code) and one model.
- Convergence behavior (at what reflection iteration does additional reflection stop helping?) is reported per-paper, not as a reusable framework.
- No published cross-policy comparison: "reflection vs ReAct vs plan-execute on the same workload."

Live verification deferred; would benefit from a deep-research workflow call.

## What is still open

After the LangGraph verification, the gap is confirmed:

1. **No reusable cross-policy benchmark.** LangGraph offers primitives, LangChain offers pre-built constructors, AutoGen/CrewAI ship multi-agent patterns. None of them ship "run policy P1 and policy P2 on the same workload across the same model ladder; report which wins."
2. **No model x policy interaction surface.** Folklore: small models cannot sustain long policy loops; large models can. Nobody published the measurement.
3. **No cost-per-completion comparison.** Plan-execute and reflection add 2-3x model calls per task. The lift per cost is the deployable metric; not published anywhere.

Wedge A (policy-comparison benchmark with model x policy interaction baked in) is intact.

## Decision

Proceed to Day 2 (build the synthetic policy-task workload). The simulator will mirror the recovery dimension's pattern: hard-coded probability tables for "policy P resolves task class K at difficulty D" in Stage 2; real LLM measurement in Stage 3.

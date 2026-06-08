---
type: opportunity
dimension: execution policy
stage: 1
status: WEDGE-CANDIDATE
date: 2026-06-07
---

# Stage 1 opportunity scan: agent execution-policy dimension

This is the Stage 1 landscape scan for the **execution policy** dimension. The dimension already has scaffolding (`PolicyVariant` ABC + `AgentStep` dataclass + `b-single-shot-policy` baseline at `runner/dimensions/policy/`).

Execution policy covers how an agent decides what to do at each step: react vs plan-then-execute vs reflection-loop vs hand-off to a sub-agent vs single-shot. Most agent frameworks SHIP these patterns as code primitives; none benchmark them apples-to-apples on the same workload across the same model ladder under statistical control.

## What the incumbents do today

| Tool / framework | Policy primitives shipped | Gap relevant to a benchmark |
|---|---|---|
| **LangGraph** | Graph-based execution where nodes implement state transitions; conditional edges; `interrupt` for human-in-loop | Each graph is hand-coded for a task. No reusable policy primitives that span tasks. No comparison framework. |
| **LangChain ReAct / Plan-and-execute / OpenAI-Functions agents** | Pre-built agent constructors (`create_react_agent`, etc) | One pattern per constructor. No comparison across patterns on the same task. |
| **AutoGen / AG2** | Multi-agent conversation patterns: sequential, group-chat, hierarchical, swarm | Pattern as code; comparison only by user trial-and-error. |
| **CrewAI** | Role-based multi-agent crews with sequential / hierarchical process | Same pattern shape as AutoGen; no benchmark layer. |
| **DSPy ReAct module** | DSPy-compatible ReAct implementation; can be auto-optimized | Optimization works within ReAct; doesn't compare ReAct vs plan-execute. |
| **Reflexion / Reflexion-style libs** | Implements reflection loops that score and improve | Single pattern; not benchmarked against alternatives. |
| **Inspect AI** | Evaluates agent task completion; supports custom policies | Eval surface for one policy per evaluation; no built-in comparison. |
| **HumanEval, SWE-bench, AgentBench, GAIA** | Task-completion benchmarks across agent systems | Benchmark the SYSTEM, not the policy independent of the system. A SWE-bench score conflates model + tools + policy + prompts. |
| **OpenAI Agents SDK** | Light agent wrapper with tool-use + handoff | One policy shape, no comparison surface. |
| **Microsoft Magentic-One / Semantic Kernel planners** | Planner-executor patterns | Each planner is its own framework; no policy comparison. |

## What is missing

Three concrete gaps shared by everyone above:

1. **No apples-to-apples policy comparison on the same workload.** A research paper comparing ReAct vs Reflexion typically uses different tasks, different models, and ad-hoc metrics. There is no published "given task class K, model M, tool set T, which policy gives the best task-completion-per-cost?"
2. **No cost-budgeted policy benchmark.** Reflection loops add 2-3 model calls per step; plan-execute adds a planning prompt. None of the incumbents quantify the cost lift required to make a policy pay off vs the simpler baseline.
3. **No model-aware policy comparison.** A 3B local model often cannot sustain a 5-step plan-execute loop without going off the rails; a frontier model handles it gracefully. The "right policy" depends on the model. No published cross-model policy comparison.

## Three candidate wedges

### Wedge A: Policy-comparison benchmark suite (variant ABC + cost-budgeted gates)

Build `PolicyVariant` implementations for the canonical patterns (single-shot, ReAct, plan-and-execute, reflection-loop, multi-agent-handoff) and benchmark each on a task-completion workload across the multi-model ladder.

- **Pros**: The `PolicyVariant` ABC already exists. The `AgentStep` dataclass models the standard agent step types. The harness shape carries over from the recovery + tools dimensions.
- **Cons**: Policy variants need an underlying "executor" that simulates tool calls and observes results. Synthetic execution is similar to the recovery dimension's failure-injection simulator but bigger in scope.
- **Incumbent overlap**: None doing apples-to-apples cross-policy comparison.

### Wedge B: Model-size x policy-shape interaction benchmark

Specifically focus on the cross-product of model size and policy shape. The expected finding: "small models need simpler policies (single-shot, narrow ReAct); large models can use richer policies (multi-step plan-execute, multi-agent)." This is folklore; nobody has measured it.

- **Pros**: Highly actionable result. Operators can route tasks to (model, policy) pairs.
- **Cons**: Subset of Wedge A; should probably be done as part of A rather than separately.
- **Incumbent overlap**: Models routing (Martian, RouteLLM) gestures at this but at the model level only; not the policy level.

### Wedge C: Reflection-loop convergence benchmark

Specifically focus on reflection / self-critique loops. At what iteration does additional reflection no longer improve task completion? Is there a kind of task where reflection HURTS (overcorrects)?

- **Pros**: Specific to a hot research area (test-time compute / reasoning).
- **Cons**: Narrow scope. Better as a follow-up to Wedge A than as a primary wedge.
- **Incumbent overlap**: Reflexion paper and follow-ups gesture at this; not under statistical control or across models.

## Pick: Wedge A (policy-comparison benchmark) with Wedge B framing baked in

For three reasons:

1. **It is the highest-coverage wedge.** Wedges B and C are special cases of A. Building A first means B and C come naturally as analyses of the same data.
2. **It matches the existing framework.** Statistical harness, variant ABC, multi-model ladder, finding-doc culture all transfer.
3. **No incumbent has the comparison primitive.** Every agent framework ships ONE policy and lets the user iterate. The wedge is "the first benchmark that lets you A/B test policies."

Wedge C (reflection convergence) is a worthy follow-up.

## Out-of-scope for Stage 1

- **Multi-agent communication protocols** (swarm vs hierarchical vs broadcast; would be its own opportunity scan)
- **Learned policies** (RL-trained agent decision policies; orthogonal axis)
- **Real-time / streaming agents** (latency-bounded execution is a different problem space)

## Stage 2 plan (sketch, not committed)

If Wedge A holds up, Stage 2 looks like:

**Day 1**: Verify the incumbent state. WebFetch LangGraph's `interrupt` semantics, LangChain's `create_react_agent` source, AutoGen's group-chat / swarm primitives, Reflexion's published implementation.

**Day 2**: Build the synthetic task-completion workload with executable steps. Each task has a goal + step-graph + ground-truth result. The runner simulates an agent walking the policy through the task, calling tools (the existing failure-injection simulator can be reused for tool errors).

**Day 3**: Build four-to-six pilot policy variants:
- `b-single-shot-policy` (already in `runner/dimensions/policy/b_noop.py`)
- `policy-v0.1.0-react` (think -> act -> observe loop with max steps)
- `policy-v0.1.1-plan-execute` (plan upfront, then execute steps)
- `policy-v0.1.2-reflect-loop` (after each step, reflect; revise plan)
- `policy-v0.1.3-handoff` (single-shot, but on failure handoff to a more capable model)

**Day 4**: Build the runner with UC gates:
- UC-POLICY-1: task-completion lift vs single-shot
- UC-POLICY-2: cost-per-correct-completion <= baseline * 2.0
- UC-POLICY-3: max steps per task
- UC-POLICY-4: per-task latency

**Day 5**: Run benchmark across the multi-model ladder + write finding doc with the model x policy interaction table (Wedge B's deliverable).

If Day 5 passes, Stage 3 runs on a real public agent benchmark subset (AgentBench tasks, SWE-bench minified, or a HotpotQA agent variant) with the same policy variants.

## Pointers

- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Existing scaffolding: `runner/dimensions/policy/{base.py, b_noop.py, __init__.py}`
- Framework narrative: [`../FRAMEWORK.md`](../FRAMEWORK.md)
- Multi-model ladder (will be reused): `experiments/ladder_sweep_real_data.py`
- Recovery dimension precedent (similar runner shape): `runner/recovery_runner.py`
- Precedents for this scan's shape: [`opportunity.md`](opportunity.md), [`opportunity-graph-gc.md`](opportunity-graph-gc.md), [`opportunity-recovery.md`](opportunity-recovery.md), [`opportunity-tools.md`](opportunity-tools.md), [`opportunity-prompt.md`](opportunity-prompt.md)

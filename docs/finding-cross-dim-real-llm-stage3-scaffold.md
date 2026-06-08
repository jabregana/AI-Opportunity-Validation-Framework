---
type: finding
opportunity: cross-dimension orchestration
stage: 3
status: SCAFFOLD-COMPLETE-AWAITING-API-ACCESS
date: 2026-06-08
artifact: runs/cross_dim_real_llm_stage3/20260608T085557.json
---

# Real-LLM Stage 3: scaffold complete, awaiting API budget for real run

This finding documents the **scaffolding** for taking the framework's recommended joint configuration (from [`finding-cross-dim-cost-weighted.md`](finding-cross-dim-cost-weighted.md)) and running it against a real LLM agent loop. The scaffold ships with a stub LLM client and runs end-to-end; **the real-LLM run itself is deferred until API access (and budget) is provisioned.**

## Why this is honest as "Stage 3 scaffold" rather than "Stage 3"

The framework's Stage 3 discipline is "real data, small N." For a cross-dim joint deployment, "real data" means real LLM calls executing the recommended config on real tasks. That requires:

1. API keys (Anthropic / OpenAI / OpenRouter / etc) OR a running local LLM
2. Real budget (50-100 task runs at frontier-model rates is roughly $1-$10)
3. Time (most runs take minutes per task)

None of these are available in the current execution environment by default. Shipping the scaffold with a stub LLM client lets the user (or future iteration) drop in a real client without re-architecting.

## What the scaffold provides

`experiments/cross_dim_real_llm_stage3.py` ships:

| Component | Behavior |
|---|---|
| `RealLLMConfig` dataclass | Encapsulates the recommended config + model name + n_tasks |
| `RealLLMRunResult` dataclass | Output shape: completion rate, API call count, input/output tokens, estimated $ cost |
| `_get_llm_client(model_name, for_real)` | Factory; returns stub by default, raises `NotImplementedError` for real clients (with documented hook for Anthropic, OpenAI, Ollama wiring) |
| `StubLLMClient` | Returns a randomized 70%-success response so the driver can be exercised end-to-end with no API calls |
| `run_real_llm_stage3(config)` driver | Walks the cross-dim workload: render prompt, expose tools, call LLM, on failure invoke recovery variant |

End-to-end smoke test (with stub) produces a 100% completion rate at zero cost in milliseconds. The wiring is verified.

## To convert this into a real Stage 3 run

Three steps:

1. **Install a real LLM client** (`pip install anthropic` or similar)
2. **Edit `_get_llm_client()` to instantiate the real client** when `for_real=True` and the model name matches the provider's prefix
3. **Run with `--for-real --model claude-haiku-4-5 --n-tasks 50`**

The driver is designed to fail gracefully if the real-client wiring is incomplete (raises `NotImplementedError` with a clear message) rather than silently downgrading to the stub.

## What Stage 3 should test (when run)

The hypothesis: **does the simulator's qualitative recommendation hold up with a real LLM?**

Specifically:
- Does `prompt-v0.1.4-cot-plus-structured` outperform `b-default-prompt` by ~10pp on real tasks? (Simulator says yes; real LLMs may differ by task class.)
- Does `recovery-v0.1.1-fallback-chain` recover ~70% of failed tasks? (Simulator's `P_RESOLVE_OPTIMISTIC` assumes ~60-85% recovery rates; real LLM tool errors have a different distribution.)
- Does the joint config's completion rate land near the simulator's 59.60% estimate (CI [55.0-63.6])?

If yes: the cross-dim matrix becomes a production-decision instrument. The framework can credibly tell an enterprise team "this config will lift completion by ~Xpp on your real workload."

If no: the simulator's lift tables need recalibration. The honest framing then becomes "the cross-dim methodology is right, but the specific variant rankings are simulator-specific and should be calibrated to your domain before deployment."

Either result is informative.

## What this scaffold demonstrates today

Even without a real LLM run, the scaffold has value:

1. **The variant ABCs work in a real agent loop.** Render prompt -> call LLM -> recovery on failure -> finish. The shape carries.
2. **The integration shim pattern from the memory dimension** (proxy + GC integration shims at `runner/dimensions/memory/lifecycle/integrations/`) is the right template for the LLM-side hook. Same contract: pluggable client behind a stable interface.
3. **The cost-tracking model from the cost-weighted matrix** ports directly. Real LLM clients expose input/output token counts; the driver already aggregates them.

## What this finding does NOT earn

- **No actual real-LLM measurement.** This is scaffold only.
- **No statistical comparison to simulator estimates.** That requires the real run.
- **No real cost figures.** The stub reports $0; real clients would multiply by provider rates.

## Decision

Accept the scaffold as a Stage 3 architectural deliverable, analogous to the GC dimension's Stage 4 ARCHITECTURAL-PASS finding. The actual real-LLM run is the next iteration's first item, predicated on API access.

## How this fits the analyst-framing decision-tool positioning

The strategic-framing doc ([`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)) names the simulator-vs-real-LLM gap as the biggest credibility risk. This scaffold is the smallest credible commitment to closing that gap: the framework now ships the wiring; the user (or the project's next iteration) can drop in real clients without architectural change.

## Pointers

- Code: `experiments/cross_dim_real_llm_stage3.py`
- Recommended config source: [`finding-cross-dim-cost-weighted.md`](finding-cross-dim-cost-weighted.md)
- Strategic positioning: [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce (with stub)

```sh
.venv/bin/python experiments/cross_dim_real_llm_stage3.py
# Defaults: n_tasks=20, model=stub-llm, for_real=False.
# Runs the recommended config end-to-end with a stub LLM. Zero cost.
```

## To run for real (when wiring lands)

```sh
# Wire your provider in _get_llm_client(), then:
ANTHROPIC_API_KEY=sk-... \
  .venv/bin/python experiments/cross_dim_real_llm_stage3.py \
  --for-real --model claude-haiku-4-5 --n-tasks 50
```

"""Real-LLM Stage 3 scaffolding for the cross-dim recommended config.

This is the SCAFFOLDING for taking the framework's recommended joint
configuration (from the cost-weighted matrix) and running it against
a real LLM agent loop. It does NOT actually run an LLM by default
because:

  1. It would consume real API budget
  2. It requires API keys (Anthropic / OpenAI / OpenRouter / etc)
     or a running local LLM (Ollama)
  3. Running 50-100 real tasks takes minutes-to-hours

What this module provides:

  - `RealLLMConfig` dataclass that maps the recommended config
    (prompt variant + tools variant + recovery variant) onto real
    LLM calls
  - `run_real_llm_stage3()` driver that calls the variants against
    a pluggable LLM client (Anthropic, OpenAI, Ollama)
  - Stub LLM client for dry-run testing
  - Documented integration points for real clients

To actually run with a real LLM:
  1. Install the client (e.g. `pip install anthropic`)
  2. Set the API key in env (e.g. ANTHROPIC_API_KEY=sk-...)
  3. Edit `_get_llm_client()` to use the real client
  4. Run with `--for-real` flag

The Stage 3 hypothesis being tested: does the simulator's qualitative
recommendation (cot-plus-structured + b-allow-all-tools + fallback-
chain) hold up with a real LLM? If yes, the cross-dim matrix becomes
a production-decision instrument.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures.workloads.w_cross_dim_scenarios import (
    generate_cross_dim_workload,
)
from fixtures.workloads.w_tool_selection import (
    TOOL_CATEGORIES,
    TOOL_UNIVERSE,
)
from runner.dimensions.prompt import build as build_prompt
from runner.dimensions.recovery import build as build_recovery
from runner.dimensions.tools import build as build_tool


# The recommended configuration from the cost-weighted matrix experiment.
# Updated to point at the statistically-indistinguishable BUT slightly
# cheaper #2 instead of the marginal #1.
RECOMMENDED_PROMPT = "prompt-v0.1.4-cot-plus-structured"
RECOMMENDED_TOOLS = "b-allow-all-tools"
RECOMMENDED_RECOVERY = "recovery-v0.1.1-fallback-chain"


@dataclass
class RealLLMConfig:
    prompt_variant: str = RECOMMENDED_PROMPT
    tool_variant: str = RECOMMENDED_TOOLS
    recovery_variant: str = RECOMMENDED_RECOVERY
    model: str = "claude-haiku-4-5"  # cheap default
    n_tasks: int = 50               # bounded by API budget
    for_real: bool = False           # set True to actually call LLMs


@dataclass
class RealLLMRunResult:
    config: RealLLMConfig
    n_attempted: int
    n_completed: int
    completion_rate_pct: float
    total_api_calls: int
    total_input_tokens: int  # approximate
    total_output_tokens: int  # approximate
    estimated_cost_usd: float
    per_task_outcomes: list[dict] = field(default_factory=list)


def _approx_token_count(text: str) -> int:
    return max(1, len(text) // 4)


class StubLLMClient:
    """Dry-run LLM that returns a deterministic structured answer.

    Use this to validate the driver wiring before spending real API
    budget. Stub completion is randomized at ~70% by default so the
    Stage 3 driver can be exercised end-to-end.
    """

    name = "stub-llm"
    input_token_rate = 0.0
    output_token_rate = 0.0

    def __init__(self, success_rate: float = 0.70, seed: int = 0):
        import random
        self.success_rate = success_rate
        self.rng = random.Random(seed)

    def call(
        self,
        prompt: str,
        tools: list[str],
        max_output_tokens: int = 256,
    ) -> dict:
        """Return a fake LLM response.

        Returns a dict with at least:
          {"text": "...", "input_tokens": N, "output_tokens": M,
           "tool_calls": [], "stopped_on": "...", "completed": bool}
        """
        # Deterministic, looks like real shape
        completed = self.rng.random() < self.success_rate
        return {
            "text": "[stub] task complete" if completed else "[stub] partial",
            "input_tokens": _approx_token_count(prompt) + 100 * len(tools),
            "output_tokens": 30,
            "tool_calls": [],
            "stopped_on": "end_turn",
            "completed": completed,
        }


def _get_llm_client(model_name: str, for_real: bool):
    """Return an LLM client appropriate for the requested model.

    To wire a real client, populate the for_real branch. The
    framework's narrative discipline is that we do not silently
    upgrade from stub to real; the user must opt in.
    """
    if not for_real:
        return StubLLMClient(success_rate=0.70, seed=42)

    if model_name.startswith("claude-"):
        # Anthropic client wiring (not active by default)
        raise NotImplementedError(
            "Real Anthropic client wiring is documented in this file's "
            "docstring; uncomment to enable."
        )
    if model_name.startswith("gpt-"):
        raise NotImplementedError("OpenAI client wiring not active.")
    if model_name.startswith("ollama:"):
        raise NotImplementedError("Ollama client wiring not active.")
    raise NotImplementedError(f"Unknown model: {model_name}")


def run_real_llm_stage3(config: RealLLMConfig) -> RealLLMRunResult:
    """Drive the recommended-config agent loop against a real LLM.

    For each task: render prompt (via variant), pass tool set (via
    variant), call LLM, score result. On failure, recovery variant
    decides next step (retry / fallback / abort).
    """
    workload = generate_cross_dim_workload(
        n_scenarios=config.n_tasks,
        failure_rate=0.0,  # Real Stage 3 should source failures
                          # from the LLM's actual behavior, not
                          # synthetic injection
        seed=42,
    )

    prompt_v = build_prompt(config.prompt_variant)
    tool_v = build_tool(config.tool_variant)
    recovery_v = build_recovery(config.recovery_variant)
    client = _get_llm_client(config.model, config.for_real)

    n_completed = 0
    total_api_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    per_task: list[dict] = []

    for sc in workload.scenarios:
        # 1. Render the prompt via the prompt variant
        rendered = prompt_v.render({"raw": sc.goal})

        # 2. Get the exposed tool set
        ctx = {
            "all_tools": list(TOOL_UNIVERSE),
            "goal": sc.goal,
            "categories": TOOL_CATEGORIES,
            "task_id": sc.scenario_id,
            "required_tools": list(sc.required_tools),
        }
        exposed_tools = tool_v.available_tools(ctx)

        # 3. Call the LLM
        response = client.call(rendered, exposed_tools)
        total_api_calls += 1
        total_input_tokens += response.get("input_tokens", 0)
        total_output_tokens += response.get("output_tokens", 0)
        completed = response.get("completed", False)

        if completed:
            n_completed += 1
            per_task.append({
                "task_id": sc.scenario_id,
                "category": sc.category,
                "completed": True,
                "n_attempts": 1,
            })
            continue

        # 4. On failure, invoke the recovery variant
        # (Real Stage 3 would classify the failure kind here; the
        # stub doesn't surface enough detail so we use tool_error
        # as a default and let recovery decide.)
        from runner.dimensions.recovery import Failure
        failure = Failure(kind="tool_error", detail={"raw_response": str(response.get("text", ""))})
        action = recovery_v.recover(
            failure,
            context={"scenario_id": sc.scenario_id, "n_retries": 0,
                     "n_fallbacks": 0},
        )

        if action.kind == "retry":
            response2 = client.call(rendered, exposed_tools)
            total_api_calls += 1
            total_input_tokens += response2.get("input_tokens", 0)
            total_output_tokens += response2.get("output_tokens", 0)
            if response2.get("completed", False):
                n_completed += 1
            per_task.append({
                "task_id": sc.scenario_id,
                "category": sc.category,
                "completed": response2.get("completed", False),
                "n_attempts": 2,
                "recovery_action": "retry",
            })
        elif action.kind == "fallback":
            # Real Stage 3 would switch to a different tool / model here
            per_task.append({
                "task_id": sc.scenario_id,
                "category": sc.category,
                "completed": False,
                "n_attempts": 1,
                "recovery_action": "fallback (not implemented in stub)",
            })
        else:
            per_task.append({
                "task_id": sc.scenario_id,
                "category": sc.category,
                "completed": False,
                "n_attempts": 1,
                "recovery_action": action.kind,
            })

    # Estimated cost: stub is free, real clients would multiply by
    # provider rate
    estimated_cost_usd = (
        total_input_tokens * client.input_token_rate
        + total_output_tokens * client.output_token_rate
    )

    return RealLLMRunResult(
        config=config,
        n_attempted=config.n_tasks,
        n_completed=n_completed,
        completion_rate_pct=100.0 * n_completed / max(1, config.n_tasks),
        total_api_calls=total_api_calls,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        per_task_outcomes=per_task,
    )


def main():
    p = argparse.ArgumentParser(prog="cross-dim-real-llm-stage3")
    p.add_argument("--n-tasks", type=int, default=20,
                   help="how many tasks to run (default 20)")
    p.add_argument("--model", default="stub-llm",
                   help="LLM identifier (claude-* / gpt-* / ollama:* / stub-llm)")
    p.add_argument("--for-real", action="store_true",
                   help="actually call the LLM (otherwise use stub)")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    config = RealLLMConfig(
        prompt_variant=RECOMMENDED_PROMPT,
        tool_variant=RECOMMENDED_TOOLS,
        recovery_variant=RECOMMENDED_RECOVERY,
        model=args.model,
        n_tasks=args.n_tasks,
        for_real=args.for_real,
    )

    print("=" * 78)
    print("Real-LLM Stage 3 driver")
    print("=" * 78)
    print(f"Recommended config:")
    print(f"  prompt:   {config.prompt_variant}")
    print(f"  tools:    {config.tool_variant}")
    print(f"  recovery: {config.recovery_variant}")
    print(f"Model:     {config.model}")
    print(f"For real:  {config.for_real}")
    print(f"N tasks:   {config.n_tasks}")
    print()

    if not config.for_real:
        print("RUNNING WITH STUB LLM (no real API calls).")
        print("To run with a real LLM:")
        print("  1. Wire your provider in _get_llm_client()")
        print("  2. Set the appropriate API key in env")
        print("  3. Re-run with --for-real")
        print()

    t0 = time.perf_counter()
    result = run_real_llm_stage3(config)
    elapsed = time.perf_counter() - t0

    print(f"completion rate:   {result.completion_rate_pct:.2f}%")
    print(f"api calls:         {result.total_api_calls}")
    print(f"input tokens:      {result.total_input_tokens}")
    print(f"output tokens:     {result.total_output_tokens}")
    print(f"estimated cost:    ${result.estimated_cost_usd:.4f}")
    print(f"wall time:         {elapsed:.2f}s")
    print()

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "cross_dim_real_llm_stage3"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "cross-dim real-LLM Stage 3",
        "for_real": config.for_real,
        "config": {
            "prompt_variant": config.prompt_variant,
            "tool_variant": config.tool_variant,
            "recovery_variant": config.recovery_variant,
            "model": config.model,
            "n_tasks": config.n_tasks,
        },
        "result": {
            "completion_rate_pct": result.completion_rate_pct,
            "n_completed": result.n_completed,
            "total_api_calls": result.total_api_calls,
            "total_input_tokens": result.total_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "estimated_cost_usd": result.estimated_cost_usd,
        },
        "per_task_outcomes": result.per_task_outcomes,
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

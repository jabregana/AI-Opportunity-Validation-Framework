# Per-Dimension Runner Recipe

This doc is the step-by-step recipe for adding a new opportunity in a new dimension. The framework's existing per-dimension runners (canonicalization, GC, prompt, tools, policy, recovery) all follow this pattern. Copying one of them + adapting takes roughly 2-3 engineer-days.

## Why per-dimension runners exist

Each agent-system dimension has fundamentally different metric shapes (F1 vs completion rate vs latency vs token cost vs precision/recall), different gate definitions (UC-GC-1..5 vs UC-PROMPT-1..4 vs UC-REC-1..4), and different workload types. The framework explicitly does NOT unify them into a single configurable runner; that would push complexity into config parsing instead of removing it. See [`FRAMEWORK.md`](../FRAMEWORK.md) for the rationale.

Each runner is 200-450 lines, lives in `runner/<dim>_runner.py`, and owns its dimension's full pipeline: workload load, variant invocation, metric calculation, gate evaluation, artifact emission.

## The seven-step recipe

### Step 1: Define the variant ABC for your dimension

Create `runner/dimensions/<your_dim>/base.py` with an abstract base class describing the decision shape your variants will share.

```python
# runner/dimensions/observability/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TraceEvent:
    """One event in an agent trace."""
    timestamp: float
    span_id: str
    kind: str  # 'tool_call', 'llm_call', 'memory_read', ...
    payload: dict


class TraceSamplingVariant(ABC):
    """Variant decides whether to retain a trace event for analysis.

    The decision shape is dimension-specific: GC has should_collect(),
    prompt has render(), recovery has step_recover(). Observability
    has sample_trace(). Pick a verb that captures the dimension's
    actual decision.
    """

    name: str

    @abstractmethod
    def sample_event(self, event: TraceEvent) -> bool:
        """Return True to retain the event in long-term storage."""
        ...

    def __init__(self) -> None:
        pass
```

The framework's existing dimensions show the shape variation:
- `runner/dimensions/memory/lifecycle/base.py` has `should_collect(node_id, state, current_time)`
- `runner/dimensions/prompt/base.py` has `render(task_input) -> str`
- `runner/dimensions/recovery/base.py` has `step_recover(failure_context) -> recovery_action`

Pick a verb that names the actual decision the variant makes.

### Step 2: Implement candidate variants

Create one file per variant under `runner/dimensions/<your_dim>/`. Each file inherits from your ABC and implements the decision.

```python
# runner/dimensions/observability/b_keep_all.py
from .base import TraceSamplingVariant, TraceEvent


class KeepAllBaseline(TraceSamplingVariant):
    """Baseline: retain every event. The 'no GC' equivalent."""
    name = "b-keep-all"

    def sample_event(self, event: TraceEvent) -> bool:
        return True
```

```python
# runner/dimensions/observability/v0_1_0.py
from .base import TraceSamplingVariant, TraceEvent


class HeadSampler(TraceSamplingVariant):
    """v0.1.0: probabilistic head sampling at trace-start."""
    name = "obs-v0.1.0-head-sample"

    def __init__(self, p_keep: float = 0.1):
        super().__init__()
        self.p_keep = p_keep
        self._kept_traces: set[str] = set()

    def sample_event(self, event: TraceEvent) -> bool:
        # Keep all events from traces already decided to keep
        if event.span_id.split('.')[0] in self._kept_traces:
            return True
        # First event of a trace: probabilistic decision
        import hashlib
        trace_id = event.span_id.split('.')[0]
        h = int(hashlib.md5(trace_id.encode()).hexdigest()[:8], 16)
        keep = (h % 10000) / 10000.0 < self.p_keep
        if keep:
            self._kept_traces.add(trace_id)
        return keep
```

Register variants in `runner/dimensions/<your_dim>/__init__.py`:

```python
# runner/dimensions/observability/__init__.py
from .base import TraceSamplingVariant, TraceEvent
from .b_keep_all import KeepAllBaseline
from .v0_1_0 import HeadSampler


FACTORIES = {
    "b-keep-all": KeepAllBaseline,
    "obs-v0.1.0-head-sample": HeadSampler,
}


def build(variant_id: str) -> TraceSamplingVariant:
    if variant_id not in FACTORIES:
        raise KeyError(f"Unknown variant {variant_id!r}. Known: {sorted(FACTORIES)}")
    return FACTORIES[variant_id]()
```

### Step 3: Build a workload generator

Create `fixtures/workloads/w_<your_dim>.py` that generates synthetic data matching your dimension's shape. Per [`docs/benchmark-methodology.md`](benchmark-methodology.md), the generator should support multiple archetypes and accept a seed.

```python
# fixtures/workloads/w_traces.py
import random
from dataclasses import dataclass
from runner.dimensions.observability import TraceEvent


@dataclass
class TraceWorkload:
    archetype: str
    n_traces: int
    seed: int
    events: list[TraceEvent]


def generate(archetype: str, n_traces: int, seed: int) -> TraceWorkload:
    """Generate a trace workload of the requested archetype.

    Archetypes (from the standard library):
      - 'steady-state': constant rate, uniform trace length
      - 'bursty': 10x spike for 5% of duration
      - 'large-trace-dominated': heavy-tail trace length
      - 'high-mutation': 50% of traces are partial failures
      - 'cluster-rich': traces group into N topics
      - 'adversarial-no-skew': defeats head sampling specifically
    """
    rng = random.Random(seed)
    if archetype == "steady-state":
        events = [
            TraceEvent(timestamp=i * 0.1, span_id=f"trace_{i//10}.span_{i%10}",
                       kind="tool_call", payload={"tool": "search"})
            for i in range(n_traces * 10)
        ]
    elif archetype == "adversarial-no-skew":
        # Every trace has identical hash properties; head sampling
        # either keeps everything or nothing
        events = [
            TraceEvent(timestamp=i * 0.1, span_id=f"trace_AAAA.span_{i}",
                       kind="tool_call", payload={})
            for i in range(n_traces * 10)
        ]
    else:
        raise ValueError(f"Unknown archetype: {archetype}")
    return TraceWorkload(archetype=archetype, n_traces=n_traces, seed=seed, events=events)
```

### Step 4: Define the gates

Add a `compute_<your_dim>_gates()` function in your runner. Each gate is a calibrated pass/fail threshold:

```python
# (will live in runner/observability_runner.py, but defining the function shape here)

def compute_obs_gates(
    variant_result: dict,
    baseline_result: dict,
    *,
    uc_obs_1_min_storage_reduction_pct: float = 50.0,
    uc_obs_2_min_failure_recall: float = 0.95,
    uc_obs_3_max_p99_overhead_ms: float = 1.0,
) -> dict[str, dict]:
    """Compute UC-OBS gates for a sampling variant vs the keep-all baseline.

    UC-OBS-1: storage size reduction (% smaller than baseline)
    UC-OBS-2: failure recall (% of failed traces still observable)
    UC-OBS-3: write-path p99 latency overhead vs no-sampling
    """
    reduction = (
        100.0 * (baseline_result["bytes_stored"] - variant_result["bytes_stored"])
        / max(1, baseline_result["bytes_stored"])
    )
    uc1_pass = reduction >= uc_obs_1_min_storage_reduction_pct

    failure_recall = variant_result["failed_traces_kept"] / max(1, variant_result["failed_traces_total"])
    uc2_pass = failure_recall >= uc_obs_2_min_failure_recall

    overhead = variant_result["p99_overhead_ms"]
    uc3_pass = overhead <= uc_obs_3_max_p99_overhead_ms

    return {
        "UC-OBS-1": {"name": "storage reduction", "value": round(reduction, 2),
                     "threshold": uc_obs_1_min_storage_reduction_pct,
                     "status": "PASS" if uc1_pass else "FAIL",
                     "reason": f"reduced storage by {reduction:.2f}% (need >= {uc_obs_1_min_storage_reduction_pct}%)"},
        "UC-OBS-2": {"name": "failure recall", "value": round(failure_recall, 4),
                     "threshold": uc_obs_2_min_failure_recall,
                     "status": "PASS" if uc2_pass else "FAIL",
                     "reason": f"kept {failure_recall:.1%} of failed traces (need >= {uc_obs_2_min_failure_recall:.1%})"},
        "UC-OBS-3": {"name": "write-path p99 overhead", "value": round(overhead, 3),
                     "threshold": uc_obs_3_max_p99_overhead_ms,
                     "status": "PASS" if uc3_pass else "FAIL",
                     "reason": f"p99 overhead {overhead:.3f}ms (need <= {uc_obs_3_max_p99_overhead_ms}ms)"},
    }
```

Calibrate thresholds based on Stage 1 landscape findings, not aspirational targets. A gate that always passes is useless. A gate that never passes is also useless.

### Step 5: Build the runner

Create `runner/<your_dim>_runner.py` that takes a variant + workload, runs it, computes metrics, evaluates gates, and returns a result dict.

```python
# runner/observability_runner.py
from dataclasses import dataclass, field
import time
from typing import Any

from runner.dimensions.observability import TraceSamplingVariant
from fixtures.workloads.w_traces import TraceWorkload


@dataclass
class ObsRunResult:
    variant_name: str
    n_events_total: int
    n_events_kept: int
    bytes_stored: int           # approximate
    failed_traces_total: int
    failed_traces_kept: int
    p99_overhead_ms: float
    sample_seconds: float
    archetype: str


def run(variant: TraceSamplingVariant, workload: TraceWorkload) -> ObsRunResult:
    """Run variant against workload, return result."""
    n_kept = 0
    bytes_kept = 0
    failed_total = sum(1 for e in workload.events if e.payload.get("failed"))
    failed_kept = 0
    overheads = []

    t_start = time.time()
    for event in workload.events:
        t_sample_start = time.perf_counter()
        keep = variant.sample_event(event)
        t_sample_end = time.perf_counter()
        overheads.append((t_sample_end - t_sample_start) * 1000.0)
        if keep:
            n_kept += 1
            bytes_kept += len(str(event.payload)) + 64  # approx
            if event.payload.get("failed"):
                failed_kept += 1
    sample_seconds = time.time() - t_start

    overheads.sort()
    p99 = overheads[min(len(overheads) - 1, int(0.99 * len(overheads)))]

    return ObsRunResult(
        variant_name=variant.name,
        n_events_total=len(workload.events),
        n_events_kept=n_kept,
        bytes_stored=bytes_kept,
        failed_traces_total=failed_total,
        failed_traces_kept=failed_kept,
        p99_overhead_ms=p99,
        sample_seconds=sample_seconds,
        archetype=workload.archetype,
    )
```

The runner exists to be called from one or more experiment scripts. It should NOT do its own artifact emission, NOT do its own CLI parsing. Keep it pure: takes inputs, returns a structured result.

### Step 6: Write an experiment script that uses the runner + standardized artifact emission

The experiment script is what users actually run. It owns:
- CLI parsing
- Multiple seed runs (per [`docs/benchmark-methodology.md`](benchmark-methodology.md))
- Artifact emission via `emit_dimension_artifact()`
- Pre-registration block (when applicable for Stage 3+)

```python
# experiments/obs_v0_1_0_stage2.py
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fixtures.workloads.w_traces import generate
from runner.observability_runner import run, compute_obs_gates
from runner.dimensions.observability import build
from runner.artifacts import emit_dimension_artifact


def main():
    p = argparse.ArgumentParser(prog="obs-v0.1.0-stage2")
    p.add_argument("--archetype", default="steady-state",
                   choices=["steady-state", "bursty", "adversarial-no-skew"])
    p.add_argument("--n-traces", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42,
                   help="Workload seed (for multi-seed CI)")
    p.add_argument("--variant", default="obs-v0.1.0-head-sample")
    p.add_argument("--baseline", default="b-keep-all")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    workload = generate(archetype=args.archetype, n_traces=args.n_traces, seed=args.seed)

    variant = build(args.variant)
    baseline = build(args.baseline)

    variant_result = run(variant, workload)
    baseline_result = run(baseline, workload)

    gates = compute_obs_gates(
        variant_result=variant_result.__dict__,
        baseline_result=baseline_result.__dict__,
    )

    overall = "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL"

    emit_dimension_artifact(
        opportunity="observability",
        dimension="observability.trace_sampling",
        stage=2,
        experiment_name="obs-v0.1.0 head-sampling vs keep-all baseline",
        variants=[
            {"id": args.variant, "role": "candidate"},
            {"id": args.baseline, "role": "baseline"},
        ],
        workload={
            "archetype": args.archetype,
            "n": args.n_traces,
            "seed": args.seed,
            "params": {},
        },
        metrics={
            "variant_n_events_kept": variant_result.n_events_kept,
            "variant_bytes_stored": variant_result.bytes_stored,
            "variant_p99_overhead_ms": variant_result.p99_overhead_ms,
            "baseline_bytes_stored": baseline_result.bytes_stored,
            "storage_reduction_pct": gates["UC-OBS-1"]["value"],
            "failure_recall": gates["UC-OBS-2"]["value"],
        },
        gates=gates,
        decision=overall,
        environment={"python_version": "3.11+"},
        raw={
            "variant_result": variant_result.__dict__,
            "baseline_result": baseline_result.__dict__,
        },
        out_path=args.out,
    )


if __name__ == "__main__":
    main()
```

### Step 7: Write a Stage 1 finding doc

Before running the variant, write a Stage 1 landscape scan that establishes:
1. The wedge is real and not already shipped
2. Verification questions that need answering
3. The pre-registered metric and gate thresholds

See [`docs/opportunity-v0.2.x-graph-topology-gc.md`](opportunity-v0.2.x-graph-topology-gc.md) for an example.

After running, write a Stage 2 finding doc with the actual numbers. The finding doc lifecycle is the framework's primary artifact for credibility; see [`docs/benchmark-methodology.md`](benchmark-methodology.md) for the compliance checklist.

## Approximate effort per step

| Step | Time | Output |
|---|---|---|
| 1. Variant ABC | 1 hour | `dimensions/<dim>/base.py` |
| 2. Two candidate variants (baseline + first variant) | 2-3 hours | Two variant files + factory |
| 3. Workload generator with 2-3 archetypes | 3-4 hours | `fixtures/workloads/w_<dim>.py` |
| 4. Gate function | 2 hours | `compute_<dim>_gates()` |
| 5. Runner (pure functions) | 4-6 hours | `runner/<dim>_runner.py` |
| 6. Experiment script with standardized emission | 2-3 hours | `experiments/<dim>_stage2.py` |
| 7. Stage 1 finding doc | 4-6 hours | `docs/opportunity-<dim>.md` |
| Unit tests for variants + runner | 4-6 hours | `tests/test_<dim>_*.py` |

**Total: 2-3 engineer-days for the first variant + harness, then 1 day per additional variant.**

After Stage 2 numbers exist, the Stage 3+ work (real-data integration, multi-archetype matrix, multi-seed CIs) is another 1-2 weeks per [`docs/benchmark-methodology.md`](benchmark-methodology.md).

## What you can copy from existing runners

| You're building | Closest existing runner to copy |
|---|---|
| State-mutating sweep (GC-style, lifecycle, cleanup) | `runner/gc_runner.py` |
| Pure-function evaluation (prompt eval, output scoring) | `runner/prompt_runner.py` |
| Trace-based replay (recovery from failures, debugging) | `runner/recovery_runner.py` |
| Multi-stage agent decisions (policy, orchestration) | `runner/policy_runner.py` |
| Selection-from-options (tool routing, model routing) | `runner/tool_runner.py` |
| Cross-cutting joint experiments | `runner/cross_dim_runner.py` |
| Clustering / entity-canonicalization | `runner/canonicalization_runner.py` |

Don't try to be too clever about which runner to copy. The diffs after adaptation are usually large. The point of copying is to inherit the shape (returns a result dict, runs the variant against the workload, computes metrics), not to share code.

## Common pitfalls

1. **Trying to share too much across runners.** Each dimension's metrics legitimately differ. Don't force a base class. The framework's discipline is to copy and adapt, not to abstract prematurely.

2. **Skipping the workload archetype library.** Running on one workload hides architectural assumptions. The Graphiti v0.1.x finding (see [`finding-graphiti-f1-stage5.md`](finding-graphiti-f1-stage5.md)) is the canonical example. Build at least 3 archetypes from day one.

3. **Single-seed point estimates.** Per [`docs/benchmark-methodology.md`](benchmark-methodology.md), Stage 3+ findings require multi-seed CIs. Build the experiment script to accept `--seed` from day one even if Stage 2 uses a single seed.

4. **Putting CLI parsing in the runner.** The runner should be a pure function. The experiment script is where argparse lives.

5. **Forgetting to register the variant in the factory.** Test before benchmarking: `python -c "from runner.dimensions.<dim> import build; print(build('your-variant-id'))"`

## Pointers

- Existing dimensions: `runner/dimensions/{memory,prompt,tools,policy,recovery}/`
- Existing per-dim runners: `runner/{gc,prompt,recovery,policy,tool,cross_dim,canonicalization}_runner.py`
- Standardized artifact helper: `runner/artifacts.py::emit_dimension_artifact`
- Methodology standard: [`docs/benchmark-methodology.md`](benchmark-methodology.md)
- Framework narrative: [`FRAMEWORK.md`](../FRAMEWORK.md)
- Sample Stage 1 opportunity scan: [`docs/opportunity-v0.2.x-graph-topology-gc.md`](opportunity-v0.2.x-graph-topology-gc.md)
- Sample Stage 5 finding: [`docs/finding-mem0-f1-stage5.md`](finding-mem0-f1-stage5.md)

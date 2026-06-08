# Six-dimension agent-system architecture

This doc describes the architecture that lets one statistical harness measure an agent system across the six dimensions that define it: model, prompt, tools, memory, execution policy, and recovery behavior.

The narrowest framework claim is "a four-stage evaluation pipeline for one AI mechanism at a time." The bigger claim is "an agent system has six measurable dimensions and the same machinery applies to every one of them." This doc is the architectural commitment behind the bigger claim.

## The shape

```
runner/dimensions/
  base.py                    DimensionVariant ABC (marker base class)
  __init__.py                DIMENSIONS list, DimensionVariant export

  prompt/                    DIMENSION 2: prompt
    base.py                    PromptVariant ABC, render() decision
    b_noop.py                  DefaultPromptVariant (returns raw)
    __init__.py                FACTORIES + build()

  tools/                     DIMENSION 3: tools
    base.py                    ToolVariant ABC, ToolCall dataclass
                               available_tools() + should_allow_call()
    b_noop.py                  AllowAllToolVariant
    __init__.py                FACTORIES + build()

  policy/                    DIMENSION 5: execution policy
    base.py                    PolicyVariant ABC, AgentStep dataclass
                               next_step() decision
    b_noop.py                  SingleShotPolicyVariant (always finish)
    __init__.py                FACTORIES + build()

  recovery/                  DIMENSION 6: recovery
    base.py                    RecoveryVariant ABC, Failure +
                               RecoveryAction dataclasses
                               recover() decision
    b_noop.py                  AbortOnFailureVariant
    __init__.py                FACTORIES + build()
```

Two dimensions are not yet under `dimensions/` because they pre-date the architecture:

- **DIMENSION 1: model** lives in `experiments/ladder_sweep_real_data.py` (the multi-provider ladder that auto-routes by model-name prefix).
- **DIMENSION 4: memory** lives in `runner/variants/` (schema-alignment proxy) and `runner/gc_variants/` (real-time graph GC).

Migration is mechanical; see the bottom of this doc.

## The pattern every dimension follows

Every dimension package has exactly three files plus a registry:

1. **`base.py`** declares a dimension-specific ABC inheriting from `DimensionVariant`. It defines the decision method that variant implementations must override.
2. **`b_noop.py`** ships the no-op baseline. The baseline is the reference point for that dimension's UC gates; any non-trivial variant must show measurable gain over the baseline.
3. **`__init__.py`** exposes a `FACTORIES` dict (variant id -> no-arg factory) and a `build(variant_id)` helper. Same shape as `runner/variants/__init__.py`.

The dimension-specific Variant ABCs all inherit from `DimensionVariant`, a marker base class. The marker class provides two attributes (`name`, `dimension`) and zero behavior. It does not prescribe the decision interface; each dimension owns that.

### Decision interface per dimension

| Dimension | Decision method | Returns |
|---|---|---|
| Memory (canonicalization) | `align(input_relation)` | canonical bucket id |
| Memory (lifecycle / GC) | `should_collect(node_id, state, t)` | bool |
| Prompt | `render(task_input)` | prompt string |
| Tools | `available_tools(context)` + `should_allow_call(call, context)` | list[str] / bool |
| Policy | `next_step(history, context)` | `AgentStep` |
| Recovery | `recover(failure, context)` | `RecoveryAction` |
| Model | (no per-instance ABC; routed by name prefix in the ladder) | model handle |

Different decision shapes, same harness around them.

## Where the harness plugs in

The statistical harness (LORD++ FDR, paired bootstrap, CUPED, CI gates) does not care which decision method a variant exposes. It cares about per-trial outcomes (a value per case, with a baseline and a variant value). Every dimension produces those outcomes from its own decision:

- **Memory canonicalization:** the trial outcome is per-pair F1 (variant clustering vs ground-truth clustering).
- **Memory lifecycle:** the trial outcome is per-run UC gate values (UC-GC-1..4 in `runner/gc_runner.py`).
- **Prompt:** the trial outcome is per-task quality metric (answer correctness, format compliance, etc) given the rendered prompt.
- **Tools:** the trial outcome is per-task completion rate, latency, or cost given the gated tool set.
- **Policy:** the trial outcome is per-task completion rate or step count given the policy.
- **Recovery:** the trial outcome is per-failed-task recovery success rate given the recovery action.

For each, the harness compares the variant's outcomes against the dimension's no-op baseline using the same paired-bootstrap machinery. UC gates per dimension are defined in finding docs and become the pass/fail contract for that dimension's variants.

## Adding a new variant to an existing dimension

Four steps, mirroring how `RefCountGC` was added to `runner/gc_variants/`:

1. Add a new file in the dimension's package (e.g. `runner/dimensions/policy/react.py`).
2. Subclass the dimension's Variant ABC. Implement the decision method. Set `name`.
3. Register the factory in the dimension's `__init__.py`: add an entry to `FACTORIES`.
4. Add tests in `tests/test_<dimension>_variants.py` covering the decision method and any lifecycle hooks.

No changes to `dimensions/base.py`, no harness changes, no test-runner changes. The pattern carries.

## Adding a brand new dimension

Five steps. Not done in this commit; documented so the path is visible:

1. Pick the decision shape. Write the Variant ABC + supporting dataclasses in `runner/dimensions/<new>/base.py`.
2. Write the no-op baseline in `runner/dimensions/<new>/b_noop.py`.
3. Write `runner/dimensions/<new>/__init__.py` with `FACTORIES` and `build()`.
4. Add `<new>` to the `DIMENSIONS` list in `runner/dimensions/__init__.py`.
5. Run a Stage 1 opportunity scan against existing tools in that dimension's space (the `docs/opportunity-graph-gc.md` template).

Wedge selection, statistical machinery, and finding-doc culture stay the same.

## Migration plan for the two existing dimensions

`runner/variants/` and `runner/gc_variants/` are case studies that pre-date the architecture. They will move under `dimensions/memory/` in a separate commit (not bundled here because the rewrite touches 24 finding docs that reference the old paths).

Planned target layout:

```
runner/dimensions/memory/
  canonicalization/          (current runner/variants/)
    base.py                    Variant ABC (current; align() decision)
    b_raw.py                   BRawIdentity
    embed_proxy.py             ... etc
    per_source.py
    stub_proxy.py
    __init__.py                FACTORIES + build()
  lifecycle/                 (current runner/gc_variants/)
    base.py                    GCVariant ABC (current; should_collect() decision)
    b_raw.py                   BRawNoGC
    ref_count.py               RefCountGC, RefCountUtilityGC
    __init__.py                FACTORIES + build()
```

Backward-compat: `runner/variants/__init__.py` will re-export from the new location. `runner/gc_variants/__init__.py` will do the same. Existing import paths in tests, experiments, and finding docs keep working.

The migration is mechanical: `git mv` plus updating two `__init__.py` files. Postponed until the dimensions package has more than scaffolding (i.e., after the first real variant lands in one of the new dimensions), so the migration commit shows the architecture working with real cross-dimension code.

## What this commit changes

Before this commit, the six-dimension claim was a paragraph in `FRAMEWORK.md` and a row in a table. The repo's actual structure (`runner/variants/`, `runner/gc_variants/` as unrelated siblings) did not reflect the claim.

After this commit:

- `tree runner/` shows the architecture: `dimensions/{prompt,tools,policy,recovery}/` next to the existing `variants/` and `gc_variants/`.
- Four new Variant ABCs prove the pattern generalizes to non-memory dimensions.
- Four no-op baselines establish the reference point each dimension's UC gates will compare against.
- 27 new tests verify the factory registry, ABC contract, baseline behavior, and cross-dimension `DimensionVariant` typing.
- The FRAMEWORK.md scorecard moves from "2 strong, 1 partial, 3 not started" to "2 strong, 1 partial, 3 scaffolded with stubs."

The claim is now load-bearing on code, not just on prose.

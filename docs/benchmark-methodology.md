---
type: methodology-standard
date: 2026-06-09
status: AUTHORITATIVE
applies_to: every Stage 3+ benchmark across every dimension
---

# Benchmark Methodology Standard

This doc defines what a Stage 3+ benchmark in this framework must include to be defensible. It exists because a benchmark that looks good on its own data but falls apart under hostile review is worse than no benchmark at all. The framework's credibility comes from the Stage 3-to-Stage 4 self-correction story (see [`finding-substantial-N-revision.md`](finding-substantial-N-revision.md)) and the Graphiti F1 architectural finding (see [`finding-graphiti-f1-stage5.md`](finding-graphiti-f1-stage5.md)). Both of those caught real problems because the methodology forced multiple workloads, real data, and honest variance reporting. This doc captures that methodology as a checklist.

## The two failure modes that get benchmarks torn apart

Every benchmark survives or fails on two questions a hostile reviewer will ask:

1. **"Does this workload resemble the target deployment?"** Fixed by sourcing the workload from real telemetry/traces and validating that the synthetic version reproduces the source distributions.
2. **"Was the baseline tuned?"** Fixed by tuning the incumbent baseline as aggressively as the new variant before comparing.

Everything below is in service of those two questions. If a benchmark cannot answer both, it does not ship as a Stage 3 finding.

## The five problem areas

### 1. Workload realism

| Requirement | How to satisfy |
|---|---|
| Real-data input wherever possible | Use real corpora at Stage 3+. Existing examples: SQuAD validation subset (`experiments/gc_retrieval_f1_benchmark.py --use-squad`), Twitter Financial News (`experiments/case_study_expanded.py`). Reserve synthetic-only for Stage 2 pilot. |
| Library of distinct archetypes, not one mega-workload | Every Stage 3+ benchmark must run against AT LEAST three workload archetypes from the framework's archetype library (see "Workload archetype library" below). One workload hides architectural assumptions; the Graphiti F1 finding is the canonical example. |
| Edge / structural topology modeled for graph-native opportunities | When the opportunity touches graph structure (memory lifecycle, agent reasoning, dependency graphs), model: fan-out distribution, cross-region references, read/write ratio, churn rate. Do not treat the graph as a flat collection. |
| Adversarial archetype that stresses the new variant specifically | Every variant family ships with at least ONE workload designed to defeat its claimed advantage. v0.1.x had `w_graph_churn.py` with edge-removal events; v0.2.x needs an analog that creates rich connectivity with no supersession (the case that broke v0.1.x on Graphiti). |

#### Workload archetype library

The framework's standard archetypes. Every Stage 3+ benchmark runs at least three of these (one steady-state, one stress, one adversarial). New archetypes get added when an opportunity exposes a shape not yet covered.

| Archetype | Shape | Why it matters |
|---|---|---|
| **Steady-state** | Constant input rate, uniform fact distribution, no supersession | Baseline that all other archetypes deviate from |
| **Bursty** | 10x input spike for 5% of duration, then quiet | Tests sweep-cadence assumptions; reveals back-pressure issues |
| **Large-fact-dominated** | Heavy-tail size distribution (90% small, 10% are 100x larger) | Stresses memory-pressure logic and per-fact cost assumptions |
| **High-mutation / supersession-heavy** | 50% of facts get superseded within 10 days | Required to exercise temporal-validity rules; SQuAD does NOT have this shape |
| **Cluster-rich** | Facts form natural subgraph communities; queries target one cluster at a time | Tests subgraph-isolation and PPR-style rules |
| **Adversarial / variant-specific** | Designed to defeat the new variant's claimed advantage | Forces the variant to either handle the case or document it as out-of-scope |

### 2. Sourcing domain-specific data

In rough priority order:

| Source | What to extract | Status today |
|---|---|---|
| **Production telemetry (best)** | Allocation rate over time, object size histograms, survival rates, pause distributions, live-set size, promotion rates | Currently UNAVAILABLE: no customer pilot yet. The gating constraint between "research asset" and "product" |
| **Allocation / mutation traces (strongest realism)** | Full read/write events with timestamps, replay-able through the harness | Not yet collected; would require customer permission |
| **Snapshot / heap-dump mining** | Periodic graph state snapshots; reconstruct degree distributions, retained-size, type mix | Not yet collected |
| **Domain models fit to partial telemetry** | Parametric distributions (e.g., log-normal sizes, Weibull lifetimes, power-law fan-out) fit to whatever exists | PARTIALLY DONE: Mem0 LLM extraction amplification (1.68x) observed in the 2000-input smoke; this is the only formally-observed parameter |
| **Public / standard corpora as a sanity floor** | Established benchmark suites for cross-anchoring | PARTIALLY DONE: SQuAD + Twitter Financial News; LongMemEval and MemGPT-bench should be added |

**Validation step (critical):** after generating any synthetic workload, compare its aggregate statistics (alloc rate, size histogram, survival curve, edge-degree distribution) back against the source telemetry. A workload that does not reproduce the source distributions is not representative. Write a validation block in the finding doc that shows the comparison.

### 3. Volume sufficiency

| Requirement | Standard |
|---|---|
| Many GC cycles per run | Dozens of full sweeps minimum. Existing 2000-input Mem0 smoke = 20 sweeps; the F1 benchmarks = 1 sweep per config (acceptable for F1 measurement; insufficient for steady-state characterization). For new variants, the smoke run must exceed 20 sweeps. |
| Multiple store sizes | Each variant tested at AT LEAST 3 store-size points (e.g., 1x, 4x, 10x the warmup-converged live set). A single store size hides the headroom-tradeoff curve. |
| Multiple runs per config to characterize variance | Each headline metric reported with paired bootstrap CI from at least **3 seeded runs** with different random seeds. Single-run point estimates are NOT acceptable for Stage 3+ findings. |
| Explicitly discard warmup | First N adds (where the LLM extraction ramps up or the store reaches steady state) discarded from the artifact before computing aggregates. Warmup boundary documented per workload. |

### 4. Measurement rigor

| Requirement | Standard |
|---|---|
| Report distributions, not just averages | p50 / p95 / p99 / max for every latency, sweep cost, F1, reduction, and false-collection metric. Means alone hide tail behavior. |
| Trade-off frontier explicit | The artifact must include a Pareto-style table or chart showing the tradeoff between competing metrics (reduction vs F1, throughput vs sweep cost). A new variant ALWAYS wins one and loses another; show the whole frontier. |
| Confound control documented | Each artifact's JSON records: LLM model + version, embedder + dimensions, vector store + path, deterministic seed, machine + OS, neighboring processes (especially other Ollama jobs). The reproducibility of the Mem0 F1 numbers depends on this. |
| Fair baseline | Where an incumbent exists, tune the incumbent as aggressively as the new variant before comparing. Where no incumbent exists (current state for graph-native GC), the baseline is "no GC" and that is the correct comparison. Document the baseline-tuning decision in the artifact. |

### 5. Reproducibility & defensibility

| Requirement | Standard |
|---|---|
| Seeded / deterministic workload generation | Every workload generator accepts a `--seed` parameter. Default is 42. Multi-seed runs use {42, 123, 456} unless otherwise specified. |
| Variance + significance tests | `runner/metrics/stats.py::paired_bootstrap` applied to every cross-run metric. Report observed mean, 95% CI, and one-sided p-value vs baseline. A 3% improvement inside 8% run-to-run noise is not a result. |
| Pre-registration of metrics + workloads | Before running each variant, the finding doc must include a **pre-registration block** stating: metrics to measure, gate thresholds, decision rules. After running, do NOT change the gates. This is what separates a measurement from a self-flattering search. |
| Environment metadata captured | Kernel, hardware, Python version, package versions (frozen at run time), git commit hash, all alongside every artifact. The `runner/artifacts.py` module's three-block schema enforces this. |
| Immutable artifacts under `runs/` | Once written, NEVER edit a `runs/*.json` file. If a re-run is needed, write a new artifact and reference both in the finding doc. |
| Finding-doc immutability | Once a finding doc ships, NEVER silently edit its numbers. If they need correction, write a follow-up finding doc that supersedes it. The Stage 3-to-Stage 4 self-correction (`finding-substantial-N-revision.md`) is the canonical example. |

## Pre-registration template

Every Stage 3+ finding doc must include this block, **populated before the variant runs**:

```yaml
pre_registration:
  filed_at: <ISO timestamp>
  variant_under_test: <variant_id>
  baseline: <baseline_variant_id or "no-GC">
  workloads:
    - archetype: <one of: steady-state, bursty, large-fact, high-mutation, cluster-rich, adversarial>
      params: { n: <int>, seed: <int>, ... }
  primary_metrics:
    - name: <metric>
      direction: <higher_better | lower_better>
      pre_registered_threshold: <value>
      pre_registered_decision: <PASS_means_X | FAIL_means_Y>
  secondary_metrics: [ ... ]
  decision_rule: <free text describing what each combination of metric outcomes means>
  expected_run_time_minutes: <int>
```

After running, the finding doc reports:

```yaml
post_run:
  ran_at: <ISO timestamp>
  observed_run_time_minutes: <int>
  metrics:
    - name: <metric>
      observed: <value>
      ci_95: [<low>, <high>]
      vs_baseline_p_value: <float>
      meets_pre_registered_threshold: <bool>
  decision: <PASS | FAIL | NA>
  decision_reason: <free text>
```

The discipline here is that the post-run block's "decision" can ONLY use the pre-registered thresholds. A reviewer should be able to see the pre-registration and the post-run side by side and verify no gate was moved.

## Compliance checklist for new Stage 3+ benchmarks

Before a finding doc gets committed:

- [ ] Workload from real corpus OR validated against telemetry
- [ ] At least 3 archetypes from the standard library exercised
- [ ] At least one adversarial archetype designed to defeat the variant
- [ ] At least 3 seeded runs per config
- [ ] At least 3 store-size points
- [ ] Paired bootstrap CI on every headline metric
- [ ] p50 / p95 / p99 for every latency metric
- [ ] Pre-registration block filed before run
- [ ] Environment metadata captured in artifact JSON
- [ ] Confound-control decisions documented
- [ ] Validation block showing synthetic workload matches source distributions (when applicable)
- [ ] Fair baseline (tuned incumbent OR documented justification for no-GC baseline)
- [ ] Trade-off frontier explicit (table or chart showing competing metrics)

If any box is unchecked, the finding doc ships marked as PILOT or PARTIAL, not VALIDATED.

## What this doc changes

This methodology applies retroactively as the framework's standard. Existing Stage 3+ findings that pre-date this doc:

| Finding | Compliance status | What's missing |
|---|---|---|
| `finding-mem0-adapter-real-llm-stage5.md` (98.4% reduction, 2000-input smoke) | PARTIAL | Single seeded run; no CI; one workload archetype |
| `finding-mem0-f1-stage5.md` (revised 2026-06-09 to multi-seed: mean 83.8% F1 preservation, 95% CI [74.5%, 88.8%], pass-2-of-3 seeds) | COMPLIANT (multi-seed) but PARTIAL (single archetype) | Multi-seed CI now present; needs additional archetypes for full compliance |
| `finding-graphiti-f1-stage5.md` (0% reduction, three scenarios) | COMPLIANT-FOR-NEGATIVE | Three scenarios IS the multi-archetype check; the negative result is the finding |
| `finding-substantial-N-revision.md` (the 3B-vs-frontier self-correction) | COMPLIANT | This is the canonical example of why the methodology matters |
| `finding-gc-stage3-real-text.md` (Twitter 84.96% reduction) | PARTIAL | Single seed; needs CI |

The retroactive cleanup (adding CIs to existing single-seed numbers) is roughly half a day per finding. Worth doing for the headline numbers.

Going forward, no new finding doc ships without the compliance checklist green or explicit PILOT / PARTIAL marking.

## Pointers

- Statistical primitives: `runner/metrics/stats.py` (paired bootstrap)
- FDR control: `runner/fdr.py` (LORD++)
- Variance reduction: `runner/cuped.py` (CUPED)
- Artifact schema: `runner/artifacts.py`
- Existing workload generators: `fixtures/workloads/`
- The canonical self-correction: `docs/finding-substantial-N-revision.md`
- The canonical multi-archetype catch: `docs/finding-graphiti-f1-stage5.md`

# Experiments: Test Plan and Statistical Framework

Operationalized test plan for the proxy/middleware wedges identified in [opportunity.md](opportunity.md):

- **Niche 4 (primary): Schema Alignment Proxy.** Write-path middleware that aliases near-duplicate relations and properties before they hit a property graph.
- **Niche 3 (backup): Real-Time Graph GC.** Write-path or post-task middleware that reference-counts and evicts low-utility nodes and edges.

Both compete against the same incumbent stance: LLM-in-extraction-prompt (Mem0 v3) or no middleware at all (raw Neo4j or Memgraph). The experiments below are designed to do two things. First, prove the wedge with statistically defensible effect sizes. Second, gate every version N+1 release behind a regression gauntlet, so that progress is unambiguous.

## 0. Design priority: write latency vs merge accuracy

Two distinct concerns the proxy decouples on purpose.

**Write latency is a hot-path constraint** with a hard p99 kill switch at 100 ms (UC-4.6). Every ingestion pays the inner variant's cost: deterministic embedding plus cosine search. Across the variants currently shipped, p99 sits around 27-28 ms regardless of multi-tenant layering. No LLM in the hot path. No cross-source consensus computation on the write itself.

**Cross-source merge accuracy is a consolidation concern** that runs separately from writes. Multi-tenant variants (v0.4.0 through v0.4.2) accumulate cross-source intelligence through a `consolidate()` step. In production this step is a periodic background job: every 100 writes, every shift, every night, whatever cadence matches the operational tolerance for eventual consistency.

The harness implements consolidation between pass 1 (ingest) and pass 2 (re-query). A `drift_rate` metric records the fraction of writes whose pre-consolidation canonical differs from the post-consolidation canonical. This is the visibility tax of lazy consolidation; high drift means the system's view changed substantially during the consolidation.

Three drift types worth measuring (added or planned in the harness):

| Type | What it means | Where it surfaces |
|---|---|---|
| A. Pre/post consolidation prediction drift | Same write returns different canonical before vs after consolidation | UC-4.1 `drift_rate` diagnostic |
| B. Bad-write contamination | A wrong write tilts a merge decision; the bad merge propagates | Future UC: noise-injection workload |
| C. Order-dependence | Same writes in different orders produce different merges | Unit test (Adjusted Rand Index ≥ 0.9) |
| D. Consolidation cadence sensitivity | Different cadences produce different effective canonical spaces | Future analysis: parameter sweep |

This separation is the deliberate trade-off vs LLM-in-the-loop designs (Mem0 v3) that pay 500-2000 ms per write for what we accumulate offline.

## 1. Purpose, Scope, Non-Goals

**Purpose.** Establish a measurement harness so each prototype version produces an artifact (`runs/run-<uuid>.json`) that can be compared to all prior versions and to all baselines, with confidence intervals and pre-registered hypotheses.

**Scope.** Two products, thirteen use cases, one shared statistical protocol, one shared workload registry, one CI gauntlet.

**Non-goals.** End-user UX, marketing benchmarks, leaderboard chasing. The harness is private engineering infrastructure.

## 2. Workloads and Fixtures

Every experiment runs on a named, versioned workload. A workload is a deterministic stream of `(operation, payload, oracle_label)` triples replayable across variants. Workloads live under `fixtures/` with a manifest containing SHA-256 hashes.

| ID | Workload | Source | Volume | Oracle |
|----|----------|--------|--------|--------|
| W-LME-S | LongMemEval-S subset | LongMemEval (Xu et al., 2024) | 500 sessions | Annotated relation and entity ground truth |
| W-MEM0-EXP | Mem0 v3 production-style export | Synthetic via Mem0 v3 SDK on a public chat corpus | 10k memories | Self-consistency oracle |
| W-WIKIDATA-100K | WikiData property-alias dump | WikiData dumps (property aliases and labels) | 100k aliased relation pairs | WikiData's own alias structure |
| W-CONCEPTNET-REL | ConceptNet relation set | ConceptNet 5.7 | 34 canonical relations plus LLM-paraphrased synonyms | Canonical relation per row |
| W-CHURN-30D | Synthetic high-churn agent log | Generator script | 30-day stream, ~50 ops/min | Lifetime label per node (kept or evicted) |
| W-LATENCY-ZIPF | Latency load test | Zipfian relation distribution generator | 1M writes, configurable QPS | None (throughput only) |

WikiData and ConceptNet give external oracles for schema alignment that no incumbent can game. LongMemEval is the only public memory benchmark with annotated facts. The synthetic generators allow controlled distributional shifts to stress edge cases.

Only `W-CONCEPTNET-REL` is implemented as of this writing. The other five workloads are status-stubs in `fixtures/manifest.json`.

## 3. Use Cases: Schema Alignment Proxy (Niche 4)

Each use case specifies fixture, operation, expected outcome, observables, primary metric, and guardrails. The primary metric is the one a hypothesis test runs on. Guardrails are pass/fail thresholds that disqualify a run regardless of the primary metric.

### UC-4.1: Synonymous Relation Aliasing

- Fixture: W-WIKIDATA-100K, W-CONCEPTNET-REL.
- Operation: stream relation writes; the proxy must alias near-duplicates (`EMPLOYED_BY` to `WORKS_AT`) before write.
- Expected outcome: a canonical relation set whose cardinality matches the oracle's canonical count within a small margin.
- Observables: per-write alias decision `(input_relation, chosen_canonical, similarity_score, latency_ms)`.
- Primary metric: pairwise clustering F1 versus oracle equivalence classes.
- Guardrails:
  - Cross-canonical merge rate at most 1%. Fraction of merges that group inputs whose oracle canonicals differ. This is the semantic-over-clustering gate. It directly penalizes "things that look similar but aren't" and applies on the full workload, not a curated set.
  - Cluster diversity at least 0.8. Computed as `|distinct_predicted_canonicals| / |distinct_oracle_canonicals|`. Prevents the trivial all-into-one-bucket attack on F1.
  - p95 added latency under 50 ms.

### UC-4.2: Property Key Normalization

- Fixture: W-MEM0-EXP enriched with property-key paraphrase pairs (`email_address` paired with `email`, `birth_date` paired with `dob`).
- Operation: property writes routed through the proxy.
- Primary metric: key-alignment precision at 0.95 recall. Report the area under the precision portion of the precision-recall curve where recall is at least 0.95.
- Guardrails: zero data loss. Every input value must be retrievable by either the input key or the canonical key.

### UC-4.3: Entity Surface-Form Merging

- Fixture: WikiData entity-alias subset (`IBM` paired with `International Business Machines Corporation`).
- Operation: entity node writes through the proxy.
- Primary metric: pairwise merge accuracy using B-cubed precision and recall (Bagga and Baldwin, 1998). Standard for coreference clustering.
- Guardrails: no incorrect cross-type merges. A `Person:IBM` engineer must not merge with `Org:IBM`.

### UC-4.4: Adversarial False-Positive Resistance

- Fixture: two-tier adversarial set.
  - Tier A (curated): 200 hand-labeled pairs of relations that look similar but are semantically distinct (`CONTAINS` set-membership vs `INCLUDES` text-substring; `OWNS` vs `LEASES`; `LOCATED_IN` vs `LOCATED_NEAR`).
  - Tier B (generative): a programmatic generator that mines hard negatives. For each oracle canonical, take its top-K nearest neighbors in embedding space restricted to a held-out vocabulary, then keep only pairs whose surface-form-pair embedding cosine is at least 0.85 and whose oracle canonicals differ. Regenerated per release, SHA-pinned per run.
- Operation: same as UC-4.1.
- Primary metric: false-merge rate, stratified by tier. Report Tier A and Tier B separately; the union is the headline number.
- Guardrails:
  - Tier A false-merge rate at most 1% (tightened from 2% because the curated set is small enough to fully audit).
  - Tier B false-merge rate at most 3% (programmatic set is noisier but stress-tests the proxy's worst case).
  - Both are kill switches. A regression on either blocks release regardless of other gains.

### UC-4.5: Distributional Drift Recovery

- Fixture: W-CHURN-30D with a planted regime change at day 15 (new vocabulary domain replacing the old; for example, medical relations replacing finance).
- Operation: stream the 30-day workload. The proxy's canonical store evolves.
- Primary metric: time-to-stable-alignment after the regime change. Writes until alignment F1 recovers within 95% of pre-change steady state.
- Guardrails: no alignment collapse during transition. Per-window F1 never below 0.6 for more than 2 windows.

### UC-4.6: Latency Budget Under Load

- Fixture: W-LATENCY-ZIPF.
- Operation: sustained writes at increasing QPS (100, 500, 1k, 5k).
- Primary metric: p95 and p99 added latency versus raw write, with throughput ceiling (the QPS at which p99 exceeds 100 ms).
- Guardrails: p99 under 100 ms at 1k QPS; throughput ceiling at least 5x the LLM-baseline ceiling.

### UC-4.7: Downstream Retrieval Preservation

This use case exists because UC-4.1's F1 measures cluster shape against an oracle. UC-4.4 stress-tests known hard negatives. Neither directly proves the proxy did not subtly corrupt the graph in a way that hurts the downstream task. This use case closes that loop.

- Fixture: W-LME-S with the proxy interposed during the memory-ingestion phase. Canonical retrieval queries run after ingestion.
- Operation: same workload run twice, once with the proxy and once without (B-RAW), into the same graph backend. The same query set is replayed against both graphs.
- Primary metric: Δ retrieval F1@10, defined as F1@10 (with proxy) minus F1@10 (no proxy), per query, bootstrapped.
- Non-inferiority hypothesis: the proxy must not reduce downstream F1@10 by more than δ = 0.01 (one-sided 95% CI lower bound above -0.01).
- Guardrails: per-query F1@1 delta at least -0.02. Zero queries whose F1@10 drops to 0 because the proxy collapsed all relevant relations into a wrong canonical.

## 4. Use Cases: Real-Time Graph GC (Niche 3)

### UC-3.1: Reference-Counting Correctness

- Fixture: synthetic graph with controlled edge insert and delete sequences.
- Primary metric: correctness rate. Fraction of nodes correctly evicted exactly when their refcount drops to zero (binary per node).
- Guardrails: zero false evictions. A node with refcount above zero must never be evicted.

### UC-3.2: Utility-Score Eviction Ranking

- Fixture: W-CHURN-30D with oracle "used-in-retrieval" labels per node.
- Primary metric: NDCG@k of eviction ordering versus oracle utility ranking, where k is the budget-bounded eviction batch size.
- Guardrails: no high-utility node (top 10% by oracle) evicted.

### UC-3.3: Steady-State Graph Size Bound

- Fixture: W-CHURN-30D.
- Primary metric: bounded growth. Fit `nodes(t) = α + β·t`; require β at or below a small epsilon after warmup. The graph must approach a steady-state size.
- Guardrails: final graph size at most 2x the working-set lower bound (computed from oracle).

### UC-3.4: Longitudinal Recall Preservation

A single before/after recall snapshot misses slow degradation. The GC can look fine on day 1 and quietly erode old-but-still-relevant facts by day 60. This use case replaces a previous one-shot version with a longitudinal measurement.

- Fixture: W-CHURN-30D extended to 90 days, with a query set whose target facts are stratified by age bucket (under 7 days, 7 to 30 days, 30 to 60 days, 60 to 90 days).
- Operation: run the GC continuously over the 90-day stream. At each checkpoint t in {7, 14, 30, 60, 90} days, replay the full query set against the current graph and the same-state B-RAW baseline.
- Primary metric: recall@10 at t=90d versus B-RAW, bootstrapped. Headline.
- Per-checkpoint guardrails: recall@10 at every t at or above B-RAW recall@10 minus 0.02. Recall@1 at every t at or above B-RAW minus 0.01.
- Per-age-bucket guardrail: recall on the 60–90d bucket at or above B-RAW recall on that bucket minus 0.05. Directly tests whether the GC catastrophically forgets old facts.
- Diagnostic: monotonicity test. The slope of `recall(t)` over `t` must not be more negative than B-RAW's slope by a statistically detectable margin (one-sided Wilcoxon on per-checkpoint deltas).

### UC-3.5: Write-Path Latency Overhead

- Fixture: W-LATENCY-ZIPF.
- Primary metric: p95 and p99 added latency with GC running.
- Guardrails: p99 GC overhead at most 15 ms at 1k QPS.

### UC-3.6: Memory Survival Analysis

Even if average recall holds (UC-3.4), individual facts may have very short lifetimes once their utility dips. That is a problem for any agent that needs to reference cold knowledge later. Survival analysis quantifies this directly.

- Fixture: W-CHURN-30D (90-day extension) with each fact tagged `oracle_utility` in {top 10%, middle 80%, bottom 10%}.
- Operation: for each fact, observe survival (recallable via retrieval) at fixed intervals. Right-censor facts that survive past the 90-day window.
- Primary metric: Restricted Mean Survival Time (RMST) difference up to t=90d, per utility bucket. Defined as `RMST_variant - RMST_B-LLM`. Interpretable as "facts in this bucket survived X days longer (or shorter) under our variant." Bootstrap CI on per-stratum RMST_diff (Royston and Parmar, *Statistics in Medicine*, 2013).
- Why not log-rank as primary: the log-rank test requires proportional hazards. The relative eviction probability between the GC and B-LLM must be constant over time. A real GC almost certainly violates this; noise gets pruned in early bursts (high early hazard), while core facts survive indefinitely (low late hazard). Under PH violations, log-rank loses power and can produce misleading p-values. RMST sidesteps the assumption and yields an interpretable units-of-time metric.
- Diagnostic: log-rank is retained alongside Kaplan-Meier curves to flag obvious distributional differences but does not gate the decision. A KM plot per utility bucket is part of every nightly artifact.
- Secondary metric: median half-life per bucket, as a sanity check (computable only when at least 50% of bucket facts are uncensored at 90 days).
- Guardrails:
  - Top 10% utility bucket: RMST at least 30 days. Hard floor; high-utility facts should retain on average through the first month of the window.
  - Bottom 10% bucket: `RMST_diff` at most -18 days (variant's RMST is at least 18 days shorter than B-LLM's). Inverse guardrail. The GC must forget low-utility faster than B-LLM, otherwise it provides no compaction benefit.

## 5. Statistical Framework

### 5.1 Baselines

Every variant is compared, paired on fixture, against three baselines:

- **B-RAW.** No proxy, raw graph backend. Establishes the capability cost.
- **B-LLM.** Mem0 v3-style LLM-in-extraction-prompt resolver. Establishes incumbent parity.
- **B-VPREV.** The previous proxy version (last green commit). Establishes the regression gate.

All comparisons are paired: same fixture, same RNG seed, same query stream.

### 5.2 Hypothesis Testing per Metric Type

| Metric shape | Test | Why |
|--------------|------|-----|
| Paired continuous, normality not assumed (latency, recall delta) | Paired bootstrap on the mean difference, 10k resamples, BCa CI | No distributional assumptions; robust to outliers; produces CIs that can be plotted |
| Paired binary ("correctly aliased y/n") | McNemar's exact test on the discordant cells | Standard for paired binary outcomes |
| Paired ordinal or heavy-tailed continuous (p99 latency) | Wilcoxon signed-rank | Distribution-free, more powerful than t-test on skewed data |
| Count or Poisson (false-merge events per 1k writes) | Poisson exact test on the rate ratio | Correct null for count data |
| Ranking (NDCG@k) | Bootstrap CI on per-query NDCG, paired across variants | Per-query is the unit; queries are i.i.d. |
| Time-to-event (UC-4.5 stabilization) | Stratified log-rank across regime-change replicates | Standard survival comparison |

### 5.3 Effect Sizes, MDE, and Non-Inferiority Margins

For every primary metric, pre-register both:

- The MDE (minimum detectable effect) for superiority claims, sized so the powered test can detect a real improvement versus baseline.
- The non-inferiority margin δ for regression claims, the tolerable degradation explicitly tested in the gauntlet.

δ is tighter than MDE because "we didn't regress by an amount we couldn't have detected anyway" is not a real safety claim. Default: δ = 0.25 × MDE for nightly gates, δ = 0.5 × MDE for fast-tier PR gates (Section 6.2 explains the two-tier design).

| Metric | MDE (superiority) | δ (nightly NI margin) | Rationale |
|--------|-------------------|------------------------|-----------|
| Pairwise F1 (UC-4.1) | +0.05 | 0.0125 | Headline alignment quality |
| Cross-canonical merge rate (UC-4.1 guardrail) | n/a (one-sided floor) | absolute 0.005 | Direct semantic-over-clustering signal |
| Property key precision at 0.95 recall (UC-4.2) | +0.03 | 0.0075 | Tight because false aliasing damages downstream |
| Tier A false-merge rate (UC-4.4) | +0.005 | absolute 0.002 | Kill switch; δ tighter than MDE |
| Tier B false-merge rate (UC-4.4) | +0.01 | absolute 0.005 | Programmatic stress; noisier |
| Δ retrieval F1@10 (UC-4.7) | n/a (NI primary) | 0.01 | The whole UC is a non-inferiority test |
| p95 latency (UC-4.6, UC-3.5) | 5 ms | 2 ms | Below typical jitter floor |
| NDCG@k eviction (UC-3.2) | +0.02 | 0.005 | Standard NDCG MDE in IR literature |
| Recall@10 at t=90d (UC-3.4) | 0.02 | 0.01 | Longitudinal; δ tighter than per-checkpoint guardrail |
| Half-life ratio (UC-3.6) | 0.1 ratio | 0.05 ratio | Survival analysis on stratified buckets |

Sample-size formula for the paired bootstrap case. Use the observed paired SD from a 200-sample pilot to compute `N ≥ (z_{α/2} + z_β)² · σ_d² / MDE²` for superiority and `N ≥ (z_α + z_β)² · σ_d² / δ²` for non-inferiority (one-sided). The non-inferiority N is roughly 4x larger than the previous spec's implied N. Accept the cost, pick a wider δ explicitly, or apply CUPED (Section 5.6), but do not retain the underpowered "0.5 of MDE as blocker" rule.

### 5.4 Multiple Comparisons under Sequential Peeking (Online FDR)

A full release evaluation now runs 13 primary tests (7 UC-4 plus 6 UC-3), plus dozens of intermediate variant comparisons during dev iteration. The set of tested hypotheses is therefore unbounded and revealed sequentially, not a fixed batch.

Vanilla Benjamini-Hochberg is invalid here. BH assumes the full p-value vector is known before adjustment. Reapplying BH at every new test inflates FDR. Concretely: if BH has been run 10 times on growing vectors and stopped when one came up significant, the effective false discovery rate is no longer q.

Replace BH with online FDR control:

- **LORD++** (Ramdas, Yang, Wainwright, Jordan, "Online control of the false discovery rate with decaying memory," NeurIPS 2017; the ++ refinement in Javanmard and Montanari, *Annals of Statistics*, 2018) is the default. It maintains an alpha-wealth budget `W_n` and tests each new hypothesis at level `α_n = γ_n · W_0 + extra wealth from prior rejections`, with `γ_n ∝ 1 / (n · log²(max(n, 2)))` so the discount sequence sums to 1. Provably controls FDR at or below q under independent or positively-correlated p-values.
- **SAFFRON** (Ramdas, Zrnic, Wainwright, Jordan, ICML 2018) is the alternative when nulls are conservative or many hypotheses are obvious nulls. It estimates the null proportion online and recovers wealth faster.
- **ADDIS** (Tian and Ramdas, NeurIPS 2019) for cases where many candidate tests get discarded by the analyst before formal evaluation.

Default in the harness: LORD++ at q = 0.10. Wealth recharge `b_0 = q / 2 = 0.05`; initial wealth `W_0 = q / 2 = 0.05`.

Guardrails remain outside the FDR family. Each kill switch is its own pre-registered one-sided test at α = 0.01.

**Test ordering is prescriptive, not incidental.** LORD-family algorithms allocate alpha-wealth `γ_n` monotonically down the sequence. Tests scheduled late get a smaller budget and suffer Type II inflation. To prevent critical metrics from being starved, the harness fixes the `test_seq_id` order by business priority and historical variance:

| Position | Tier | Tests | Rationale |
|----------|------|-------|-----------|
| 1 to 5 | Kill switches and highest-stakes NI | UC-4.4 Tier A, UC-4.1 cross-canonical merge, UC-4.7 downstream retrieval, UC-3.4 60–90d age bucket recall, UC-3.6 top-10% RMST floor | High alpha allocation for tests where missing a real regression is most costly. |
| 6 to 10 | Primary capability metrics | UC-4.1 pairwise F1, UC-4.2 property key precision, UC-4.3 entity B-cubed, UC-3.2 NDCG eviction, UC-3.1 refcount correctness | Headline numbers; meaningful Type II budget but not the kill switches. |
| 11 to 13 | Stable / secondary | UC-4.6 latency, UC-3.5 latency, UC-3.3 bounded-growth slope | Low historical variance; can tolerate smaller alpha because effects are typically large when real. |

Nightly-only tests (UC-4.5 drift recovery, additional UC-3.4 checkpoints) continue the same ledger after the fast tier completes; their `test_seq_id` starts at 14.

**SAFFRON fallback trigger.** If the rolling 30-day null proportion (fraction of hypotheses with `outcome != REJECT`) exceeds 0.7, the harness switches the next release cycle to SAFFRON. SAFFRON estimates the null proportion online and recovers alpha-wealth faster when most tests fail to reject. That is the regime where LORD++ becomes underpowered.

### 5.5 Sequential and Always-Valid Analysis (Within-Test Peeking)

Section 5.4 controls FDR across the sequence of hypotheses. Inside any one hypothesis, a fixed-N test still inflates type-I error if you peek at the metric before N is reached.

Use always-valid confidence sequences (Howard, Ramdas, McAuliffe, Sekhon, "Time-uniform, nonparametric, nonasymptotic confidence sequences," *Annals of Statistics*, 2021) for per-hypothesis monitoring. These CIs are valid at every sample size simultaneously, so stop-when-significant does not inflate α.

The two compose. Each hypothesis is monitored with an always-valid CI. The decision to declare significance (and add a rejection event to the LORD++ ledger) is gated by that CI excluding zero in the pre-registered direction.

Implementation: the harness emits a CI after every batch of N=100 paired samples within a hypothesis. Stop when the always-valid CI excludes the relevant non-inferiority margin (for regression tests) or zero (for superiority tests), or when N reaches the pre-registered cap. Then submit the rejection event to the online FDR ledger.

### 5.6 Variance Reduction

To get tighter CIs without growing N:

- **Common Random Numbers (CRN).** Same seeds across variants. The paired design exploits this directly.
- **Stratified sampling** by relation-frequency bucket (head, torso, tail) so each bucket contributes proportionally.
- **CUPED** (Deng, Xu, Kohavi, Walker, KDD 2013). Covariate adjustment using pre-experiment metrics. The recommended baseline covariate is the per-item metric value from B-VPREV (last green commit), measured on the same item before the variant ran. CUPED-adjusted variant metric: `Y' = Y - θ(X - E[X])` where `X` is the B-VPREV covariate and `θ = Cov(Y, X) / Var(X)` minimizes `Var(Y')`. The variance reduction factor is `ρ²` where ρ is the Pearson correlation between variant and baseline. For file-memory systems tracking structured items across versions ρ routinely exceeds 0.55, securing the target 30% reduction. That substantially offsets the 4x N inflation from the Section 5.3 non-inferiority sample-size formula. A 30% σ² reduction takes the NI N from 4x back to roughly 2.8x of the superiority N. The harness applies CUPED automatically whenever a B-VPREV artifact exists for the (workload, metric) pair and passes the 14-day lookback cap in Section 6.4.3. Without it the tightened NI gauntlet would be cost-prohibitive at scale. Implementation: `runner/cuped.py`.

## 6. Experimental Design

### 6.1 Run Artifact

Every experiment writes one JSON file with three top-level blocks (`artifact_metadata`, `sequential_fdr_ledger`, `test_executions[]`) capped by a `pipeline_decision`. Artifacts go to `runs/` and are immutable. Comparisons are computed across artifacts post hoc; no in-place mutation.

```json
{
  "artifact_metadata": {
    "run_id": "<uuid>",
    "git_sha": "...",
    "variant": "schema-proxy-v0.3.1",
    "baseline": "B-VPREV@<sha>",
    "workload_id": "W-WIKIDATA-100K",
    "workload_sha": "sha256:...",
    "timestamp_utc": "2026-06-05T21:05:00Z",
    "tier": "fast"
  },
  "sequential_fdr_ledger": {
    "algorithm": "LORD++",
    "ledger_scope": "per_release",
    "target_q": 0.10,
    "gamma_schedule": "0.4412 / (n * log2(n+1)^2)",
    "initial_wealth": 0.05,
    "current_wealth": 0.043,
    "prior_rejections": [
      {"test_seq_id": 1, "metric_id": "uc_4_1_cross_canonical_merge"}
    ]
  },
  "test_executions": [
    {
      "test_seq_id": 1,
      "use_case": "UC-4.1",
      "metric_id": "cross_canonical_merge_rate",
      "type": "guardrail_kill_switch",
      "statistical_test": "Poisson_exact_one_sided",
      "alpha_allocated": 0.01,
      "point_estimate": 0.004,
      "guardrail_threshold": 0.01,
      "always_valid_ci_upper": 0.009,
      "p_value": 0.0012,
      "outcome": "PASS"
    },
    {
      "test_seq_id": 2,
      "use_case": "UC-4.7",
      "metric_id": "delta_retrieval_f1_at_10",
      "type": "non_inferiority",
      "statistical_test": "paired_bootstrap_cuped_adjusted",
      "cuped_covariate": "f1_at_10_under_b_vprev",
      "cuped_variance_reduction": 0.31,
      "ni_margin_delta": 0.01,
      "alpha_allocated": 0.014,
      "point_estimate": 0.003,
      "always_valid_ci_lower": -0.004,
      "p_value_one_sided": 0.034,
      "outcome": "REJECT_NULL_NON_INFERIOR"
    }
  ],
  "pipeline_decision": "PASS_AND_MERGE"
}
```

`outcome` enum:

- `PASS` or `FAIL` for guardrail kill switches and floors (observed within or outside threshold).
- `REJECT_NULL_NON_INFERIOR` or `FAIL_TO_REJECT_NI` for non-inferiority tests.
- `REJECT_NULL_SUPERIOR` for one-sided superiority tests.
- `INCONCLUSIVE` for insufficient N to power the pre-registered margin. Treated as a fail by Section 6.2.

`pipeline_decision` enum: `PASS_AND_MERGE`, `BLOCK_PR`, `SOFT_REGRESSION_OPENED`, `INCONCLUSIVE`.

Implementation: `runner/artifacts.py` emits this schema as of commit `4445048`. The LORD++ ledger is populated automatically from `runner/fdr.py`. INCONCLUSIVE-is-FAIL gating is wired per Section 6.4.1.

### 6.2 CI Regression Gauntlet (Non-Inferiority)

A previous version of this spec used a rule "BH-adjusted p ≤ 0.05 AND point estimate worse by ≥ 0.5 × MDE." That rule was underpowered: 0.5 × MDE is half the effect we sized N to detect, so we could not reliably catch regressions at the threshold we were blocking on.

Replace with explicit non-inferiority testing per Section 5.3 margins. For each primary metric the gauntlet tests:

> H_0: `μ_variant - μ_VPREV ≤ -δ` vs H_1: `μ_variant - μ_VPREV > -δ`

with a one-sided always-valid CI (Section 5.5). Reject H_0 (declare non-inferior) when the lower bound of the variant-minus-VPREV CI exceeds -δ. Submit the rejection event to the LORD++ ledger.

Two-tier design:

| Tier | When | δ | Action on NI failure |
|------|------|---|----------------------|
| Fast | Every PR (~5 min) for UC-4.1, UC-4.4, UC-4.7, UC-4.6, UC-3.4 90d checkpoint, UC-3.5 | 0.5 × MDE | Hard block. PR cannot merge. |
| Nightly | Every commit on main (~30 min) for all 13 UCs | 0.25 × MDE | Soft regression. Surfaces in the daily report, auto-opens an issue, does not auto-revert. |

Kill-switch guardrails (UC-4.4 false-merge tiers, UC-4.1 cross-canonical merge, UC-3.4 per-age-bucket recall, UC-3.6 top-10% RMST floor) remain hard blocks at α = 0.01 on both tiers.

A PR is blocked if any of: a kill switch fails, a fast-tier NI test fails, or `N_fast < required N_NI(δ_fast)` from the pilot σ_d. Under-sampling is treated as a fail, not a pass.

### 6.3 Pre-registration

Before any experimental claim that goes into a writeup or pitch deck:

1. Open an entry in `runs/registry.md` with hypothesis, metric, MDE, planned N, primary test, stop rule.
2. Run.
3. Append the run_id to that entry.

No post-hoc cherry-picking. If a hypothesis changes mid-run, the analysis is exploratory, not confirmatory. Label it as such in the writeup.

### 6.4 CI/CD Edge-Case Guardrails

Three operational policies that bulletproof the LORD++ and NI and CUPED machinery against the actual failure modes of an automated pipeline. Implemented in `runner/gates.py`.

**6.4.1: INCONCLUSIVE-is-FAIL on the fast PR tier.** If an upstream infra failure causes a run to drop below its power-driven sample size N, the test must not pass by default. Any `outcome: INCONCLUSIVE` on the fast tier is treated exactly as FAIL for gating purposes. Stops corrupted, low-sample runs from sneaking through the gate due to a lack of data. The nightly tier is more permissive; INCONCLUSIVE there opens an issue and does not block.

**6.4.2: SAFFRON hot-swap trigger.** If the rolling 30-day true-null proportion π_0 (fraction of hypotheses across all runs with `outcome != REJECT_*`) exceeds 0.70, the harness flags the next release cycle to swap LORD++ for SAFFRON. In the sparse-rejection regime LORD++ continuously starves down-sequence tests of alpha-wealth because rejections (which top up wealth) are rare. SAFFRON estimates π_0 online and uses an explicit alpha-discarding threshold λ to claw back wealth from non-significant results, restoring power in exactly this regime.

**6.4.3: B-VPREV lookback cap (14 days).** CUPED is only useful when the variant-to-baseline correlation ρ is high. ρ degrades when the underlying codebase has drifted structurally between the variant and the B-VPREV snapshot. Hard cap: if the B-VPREV artifact is older than 14 days, the harness disables CUPED for the run and falls back to unadjusted variance estimation. This means the NI gauntlet needs more data to clear, which is the correct behavior. Better to require more samples than to silently compute against a stale baseline.

| Gate | Trigger | Action |
|------|---------|--------|
| INCONCLUSIVE-is-FAIL | Any INCONCLUSIVE outcome on fast tier | Block PR |
| SAFFRON hot-swap | Rolling 30d π_0 > 0.70 | Flag next release cycle; surface in nightly report |
| B-VPREV lookback | `now - B-VPREV.timestamp_utc > 14d` | Disable CUPED for this run; recompute N requirement |

### 6.5 Drift Monitoring (Post-Launch)

- Population stability index (PSI) on the input relation distribution between current week and the registered fixture. PSI above 0.25 means the fixture is stale; schedule a refresh.
- Canary metric in production: per-day alignment-disagreement rate with a 1% LLM-oracle sample. Drift alarm if the 7-day rolling mean exceeds 2x the experimental baseline.

## 7. Success Ladder

Pre-define what "good enough" looks like at each phase so we do not move goalposts.

| Phase | Niche 4 bar | Niche 3 bar |
|-------|-------------|-------------|
| Alpha (internal demo) | UC-4.1 F1 at or above B-LLM minus 0.05; UC-4.1 cross-canonical merge at or below 2%; UC-4.7 Δ F1@10 at or above -0.02; UC-4.6 p99 at or below 50 ms at 100 QPS | UC-3.1 correctness 1.00; UC-3.4 recall@10 at t=30d at or above B-RAW minus 0.03 |
| Beta (design partner) | UC-4.1 F1 NI versus B-LLM (one-sided lower CI above -δ); UC-4.4 Tier A at or below 1%, Tier B at or below 3%; UC-4.7 Δ F1@10 NI at δ=0.01; UC-4.6 p99 at or below 30 ms at 1k QPS | UC-3.2 NDCG at or above 0.75; UC-3.3 β at or below epsilon; UC-3.4 90d-checkpoint NI versus B-RAW; UC-3.6 top-10% half-life at or above 30d; UC-3.5 p99 at or below 15 ms at 1k QPS |
| GA | All UC-4 primary metrics statistically at or above B-LLM under LORD++ at q=0.10; all kill switches green for 30 consecutive nightly runs; no soft-regression issue open older than 7 days | Same standard for UC-3, plus UC-3.6 bottom-10% half-life shorter than B-LLM by at least 20% (the inverse guardrail; we must actually compact, not just preserve) |

## 8. Open Questions

- Is the W-WIKIDATA-100K oracle granular enough, or is a hand-labeled 500-row gold set needed for UC-4.1?
- What embedding model for the proxy's relation-similarity index: small (BGE-small, fast, lower precision) or medium (BGE-large, slower, may blow latency budget)?
- B-LLM baseline implementation: use Mem0 v3 as is (apples-to-apples but adds Mem0 surface area) or re-implement just its conflict-resolution prompt against the same backend (cleaner comparison)?
- LORD++ wealth schedule: initialize a fresh ledger per release cycle (resets memory of prior rejections, cleaner reasoning per release) or carry one continuous ledger across the project lifetime (more conservative; the FDR claim spans the whole history)? Default: per-release ledger, with a separate lifetime ledger for any claim that goes into external writeups.
- For UC-4.7, UC-3.4, and UC-3.6, the LongMemEval-S query set is small (~500 queries). Augment with a synthetic query generator, or accept the narrower CI?

## 9. Status and Next Concrete Actions

Implemented:

- `fixtures/` repo with W-CONCEPTNET-REL and SHA-256 workload pinning at load time.
- `runner.py` taking `(variant, workload, baseline)` and emitting the Section 6.1 three-block artifact.
- Pilot run on UC-4.1 with the stub random-bucket proxy.
- LORD++ ledger in `runner/fdr.py` with prescribed `test_seq_id` ordering.
- CUPED adjustment in `runner/cuped.py`.
- Section 6.4 CI/CD edge-case guardrails in `runner/gates.py`.

Open work:

- SAFFRON algorithm itself (currently only the recommendation gate; needs the actual ledger when hot-swap fires).
- Always-valid CI emission per batch (Section 5.5).
- UC-4.4 Tier B programmatic adversarial generator.
- UC-3.4 longitudinal checkpoint runner and UC-3.6 RMST survival analyzer (log-rank as diagnostic only).
- First real proxy variant `v0.1.0`: sentence-transformer embedding of relation strings with similarity-threshold nearest-canonical assignment.
- Pre-register first three hypotheses in `runs/registry.md`.
- Switch bootstrap to resample input indices and recompute pairwise F1 within each resample.

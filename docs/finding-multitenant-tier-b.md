# Finding: Multi-tenant Tier B Surfaces Two Real Bugs

Status: experimental, June 2026.
Reproduce: `experiments/multitenant_tier_b_score.py` against the generated fixtures.

## What the multi-tenant Tier B fixture tests

The single-source Tier B fixtures (in `fixtures/adversarials/`) test false-merge resistance within a single canonical store. The multi-tenant counterpart tests false merges across sources: pairs `(source_a, input_a, oracle_a)` and `(source_b, input_b, oracle_b)` where the inputs are the same surface form but the oracle canonicals differ. A correct multi-tenant variant must keep the two entries in separate canonical clusters.

Generator: `fixtures/generators/multitenant_tier_b.py`. Mines pairs from any multi-tenant workload.

Produced fixtures:
- `fixtures/adversarials/multitenant_tier_b_wikidata.json` — 17 pairs from W-MULTITENANT-WIKIDATA
- `fixtures/adversarials/multitenant_tier_b_synth.json` — 79 pairs from W-MULTITENANT-SYNTH

## Scoring methodology

For each variant, ingest the FULL canonical-source workload first (so each (source, local) cluster has all the aliases it would see in production), run consolidate, then check each adversarial pair's predicted canonicals. Pair is a false merge iff both entries return the same predicted canonical.

## Results

### WIKIDATA multi-tenant Tier B (17 pairs)

| Variant | False merges | Rate |
|---|---|---|
| v0.4.0 per-source | 0/17 | 0.00% |
| v0.4.1 consensus | 0/17 | 0.00% |
| v0.4.2 lazy | 0/17 | 0.00% |
| v0.4.3 AND rule | 0/17 | 0.00% |
| v0.4.4 adaptive | 0/17 | 0.00% |

All variants pass WIKIDATA cleanly. (Aliases are very disjoint across the disambiguation entries, so cross-source consolidation has no signal to fire on.)

### SYNTH multi-tenant Tier B (79 pairs)

| Variant | False merges | Rate |
|---|---|---|
| v0.4.0 per-source | 0/79 | 0.00% |
| v0.4.1 consensus | 2/79 | 2.53% |
| v0.4.2 lazy | 2/79 | 2.53% |
| v0.4.3 AND rule | 2/79 | 2.53% |
| **v0.4.4 adaptive** | **79/79** | **100.00%** |

Two bugs surfaced:

## Bug 1: Hash collision in HashedTokenEmbedder

v0.4.1 / v0.4.2 / v0.4.3 all fail 2/79 on SYNTH, all on the same pairs:

  - `(finance, Account)` <-> `(sales, Account)` -> merged
  - `(finance, Vendor)` <-> `(sales, Vendor)` -> merged

Root cause: with `HashedTokenEmbedder(dim=256)`, the tokens "account" and "vendor" happen to hash to the same bucket with the same sign. This makes `token_cosine('Account', 'Vendor') = 1.0` spuriously.

In v0.3.1's hybrid (token_weight=2, neural_weight=1, threshold=0.8):
  - hybrid_cosine('Account', 'Vendor') = 0.8 * 1.0 + 0.2 * 0.67 = 0.93
  - Above the 0.8 threshold; v0.3.1 inner aliases "Vendor" -> local "Account"

Consequence in v0.4.x: both sales and finance end up with `(source, "Account")` clusters containing alias set `{"Account", "Vendor"}`. Cross-source overlap = 2 (matches both shared surfaces), Jaccard = 1.0. v0.4.3 AND rule fires the merge. The two source-distinct "Account" clusters wrongly collapse.

Probability of any two tokens hash-colliding at dim=256 is roughly 1/256. With ~80 unique tokens in W-MULTITENANT-SYNTH, expected collisions ≈ 80*79/2 / 256 ≈ 12 pairs. We observed at least one (account/vendor). The fix is to raise the default dim.

**Recommended fix**: bump HashedTokenEmbedder default dim from 256 to 4096 or 8192. SHA-256 collision probability drops by 16x or 32x. Negligible memory cost (a few KB per centroid).

## Bug 2: v0.4.4 aggressive mode is unsafe on SYNTH

v0.4.4 in aggressive mode sets `min_aliases=1, min_overlap=1`. This means:
- Single-alias clusters can participate in merge consideration
- Even ONE shared alias between two clusters is enough to fire the merge

On SYNTH the global stratum has many cross-source pairs sharing single aliases (e.g., multiple sources see "Microsoft" with the same single alias). These genuine merges are what made v0.4.4 win UC-4.1 B-cubed.

But the conditional stratum has many cross-source pairs sharing single aliases of DIFFERENT entities (e.g., sales "Account" = CRM_Account, finance "Account" = GL_Account). These should NOT merge. With min_overlap=1, the single shared "Account" surface triggers a wrong merge.

Tier B fixture catches this: 79/79 false-merge rate at v0.4.4 aggressive mode.

The B-cubed F1 metric did not catch this because most of v0.4.4's aggressive merges are CORRECT (the global stratum), and B-cubed averages over all items.

**Recommended fix**: tighten v0.4.4 aggressive mode to `min_aliases=1` AND `min_overlap=2`. The min_overlap=2 constraint blocks single-shared-alias merges. May reduce v0.4.4's UC-4.1 wins on SYNTH but eliminates the Tier B failure.

## Implication for variant ranking

The multi-tenant Tier B is a stronger evaluation than UC-4.1 B-cubed for safety. It directly tests the case the variants are MOST likely to get wrong: surface-form collisions across semantically-distinct entities.

The corrected ranking after this finding:

| Variant | UC-4.1 SYNTH | MT Tier B SYNTH | Recommendation |
|---|---|---|---|
| v0.4.0 | 0.284 | 0% | Safe, low quality |
| v0.4.1/v0.4.2/v0.4.3 | 0.326 | 2.5% (hash collision bug) | Pending Bug 1 fix |
| v0.4.4 default | 0.475 | (untested at default; pending) | Pending re-test |
| v0.4.4 aggressive | 0.475 | 100% FAIL | Not safe |

After Bug 1 fix (larger HashedTokenEmbedder dim): v0.4.1-v0.4.3 should drop to 0/79 false merges.
After Bug 2 fix (tighter aggressive mode): v0.4.4 should be a tunable safe variant.

## Process implication

The multi-tenant Tier B fixture should have been built at the same time as the multi-tenant workloads themselves. Building only the workload + B-cubed F1 metric let v0.4.4 ship with a major hidden failure mode (100% false merge on Tier B). The harness's principle of "pair every win metric with a safety metric" was followed for single-tenant (UC-4.1 + UC-4.4) but not for multi-tenant.

Going forward, every new use case or workload should ship with a paired Tier B fixture.

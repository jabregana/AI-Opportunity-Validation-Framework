"""Engineering-cost estimates per variant.

Maps every variant in the project's factory registries to an engineering
build-cost estimate. Used by the investment-prioritization tool to
convert "lift %" findings into "ROI per engineer-week" recommendations.

Format per entry:

  {
    "engineer_weeks": float,       # one-time build effort
    "ongoing_quarterly_weeks": float,  # maintenance per quarter
    "infra_cost_per_million_calls_usd": float,  # incremental infra
    "confidence": "high" | "medium" | "low",  # researcher's confidence
    "notes": str,                   # brief justification
  }

The numbers are researcher-estimated. Confidence is low-to-medium; real
calibration requires retrospective audit of how long each variant
actually took to build. Per the strategic-framing-decision-tool.md
proposal 1, these are the foundation for the investment-prioritization
output, not ground truth.

Convention: baselines (b-*) are 0 engineer-weeks because they are the
identity / no-op variant that already exists by construction.
"""
from __future__ import annotations


# Default estimate when a variant has no entry. Surfaces as "unknown"
# in the investment-prioritization output.
DEFAULT_BUILD_COST_ESTIMATE = {
    "engineer_weeks": None,
    "ongoing_quarterly_weeks": None,
    "infra_cost_per_million_calls_usd": None,
    "confidence": "unknown",
    "notes": "no estimate registered; default unknown",
}


BUILD_COST_ESTIMATES: dict[str, dict] = {
    # ---- Memory canonicalization (proxy case study) ----
    "b-raw-identity": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Identity baseline; no build effort.",
    },
    "stub-random-bucket": {
        "engineer_weeks": 0.1, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Test stub only.",
    },
    "embed-proxy-v0.1.0": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Token-overlap regex matching + alias lookup.",
    },
    "embed-proxy-v0.2.0": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "medium",
        "notes": "Neural embedder (model2vec) integration.",
    },
    "embed-proxy-v0.3.0": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "medium",
        "notes": "Hybrid token + neural concat.",
    },
    "embed-proxy-v0.3.1": {
        "engineer_weeks": 0.5, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "medium",
        "notes": "Adds structural filter to v0.3.0.",
    },
    "embed-proxy-v0.4.0-per-source": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "medium",
        "notes": "Multi-tenant per-source scoping.",
    },
    "embed-proxy-v0.5.3-singleton-aware": {
        "engineer_weeks": 1.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "medium",
        "notes": "Singleton tracking + lazy consolidation.",
    },
    "embed-proxy-v0.5.5-ann": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 8.0,
        "confidence": "medium",
        "notes": "HNSW ANN index integration.",
    },
    "embed-proxy-v0.5.7-mt-ann": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 0.75,
        "infra_cost_per_million_calls_usd": 8.0,
        "confidence": "medium",
        "notes": "Multi-tenant ANN combine.",
    },

    # ---- Memory lifecycle (graph GC case study) ----
    "b-raw-no-gc": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "No-GC baseline.",
    },
    "gc-v0.1.0-ref-count": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Reference-counted entity GC.",
    },
    "gc-v0.1.1-ref-count-utility": {
        "engineer_weeks": 1.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Adds utility-score rule on top of v0.1.0.",
    },
    "gc-v0.1.2-fact-only": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Fact-only collection; conservative entity survival.",
    },
    "gc-v0.1.3-fact-only-tombstone": {
        "engineer_weeks": 1.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Adds tombstone log to v0.1.2 for over-collection recovery.",
    },
    "gc-v0.1.4-conservative-entity-plus-fact": {
        "engineer_weeks": 1.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "v0.1.2 + entity collection with conservative thresholds.",
    },
    "gc-v0.1.5-fact-only-tenant-pinning": {
        "engineer_weeks": 1.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "v0.1.2 + per-tenant pin tracking for multi-tenant SaaS.",
    },
    "gc-v0.1.6-comprehensive": {
        "engineer_weeks": 3.0, "ongoing_quarterly_weeks": 1.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Bundle of v0.1.3 + v0.1.4 + v0.1.5; production-ready full feature set.",
    },
    "gc-v0.1.7-conservative-entity-tuned": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "v0.1.4 + query_count secondary gate to reduce over-collection.",
    },
    "gc-v0.1.8-comprehensive-tuned": {
        "engineer_weeks": 3.5, "ongoing_quarterly_weeks": 1.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Bundle of v0.1.3 + v0.1.5 + v0.1.7 (NOT v0.1.4). Production-ready full feature set without v0.1.6's over-collection issue.",
    },

    # ---- Prompt dimension ----
    "b-default-prompt": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Raw input baseline.",
    },
    "prompt-v0.1.0-cot": {
        "engineer_weeks": 0.2, "ongoing_quarterly_weeks": 0.1,
        "infra_cost_per_million_calls_usd": 10.0,
        "confidence": "high",
        "notes": "CoT prefix template; trivial; infra cost is extra tokens.",
    },
    "prompt-v0.1.1-direct-structured": {
        "engineer_weeks": 0.5, "ongoing_quarterly_weeks": 0.1,
        "infra_cost_per_million_calls_usd": 5.0,
        "confidence": "high",
        "notes": "JSON schema + parser; ongoing schema evolution.",
    },
    "prompt-v0.1.2-few-shot-1": {
        "engineer_weeks": 0.3, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 15.0,
        "confidence": "high",
        "notes": "One example; per-task example curation is ongoing.",
    },
    "prompt-v0.1.3-few-shot-3": {
        "engineer_weeks": 0.5, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 40.0,
        "confidence": "high",
        "notes": "Three examples; 3x the curation effort + token cost.",
    },
    "prompt-v0.1.4-cot-plus-structured": {
        "engineer_weeks": 0.5, "ongoing_quarterly_weeks": 0.2,
        "infra_cost_per_million_calls_usd": 15.0,
        "confidence": "high",
        "notes": "Combines CoT + JSON schema.",
    },

    # ---- Tools dimension ----
    "b-allow-all-tools": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Passthrough baseline.",
    },
    "tool-v0.1.0-budget-bucketed": {
        "engineer_weeks": 0.5, "ongoing_quarterly_weeks": 0.1,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Simple hash-based selection.",
    },
    "tool-v0.1.1-intent-classified": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 1.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Keyword classifier; keyword list needs maintenance.",
    },
    "tool-v0.1.2-intent-plus-helper": {
        "engineer_weeks": 3.0, "ongoing_quarterly_weeks": 1.5,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "medium",
        "notes": "Expanded keywords + neighbors + helper-tool hint.",
    },

    # ---- Policy dimension ----
    "b-single-shot-policy": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Always-finish baseline.",
    },
    "policy-v0.1.0-react": {
        "engineer_weeks": 3.0, "ongoing_quarterly_weeks": 1.0,
        "infra_cost_per_million_calls_usd": 100.0,
        "confidence": "medium",
        "notes": "Think-act-observe loop + state management; 6x calls.",
    },
    "policy-v0.1.1-plan-execute": {
        "engineer_weeks": 4.0, "ongoing_quarterly_weeks": 1.5,
        "infra_cost_per_million_calls_usd": 80.0,
        "confidence": "medium",
        "notes": "Planner + executor; harder to debug than ReAct.",
    },
    "policy-v0.1.2-reflect-loop": {
        "engineer_weeks": 5.0, "ongoing_quarterly_weeks": 2.0,
        "infra_cost_per_million_calls_usd": 150.0,
        "confidence": "medium",
        "notes": "Reflection prompts + revision logic; 8x calls.",
    },
    "policy-v0.1.3-handoff": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 50.0,
        "confidence": "medium",
        "notes": "Failure detection + handoff routing to larger model.",
    },

    # ---- Recovery dimension ----
    "b-abort-on-failure": {
        "engineer_weeks": 0.0, "ongoing_quarterly_weeks": 0.0,
        "infra_cost_per_million_calls_usd": 0.0,
        "confidence": "high",
        "notes": "Always-abort baseline.",
    },
    "recovery-v0.1.0-retry-with-backoff": {
        "engineer_weeks": 1.0, "ongoing_quarterly_weeks": 0.25,
        "infra_cost_per_million_calls_usd": 30.0,
        "confidence": "high",
        "notes": "Exponential backoff + retryable-kinds filter.",
    },
    "recovery-v0.1.1-fallback-chain": {
        "engineer_weeks": 2.0, "ongoing_quarterly_weeks": 0.75,
        "infra_cost_per_million_calls_usd": 60.0,
        "confidence": "medium",
        "notes": "Kind-specific fallback strategies; needs per-strategy infra.",
    },
}


def get_build_cost(variant_name: str) -> dict:
    """Return the build-cost estimate for a variant name.

    Returns DEFAULT_BUILD_COST_ESTIMATE if no entry exists. The
    investment-prioritization tool should surface unknown entries
    explicitly rather than treat them as zero-cost.
    """
    return BUILD_COST_ESTIMATES.get(variant_name, DEFAULT_BUILD_COST_ESTIMATE)

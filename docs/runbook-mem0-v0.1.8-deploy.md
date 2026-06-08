---
type: runbook
date: 2026-06-08
status: DRAFT
covers: deploying gc-v0.1.8-comprehensive-tuned in front of Mem0 v2 in production
---

# Runbook: deploying gc-v0.1.8 with Mem0 v2 in production

This is the operational guide for a team that already runs Mem0 v2 and wants to add `gc-v0.1.8-comprehensive-tuned` as the memory-lifecycle policy.

The goal of this runbook is to make the deployment boring: the policy is a drop-in wrapper, the failure modes are bounded, and you know what to watch.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | >= 3.11 | The harness is tested on 3.11 + 3.12 |
| Mem0 | 2.0.4+ | v2's search uses `filters={'user_id': ...}` not top-level kwargs; adapter handles the translation |
| Vector store | Qdrant or any Mem0-supported backend | The adapter does not care which one |
| LLM | Whatever Mem0's config points to | Ollama (phi3:mini works), OpenAI, etc |
| `ai-wedge-harness` | this repo | Install via `pip install -e .` from the repo root |

The adapter does **not** call Mem0's internal storage directly. Every read/write goes through Mem0's public API, so any Mem0-supported backend works.

---

## 2. Drop-in installation

The pattern is composition: wrap your existing `Memory` instance, then use the middleware everywhere you used `memory`:

```python
from mem0 import Memory
from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import Mem0GCMiddleware

memory = Memory.from_config(your_existing_config)
variant = build("gc-v0.1.8-comprehensive-tuned")
mw = Mem0GCMiddleware(memory)

# Anywhere you wrote memory.add(...), write mw.add(...) instead
mw.add("User likes oat milk", user_id="alice")
results = mw.search("dietary preferences", user_id="alice")
```

That's the whole user-facing change. Every other Mem0 call (history, chat, etc) still works on `mw.memory`.

---

## 3. Picking a sweep cadence

The middleware does not auto-sweep. You decide when to call `mw.sweep(variant, current_time=time.time())`. The right answer depends on workload:

| Workload shape | Recommended cadence | Why |
|---|---|---|
| < 100 adds/day | Daily | Sweep cost trivial; cadence keeps store tidy |
| 100-10K adds/day | Every 4-6 hours | Keeps GC working set small per sweep |
| > 10K adds/day | Every 30-60 min | Bigger sweeps hurt p95 latency; smaller more often is safer |
| Spiky (batch ingests) | After each batch + daily heartbeat | Batch-aware GC catches the spike before retrieval quality drops |

The synthesis plan's compressed simulation (`experiments/gc_long_running_simulation.py`) used `sweep_every=25` and achieved 99.3% reduction at 30 days. That ratio holds across cadences; the trade-off is sweep cost per call.

**Default if you don't know:** schedule a cron every 4 hours. Adjust based on the metrics in section 5.

---

## 4. Configuring the variant

Three knobs matter:

```python
from runner.dimensions.memory.lifecycle.gc_v018 import ComprehensiveTunedGC

variant = ComprehensiveTunedGC(
    min_age_seconds=86400,      # 1 day, memories must be at least this old to be collected
    min_query_count=2,          # Entities need >=2 queries to count as "useful"
)
```

| Knob | Default | When to change |
|---|---|---|
| `min_age_seconds` | 86400 (1 day) | Lower (3600 = 1 hour) for chat agents where context goes stale fast; higher (604800 = 1 week) for compliance-heavy workloads where deletion needs to lag |
| `min_query_count` | 2 | Lower (1) if entities are scarce; higher (3-5) if you over-trust the entity rule and lose recall |
| Tombstone TTL | 7 days (set in v0.1.3) | Bump if you need a longer "soft delete" window for audit |

Tenant pinning (`mw.pin_for_tenant(tenant_id, node_ids)`) lets you protect specific memories from being swept regardless of policy. Use for: VIP users, compliance holds, explicit user-marked "important" memories.

---

## 5. Monitoring (what to chart)

Five metrics. The first three are the GC outcomes. The last two are the agent-quality signal.

| Metric | What it tells you | Where it comes from |
|---|---|---|
| Memories remaining | Store size after each sweep | `len(mw._records)` after `sweep()` |
| Memories removed per sweep | How much each sweep is reclaiming | Return value of `mw.sweep()` |
| % reduction per sweep | Removed / before | Compute from above |
| Search recall@10 (1-hour window) | Agent retrieval quality | Track in your agent eval harness; alert if drops > 10% from baseline |
| Agent task success rate | The actual business metric | Whatever your agent tracks today |

**Dashboard layout suggestion:** the top panel is store size over time (you want a sawtooth that stays bounded). The bottom panel is search recall over time (you want a flat line). Any drift in either is the signal.

---

## 6. Rollback signals

The framework's UC gates encode the rollback rule. If any of these fire in production, treat as "rollback to baseline (no GC) and investigate":

| Gate | Threshold | Means |
|---|---|---|
| UC-GC-2 (entity survival) | < 90% | The entity rule is collecting entities it shouldn't; bump `min_query_count` |
| UC-GC-RETRIEVAL (F1 preservation) | < 80% | Retrieval quality regressed; check whether `min_age_seconds` is too low |
| UC-GC-5 (tenant isolation) | any leak | A swept memory was returned to the wrong tenant; this is a bug, file an issue |
| Store size growing despite sweeps | sustained > 1 week | Sweep is not keeping up with add rate; increase cadence |
| Agent recall@10 drop > 10% from baseline | over a 24-hour window | The customer-visible signal; same fix as UC-GC-RETRIEVAL |

Rollback is straightforward: stop calling `mw.sweep()`. The middleware still records add/search events, but no collections happen. You can re-enable later once the issue is diagnosed.

---

## 7. Known issues + workarounds

| Issue | Workaround | Where it lives |
|---|---|---|
| Mem0 v2 search uses `filters={...}` not top-level entity kwargs | Adapter auto-translates; no user code change needed | `mem0_adapter.py:search()` |
| Mem0's LLM extraction sometimes returns a string instead of dict | Adapter has defensive `isinstance(result, dict)` guard | `mem0_adapter.py:add()` |
| Sweep recomputes everything from scratch | For very large stores (> 1M memories), this is slow; partition by tenant + sweep tenant-by-tenant | Plan a Phase-2 incremental-sweep adapter if you hit this |
| Tombstones grow unbounded | `gc-v0.1.8` includes a tombstone TTL (default 7 days); tombstones older than TTL get hard-deleted | `gc_v013.py:_prune_tombstones()` |

---

## 8. Pre-launch checklist

Before pointing production at the middleware:

- [ ] All 470+ unit tests pass: `pytest tests/ -q`
- [ ] F1 regression CI green on your fork (`.github/workflows/ci.yml`)
- [ ] Smoke test with `experiments/mem0_smoke_test_real_llm.py --n-memories 200` against your actual Mem0 config (catches LLM/embedder misconfig before prod)
- [ ] Sweep cadence cron written + tested (dry-run with `--dry-run` flag if your scheduler supports it)
- [ ] Monitoring dashboard live BEFORE turning sweep on (so you can see the first sweep's impact)
- [ ] Rollback path documented in your team's incident runbook (the answer is "stop calling sweep()"; make sure the on-call knows that)
- [ ] One human-owned "memory pin" UX for your tenants (so VIPs can opt out of GC)

---

## 9. First-week operational rhythm

| Day | What to do |
|---|---|
| Day 0 | Deploy middleware (no sweep yet). Confirm reads/writes work, store grows normally |
| Day 1 | Enable manual sweep (`mw.sweep()` via admin trigger). Confirm metrics are sensible |
| Day 2 | Enable cron sweep at lowest cadence (daily). Watch for 48 hours |
| Day 4 | If metrics flat: tighten cadence to your section-3 recommendation |
| Day 7 | First week-over-week review: store size trajectory, search recall, agent success rate |

After week 1, the policy runs on its own. Re-tune cadence quarterly or when workload shape changes.

---

## Pointers

- Adapter source: `runner/dimensions/memory/lifecycle/integrations/mem0_adapter.py`
- Variant source: `runner/dimensions/memory/lifecycle/gc_v018.py`
- Smoke test: `experiments/mem0_smoke_test_real_llm.py`
- F1 benchmark: `experiments/mem0_retrieval_f1_benchmark.py`
- UC gates: `runner/gc_runner.py` (`compute_*_gate` functions)
- Synthesis plan: `docs/synthesis-memory-lifecycle-management.md`
- CI regression gate: `.github/workflows/ci.yml`

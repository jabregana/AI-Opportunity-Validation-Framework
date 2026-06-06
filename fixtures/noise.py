"""Noise injection for drift Type B analysis.

Wraps a base workload with controlled noise to measure variant
robustness. Three noise modes:

  source_swap   Replace an entry's source_id with a different source.
                Simulates wrong-team attribution.
  surface_perturb Replace an entry's input with a random alternative
                  drawn from elsewhere in the workload. Simulates a
                  typo or wrong-word-picked ingestion.
  alias_drop    Drop an entry entirely from the workload. Simulates
                missing data.

The noise rate is the fraction of entries that get touched. Mixed-mode
selection: each touched entry gets a uniformly random noise type.

Reproducible via a seed. The wrapper returns a list[WorkloadEntry]
suitable for any existing UC.
"""
from __future__ import annotations
import random


def inject_noise(
    workload,
    noise_rate: float = 0.05,
    seed: int = 0xC0FFEE,
    modes: tuple[str, ...] = ("source_swap", "surface_perturb", "alias_drop"),
) -> list:
    """Return a noisy version of the workload.

    workload: list[WorkloadEntry]
    noise_rate: fraction of entries to perturb in [0, 1]
    """
    if not 0 <= noise_rate <= 1:
        raise ValueError("noise_rate must be in [0, 1]")
    if not modes:
        raise ValueError("modes must contain at least one noise mode")
    from fixtures.workloads import WorkloadEntry

    rng = random.Random(seed)
    n = len(workload)
    n_touch = int(round(n * noise_rate))
    if n_touch == 0:
        return list(workload)

    touch_idxs = set(rng.sample(range(n), n_touch))
    all_sources = sorted({e.source_id for e in workload})
    all_inputs = [e.input for e in workload]

    out = []
    for i, entry in enumerate(workload):
        if i not in touch_idxs:
            out.append(entry)
            continue
        mode = rng.choice(modes)
        if mode == "source_swap":
            alt_sources = [s for s in all_sources if s != entry.source_id]
            if not alt_sources:
                out.append(entry)
                continue
            new_source = rng.choice(alt_sources)
            out.append(WorkloadEntry(new_source, entry.input, entry.oracle_canonical))
        elif mode == "surface_perturb":
            alt_inputs = [s for s in all_inputs if s != entry.input]
            if not alt_inputs:
                out.append(entry)
                continue
            new_input = rng.choice(alt_inputs)
            out.append(WorkloadEntry(entry.source_id, new_input, entry.oracle_canonical))
        elif mode == "alias_drop":
            continue  # drop the entry entirely
        else:
            raise ValueError(f"unknown mode: {mode}")
    return out

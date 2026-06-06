# agent-memory-gaps

Experimental harness for the proxy/middleware memory-graph wedges from the
SecondBrain project notes:

- **Niche 4 (primary): Schema Alignment Proxy** — write-path middleware that
  aliases near-duplicate relations/properties before they hit a property graph.
- **Niche 3 (backup): Real-Time Graph GC** — write-path / post-task middleware
  that reference-counts and evicts low-utility nodes and edges.

Spec, statistical framework, and use-case definitions live in the vault at
`SecondBrain/1-Projects/agent-memory-gaps/experiments.md`. This repo is the
code.

## Layout

```
fixtures/        Workload generators and SHA-pinned manifest
runner/          Harness: variants, metrics, runner, artifact writer
runs/            Output run artifacts (gitignored)
tests/           Smoke tests for the harness
```

## Pilot run (UC-4.1, schema alignment)

```sh
python -m runner.runner \
  --variant stub-random-bucket \
  --baseline b-raw-identity \
  --workload W-CONCEPTNET-REL \
  --use-case UC-4.1
```

Writes `runs/run-<uuid>.json` with paired metrics and bootstrap CI.

## Smoke test

```sh
python -m pytest tests/
```

## Known pilot limitations
- The bootstrap CI is computed on **per-item strict-cluster correctness**, which is degenerate (all zeros) when neither variant produces a single perfectly-clean cluster. Pairwise F1 in the artifact still shows the real signal. Switch the bootstrap to resampling **input indices and recomputing F1** once a variant lands non-trivial F1 — tracked as a TODO in `runner/runner.py`.
- Only `W-CONCEPTNET-REL` is implemented. The other 5 workloads in `fixtures/manifest.json` are stubs (`status: stub`).
- McNemar's test is reported as raw discordant counts only. The exact binomial p-value will land when SciPy is added.

"""W-LONGMEMEVAL-S — stub for the LongMemEval-S benchmark.

Real integration plan is in docs/longmemeval-integration-plan.md.
The dataset is downloaded and cached but the format does not map
directly to the proxy's surface-form/oracle-canonical schema. A
real workload generator needs an NER stage and a retrieval scorer.
"""
from __future__ import annotations


def load():
    raise NotImplementedError(
        "W-LONGMEMEVAL-S is a planned workload. The dataset is "
        "downloaded and characterized; the workload generator requires "
        "an NER stage that extracts entity mentions from dialogue "
        "turns. See docs/longmemeval-integration-plan.md."
    )

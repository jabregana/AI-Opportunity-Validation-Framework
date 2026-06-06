from __future__ import annotations
from abc import ABC, abstractmethod


class Variant(ABC):
    """A schema-alignment variant.

    Variants observe a stream of relation writes and produce a canonical
    bucket id for each. The proxy is free to mint its own canonical labels
    (e.g., "BUCKET_07") — the harness compares clusterings, not labels.
    """

    name: str = "unnamed-variant"

    @abstractmethod
    def align(self, input_relation: str) -> str:
        """Return the canonical bucket for an input relation surface form."""
        raise NotImplementedError

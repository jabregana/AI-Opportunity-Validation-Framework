from __future__ import annotations
from .base import Variant


class BRawIdentity(Variant):
    """B-RAW baseline — no proxy, identity pass-through.

    Every surface form becomes its own canonical. Establishes the "no schema
    alignment" capability floor: any two inputs differing in case or
    underscoring will end up in distinct buckets.
    """

    name = "b-raw-identity"

    def align(self, input_relation: str) -> str:
        return input_relation

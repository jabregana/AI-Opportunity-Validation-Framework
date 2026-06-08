"""DimensionVariant: the marker base class for any variant in any
dimension.

Each of the six dimension sub-packages (prompt, tools, policy, recovery,
plus future memory and model) defines its own Variant ABC inheriting
from DimensionVariant. The marker class exists so the harness can:

  - Identify any variant as a dimension variant via isinstance()
  - Surface the variant.dimension attribute in artifact outputs (so
    finding docs can be grouped by dimension)
  - Provide a single import point for downstream tooling that wants
    to enumerate variants across dimensions

The marker class does NOT prescribe the decision interface. That is
each dimension's job. Memory variants implement align(); GC variants
implement should_collect(); prompt variants implement render(); etc.
"""
from __future__ import annotations
from abc import ABC


class DimensionVariant(ABC):
    """Base class for any variant in any of the six dimensions.

    Subclasses set `dimension` to one of DIMENSIONS and provide their
    own decision method (signature varies by dimension).
    """

    name: str = "unnamed-variant"
    dimension: str = "unknown"

from __future__ import annotations
from abc import ABC, abstractmethod


class Variant(ABC):
    """A schema-alignment variant.

    Variants observe a stream of relation writes and produce a canonical
    bucket id for each. The proxy is free to mint its own canonical labels
    (e.g., "BUCKET_07"); the harness compares clusterings, not labels.

    Two interfaces:

      align(input_relation) -> canonical
        Single-tenant interface. All v0.1.0 - v0.3.1 variants implement
        this directly. The harness's default invocation path.

      align_with_context(input_relation, context) -> canonical
        Multi-tenant interface (v0.4.0+). context is a dict that may
        carry source_id and other request-scoped metadata. The default
        implementation ignores context and delegates to align(), so
        legacy variants do not need to be modified to be invoked through
        the new path.
    """

    name: str = "unnamed-variant"

    @abstractmethod
    def align(self, input_relation: str) -> str:
        """Return the canonical bucket for an input relation surface form."""
        raise NotImplementedError

    def align_with_context(
        self,
        input_relation: str,
        context: dict | None = None,
    ) -> str:
        """Context-aware alignment.

        Default: ignore context, call align(). Variants that consume
        context (e.g., v0.4.0+ source-attributed) override this method.
        """
        return self.align(input_relation)

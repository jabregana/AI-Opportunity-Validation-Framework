"""Intent-classified tool variant.

tool-v0.1.1-intent-classified: use a simple keyword classifier to
identify which tool categories the task likely needs, then expose
only tools from matching categories.

The "classifier" is intentionally simple (keyword matching on the
task goal against category names). Real production systems would use
an embedding-based or LLM-based classifier. The wedge being benchmarked
is "does intent-aware filtering beat budget-only filtering," not
"is keyword matching the optimal classifier."

If no category matches, falls back to exposing the first
fallback_max_exposed tools (alphabetically) so the agent at least
gets a chance.
"""
from __future__ import annotations

from .base import ToolCall, ToolVariant


# Map category name to keywords that suggest the category is relevant.
# Mirrors the keys in fixtures/workloads/w_tool_selection.py's
# TOOL_CATEGORIES; kept in sync by convention.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "search": ["find", "search", "look up", "lookup", "information", "topic"],
    "data": ["process", "dataset", "metric", "data", "query", "report"],
    "files": ["file", "reorganize", "project", "directory"],
    "communication": ["notify", "team", "event", "message", "send"],
    "computation": ["compute", "calculate", "quantity", "math", "solve"],
    "external_api": ["look up", "current", "value", "datum", "fetch"],
    "system": ["inspect", "system", "resource", "process"],
}


class IntentClassifiedToolVariant(ToolVariant):
    """Pre-filter tools by category-keyword match on the task goal."""

    name = "tool-v0.1.1-intent-classified"

    def __init__(
        self,
        fallback_max_exposed: int = 10,
        category_keywords: dict[str, list[str]] | None = None,
    ):
        self.fallback_max_exposed = fallback_max_exposed
        self.keywords = category_keywords or CATEGORY_KEYWORDS

    def _classify(self, goal_text: str) -> list[str]:
        """Return the categories whose keywords appear in the goal."""
        goal_lower = goal_text.lower()
        matched: list[str] = []
        for category, kws in self.keywords.items():
            if any(kw in goal_lower for kw in kws):
                matched.append(category)
        return matched

    def available_tools(self, context: dict) -> list[str]:
        all_tools = list(context.get("all_tools", []))
        goal = str(context.get("goal", ""))
        categories_map: dict[str, list[str]] = context.get("categories", {})

        matched_categories = self._classify(goal)
        if matched_categories and categories_map:
            allowed: set[str] = set()
            for cat in matched_categories:
                for t in categories_map.get(cat, []):
                    if t in all_tools:
                        allowed.add(t)
            if allowed:
                return sorted(allowed)

        # Fallback: alphabetical first-N
        return sorted(all_tools)[: self.fallback_max_exposed]

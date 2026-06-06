"""W-MULTITENANT-DEMO — synthetic multi-source workload (v0.4.0 demo).

Three sources query the same agent: sales, ops, marketing. Some entity
surface forms have source-conditional oracle canonicals (Apple means
Apple_Inc to sales and marketing, Apple_Supplier_Inc to ops). Other
surface forms are globally unambiguous (Microsoft is always
Microsoft_Corp regardless of source).

This is intentionally a toy fixture (33 entries). Its purpose is to
demonstrate that the harness can evaluate context-aware variants, not
to deliver statistical significance. A real multi-tenant workload is
v0.4.1+ work and probably needs synthesis from a public knowledge graph
plus team-attribution metadata.

Oracle canonicals are intentionally GLOBAL names (not source-prefixed).
A perfect variant would alias sales+marketing "Apple" together (both
Apple_Inc) but keep ops "Apple" separate (Apple_Supplier_Inc). It would
also alias all three sources' "Microsoft" together. Per-source
namespace variants will over-isolate; cross-source-aware variants
(v0.4.1+) will do better.
"""
from __future__ import annotations


# (source_id, input_surface, oracle_global_canonical)
_ENTRIES = [
    # Apple: ambiguous globally
    ("sales", "Apple", "Apple_Inc"),
    ("sales", "AAPL", "Apple_Inc"),
    ("marketing", "Apple", "Apple_Inc"),
    ("marketing", "Apple Computer", "Apple_Inc"),
    ("ops", "Apple", "Apple_Supplier_Inc"),
    ("ops", "Apple Foods", "Apple_Supplier_Inc"),

    # Microsoft: globally unambiguous across all three sources
    ("sales", "Microsoft", "Microsoft_Corp"),
    ("sales", "MSFT", "Microsoft_Corp"),
    ("ops", "Microsoft", "Microsoft_Corp"),
    ("ops", "Microsoft Corp", "Microsoft_Corp"),
    ("marketing", "Microsoft", "Microsoft_Corp"),

    # Tesla: only sales and marketing see it; both mean Tesla_Inc
    ("sales", "Tesla", "Tesla_Inc"),
    ("marketing", "Tesla", "Tesla_Inc"),
    ("marketing", "Tesla Motors", "Tesla_Inc"),

    # Source-unique entities
    ("ops", "Acme Logistics", "Acme_Supplier"),
    ("ops", "Acme", "Acme_Supplier"),
    ("marketing", "Nike", "Nike_Brand"),
    ("marketing", "Nike Inc", "Nike_Brand"),
    ("sales", "Salesforce", "Salesforce_Inc"),
    ("sales", "SFDC", "Salesforce_Inc"),

    # IBM: same canonical across sales and marketing
    ("sales", "IBM", "IBM_Corp"),
    ("sales", "International Business Machines", "IBM_Corp"),
    ("marketing", "IBM", "IBM_Corp"),

    # Amazon: ambiguous across sources
    ("sales", "Amazon", "Amazon_Inc"),
    ("sales", "AMZN", "Amazon_Inc"),
    ("ops", "Amazon", "Amazon_Logistics_Partner"),
    ("ops", "Amazon Delivery", "Amazon_Logistics_Partner"),

    # Google: globally unambiguous
    ("sales", "Google", "Google_LLC"),
    ("marketing", "Google", "Google_LLC"),
    ("ops", "Google", "Google_LLC"),

    # Source-unique with paraphrase
    ("sales", "Oracle", "Oracle_Corp"),
    ("sales", "Oracle Database", "Oracle_Corp"),
    ("ops", "Acme Corp", "Acme_Supplier"),
]


def load():
    from . import WorkloadEntry
    return [WorkloadEntry(s, i, o) for s, i, o in _ENTRIES]

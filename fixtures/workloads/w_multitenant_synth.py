"""W-MULTITENANT-SYNTH — fully synthetic multi-tenant workload.

Track 1 of the v0.4.1 evaluation data plan. Authoring an explicit
ambiguity-stratified workload at scale (~500+ entries across 7 sources).

Three strata, explicit per-entity tag:

  1. GLOBALLY UNAMBIGUOUS (entries with stratum="global"):
     The same surface form means the same thing regardless of source.
     A well-behaved multi-tenant variant must alias these across sources.

  2. PARTIALLY AMBIGUOUS (stratum="partial"):
     The surface form has two distinct meanings, each pinned to a
     subset of sources. The proxy must keep the subsets separated.

  3. FULLY SOURCE-CONDITIONAL (stratum="conditional"):
     The surface form has a different meaning in each source. The proxy
     must treat the same surface form as N distinct canonicals.

Oracle canonicals are intentionally NOT source-prefixed in this fixture.
The 'right' clustering depends on the source for partial / conditional
strata. v0.4.0 per-source-namespace will over-isolate the global stratum.
v0.4.1 cross-source-consensus will hopefully merge the global stratum
while preserving the partial / conditional strata.

Stratum can be recovered from the workload by inspecting which oracle
canonicals appear under multiple source_ids; the entity_stratum dict
below also records it explicitly for diagnostic use.
"""
from __future__ import annotations

# Source domains modeled on a typical mid-size company org.
SOURCES = ["sales", "ops", "marketing", "eng", "finance", "legal", "hr"]

# (entity_id, surface_forms_per_source, stratum)
# surface_forms_per_source: {source_id: [aliases]}
# Each entry of the workload is one (source, alias_or_label, oracle_canonical).

# GLOBAL stratum: 22 entities. Same canonical across all listed sources.
_GLOBAL = [
    # Tech vendors used cross-functionally
    {"oracle": "Microsoft_Corp",
     "per_source": {s: ["Microsoft", "MSFT", "Microsoft Corporation"]
                    for s in ["sales", "ops", "marketing", "eng", "finance", "legal", "hr"]}},
    {"oracle": "Google_LLC",
     "per_source": {s: ["Google", "Google Inc", "Alphabet Google"]
                    for s in ["sales", "marketing", "eng", "finance", "legal"]}},
    {"oracle": "Adobe_Inc",
     "per_source": {s: ["Adobe", "Adobe Inc", "Adobe Systems"]
                    for s in ["marketing", "eng", "finance"]}},
    {"oracle": "Slack_Technologies",
     "per_source": {s: ["Slack", "Slack Inc", "Slack Technologies"]
                    for s in ["sales", "ops", "marketing", "eng", "hr"]}},
    {"oracle": "Zoom_Video",
     "per_source": {s: ["Zoom", "Zoom Video", "Zoom Communications"]
                    for s in ["sales", "marketing", "eng", "hr", "legal"]}},
    {"oracle": "Stripe_Payments",
     "per_source": {s: ["Stripe", "Stripe Inc", "Stripe Payments"]
                    for s in ["sales", "eng", "finance"]}},
    {"oracle": "PayPal_Holdings",
     "per_source": {s: ["PayPal", "PayPal Inc", "PYPL"]
                    for s in ["sales", "eng", "finance", "legal"]}},
    {"oracle": "Atlassian_Corp",
     "per_source": {s: ["Atlassian", "Atlassian Corp", "Atlassian Pty"]
                    for s in ["eng", "ops", "finance"]}},
    {"oracle": "HubSpot_Inc",
     "per_source": {s: ["HubSpot", "Hubspot", "HubSpot Inc"]
                    for s in ["sales", "marketing", "finance"]}},
    {"oracle": "Notion_Labs",
     "per_source": {s: ["Notion", "Notion Labs", "notion.so"]
                    for s in ["eng", "marketing", "hr"]}},
    {"oracle": "LinkedIn_Corp",
     "per_source": {s: ["LinkedIn", "LinkedIn Corp", "Linkedin"]
                    for s in ["sales", "marketing", "hr", "legal"]}},
    {"oracle": "Spotify_Tech",
     "per_source": {s: ["Spotify", "Spotify Inc", "Spotify Technology"]
                    for s in ["marketing", "finance"]}},
    {"oracle": "GitHub_Inc",
     "per_source": {s: ["GitHub", "github.com", "GitHub Inc"]
                    for s in ["eng", "hr", "legal"]}},
    {"oracle": "Twilio_Inc",
     "per_source": {s: ["Twilio", "Twilio Inc", "TWLO"]
                    for s in ["eng", "marketing", "finance"]}},
    {"oracle": "Datadog_Inc",
     "per_source": {s: ["Datadog", "Datadog Inc", "DDOG"]
                    for s in ["eng", "finance"]}},
    {"oracle": "Snowflake_Inc",
     "per_source": {s: ["Snowflake Computing", "Snowflake Inc", "SNOW Inc"]
                    for s in ["eng", "finance"]}},
    {"oracle": "Workday_Inc",
     "per_source": {s: ["Workday", "Workday Inc", "WDAY"]
                    for s in ["hr", "finance"]}},
    {"oracle": "Okta_Inc",
     "per_source": {s: ["Okta", "Okta Inc", "OKTA"]
                    for s in ["eng", "hr", "legal"]}},
    {"oracle": "Tableau_Software",
     "per_source": {s: ["Tableau", "Tableau Software"]
                    for s in ["sales", "marketing", "finance"]}},
    {"oracle": "Asana_Inc",
     "per_source": {s: ["Asana", "Asana Inc"]
                    for s in ["ops", "marketing", "eng"]}},
    {"oracle": "Figma_Inc",
     "per_source": {s: ["Figma", "Figma Inc"]
                    for s in ["marketing", "eng"]}},
    {"oracle": "DocuSign_Inc",
     "per_source": {s: ["DocuSign", "Docusign", "DocuSign Inc"]
                    for s in ["sales", "legal", "finance", "hr"]}},
]


def _aliases(*forms):
    return list(forms)


# PARTIAL stratum: same surface form, two source-conditional meanings.
# Each entry has TWO oracles, each with its own source subset.
_PARTIAL = [
    {"surface_forms": _aliases("Apple", "AAPL", "Apple Inc"),
     "splits": [
         {"oracle": "Apple_Inc", "sources": ["sales", "marketing", "eng", "finance", "legal"]},
         {"oracle": "Apple_Supplier_Inc", "sources": ["ops"]},
     ]},
    {"surface_forms": _aliases("Amazon", "AMZN", "Amazon.com"),
     "splits": [
         {"oracle": "Amazon_Inc", "sources": ["sales", "marketing", "finance"]},
         {"oracle": "Amazon_Logistics_Partner", "sources": ["ops"]},
         {"oracle": "Amazon_Web_Services", "sources": ["eng"]},
     ]},
    {"surface_forms": _aliases("Salesforce", "SFDC", "Salesforce.com"),
     "splits": [
         {"oracle": "Salesforce_CRM", "sources": ["sales", "marketing"]},
         {"oracle": "Salesforce_Inc", "sources": ["finance", "legal"]},
     ]},
    {"surface_forms": _aliases("Oracle", "Oracle Corp", "Oracle Corporation"),
     "splits": [
         {"oracle": "Oracle_Database", "sources": ["eng"]},
         {"oracle": "Oracle_Corporation", "sources": ["sales", "finance", "legal"]},
     ]},
    {"surface_forms": _aliases("Java"),
     "splits": [
         {"oracle": "Java_Programming_Language", "sources": ["eng"]},
         {"oracle": "Java_Coffee_Brand", "sources": ["ops", "marketing"]},
     ]},
    {"surface_forms": _aliases("Python"),
     "splits": [
         {"oracle": "Python_Programming_Language", "sources": ["eng"]},
         {"oracle": "Python_Snake_Skin_Brand", "sources": ["marketing"]},
     ]},
    {"surface_forms": _aliases("Mercury", "Mercury Brand"),
     "splits": [
         {"oracle": "Mercury_Cars", "sources": ["ops"]},
         {"oracle": "Mercury_Insurance", "sources": ["finance", "legal"]},
     ]},
    {"surface_forms": _aliases("Office"),
     "splits": [
         {"oracle": "Microsoft_Office_Suite", "sources": ["eng", "sales", "marketing", "hr"]},
         {"oracle": "Physical_Office_Space", "sources": ["ops", "finance"]},
     ]},
    {"surface_forms": _aliases("Excel"),
     "splits": [
         {"oracle": "Microsoft_Excel", "sources": ["eng", "sales", "finance"]},
         {"oracle": "Excel_Performance_Rating", "sources": ["hr"]},
     ]},
    {"surface_forms": _aliases("Outlook"),
     "splits": [
         {"oracle": "Microsoft_Outlook", "sources": ["eng", "hr"]},
         {"oracle": "Sales_Outlook_Forecast", "sources": ["sales", "finance"]},
     ]},
    {"surface_forms": _aliases("Surface"),
     "splits": [
         {"oracle": "Microsoft_Surface_Device", "sources": ["eng", "sales"]},
         {"oracle": "Brand_Surface_Area", "sources": ["marketing"]},
     ]},
    {"surface_forms": _aliases("Acme", "Acme Inc"),
     "splits": [
         {"oracle": "Acme_Supplier", "sources": ["ops"]},
         {"oracle": "Acme_Customer_Account", "sources": ["sales", "finance"]},
     ]},
    {"surface_forms": _aliases("Sun"),
     "splits": [
         {"oracle": "Sun_Microsystems", "sources": ["eng"]},
         {"oracle": "Sun_Insurance_Co", "sources": ["finance"]},
     ]},
    {"surface_forms": _aliases("Champion"),
     "splits": [
         {"oracle": "Champion_Account_Tier", "sources": ["sales"]},
         {"oracle": "Champion_Brand_Apparel", "sources": ["marketing"]},
     ]},
    {"surface_forms": _aliases("Saturn"),
     "splits": [
         {"oracle": "Saturn_Cars", "sources": ["ops"]},
         {"oracle": "Saturn_Marketing_Campaign", "sources": ["marketing"]},
     ]},
]


# FULLY SOURCE-CONDITIONAL stratum: different meaning in (almost) every source.
_CONDITIONAL = [
    {"surface": "Pipeline",
     "per_source": {
         "sales": ("Sales_Pipeline", ["Pipeline", "sales pipeline", "deal pipeline"]),
         "eng": ("CI_Pipeline", ["Pipeline", "CI/CD pipeline", "build pipeline"]),
         "ops": ("Oil_Pipeline_Infrastructure", ["Pipeline", "supply pipeline", "logistics pipeline"]),
     }},
    {"surface": "Account",
     "per_source": {
         "sales": ("CRM_Account", ["Account", "customer account", "CRM account"]),
         "finance": ("GL_Account", ["Account", "GL account", "general ledger account"]),
         "eng": ("User_Account", ["Account", "user account", "service account"]),
         "hr": ("Employee_Account", ["Account", "employee account"]),
     }},
    {"surface": "Channel",
     "per_source": {
         "sales": ("Sales_Channel", ["Channel", "sales channel", "distribution channel"]),
         "marketing": ("Media_Channel", ["Channel", "marketing channel", "media channel"]),
         "eng": ("Slack_Channel", ["Channel", "slack channel"]),
     }},
    {"surface": "Lead",
     "per_source": {
         "sales": ("Sales_Lead", ["Lead", "sales lead", "qualified lead"]),
         "marketing": ("Marketing_Qualified_Lead", ["Lead", "MQL", "marketing lead"]),
         "ops": ("Lead_Time_Material", ["Lead", "lead time", "lead material"]),
     }},
    {"surface": "Order",
     "per_source": {
         "sales": ("Sales_Order", ["Order", "sales order", "SO"]),
         "ops": ("Purchase_Order", ["Order", "PO", "purchase order"]),
         "eng": ("Sort_Order", ["Order", "sort order", "ORDER BY clause"]),
     }},
    {"surface": "Service",
     "per_source": {
         "sales": ("Service_Offering", ["Service", "service offering", "professional service"]),
         "ops": ("Delivery_Service", ["Service", "delivery service", "fulfillment service"]),
         "eng": ("Microservice", ["Service", "microservice", "backend service"]),
     }},
    {"surface": "Brand",
     "per_source": {
         "marketing": ("Brand_Asset", ["Brand", "brand asset", "brand guideline"]),
         "legal": ("Trademark", ["Brand", "trademark", "registered brand"]),
         "eng": ("Brand_Color_Palette", ["Brand", "brand color", "brand CSS"]),
     }},
    {"surface": "Vendor",
     "per_source": {
         "sales": ("Vendor_Customer", ["Vendor", "reseller vendor"]),
         "ops": ("Supply_Vendor", ["Vendor", "supplier", "supply vendor"]),
         "finance": ("AP_Vendor", ["Vendor", "AP vendor", "accounts payable vendor"]),
     }},
    {"surface": "Region",
     "per_source": {
         "sales": ("Sales_Region", ["Region", "sales region", "territory region"]),
         "ops": ("Warehouse_Region", ["Region", "warehouse region", "distribution region"]),
         "eng": ("AWS_Region", ["Region", "AWS region", "cloud region"]),
     }},
    {"surface": "Tier",
     "per_source": {
         "sales": ("Customer_Tier", ["Tier", "customer tier", "account tier"]),
         "ops": ("Shipping_Tier", ["Tier", "shipping tier", "delivery tier"]),
         "eng": ("Cache_Tier", ["Tier", "cache tier", "storage tier"]),
     }},
]


def load():
    """Generate the deterministic workload stream."""
    from . import WorkloadEntry

    entries: list[WorkloadEntry] = []

    # GLOBAL: same oracle across sources
    for e in _GLOBAL:
        oracle = e["oracle"]
        for source, aliases in e["per_source"].items():
            for alias in aliases:
                entries.append(WorkloadEntry(source, alias, oracle))

    # PARTIAL: shared surface forms, source-subset-conditional oracle
    for e in _PARTIAL:
        for split in e["splits"]:
            oracle = split["oracle"]
            for source in split["sources"]:
                for alias in e["surface_forms"]:
                    entries.append(WorkloadEntry(source, alias, oracle))

    # CONDITIONAL: different meaning per source
    for e in _CONDITIONAL:
        for source, (oracle, aliases) in e["per_source"].items():
            for alias in aliases:
                entries.append(WorkloadEntry(source, alias, oracle))

    return entries


def stratum_for_canonical(canonical: str) -> str:
    """Returns 'global', 'partial', 'conditional', or 'unknown' based on
    which stratum the oracle canonical came from. Useful for source-aware
    metric breakdowns when those land in v0.4.1."""
    for e in _GLOBAL:
        if e["oracle"] == canonical:
            return "global"
    for e in _PARTIAL:
        for split in e["splits"]:
            if split["oracle"] == canonical:
                return "partial"
    for e in _CONDITIONAL:
        for source, (oracle, _aliases) in e["per_source"].items():
            if oracle == canonical:
                return "conditional"
    return "unknown"

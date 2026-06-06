"""W-CONCEPTNET-REL — synthetic ConceptNet 5.7 relation paraphrase workload.

Each canonical ConceptNet relation gets multiple surface forms (case
variants, snake/SCREAMING_SNAKE, paraphrases). The workload is a deterministic
stream of (input_surface_form, oracle_canonical) pairs.

A working schema-alignment proxy should achieve high pairwise F1 by
clustering surface forms back to their canonical bucket. A random-bucket
baseline should achieve ~1/k chance F1.
"""
from __future__ import annotations

# Canonical -> list of synonymous surface forms. Order is deterministic.
_SYNONYMS: dict[str, list[str]] = {
    "IsA": ["IsA", "is_a", "IS_A", "INSTANCE_OF", "type_of", "kind_of"],
    "PartOf": ["PartOf", "part_of", "PART_OF", "member_of", "belongs_to"],
    "HasA": ["HasA", "has_a", "HAS_A", "has_part", "contains_part"],
    "UsedFor": ["UsedFor", "used_for", "USED_FOR", "purpose_of", "function_of"],
    "CapableOf": ["CapableOf", "capable_of", "CAPABLE_OF", "can_do", "ABILITY_TO"],
    "AtLocation": ["AtLocation", "at_location", "AT_LOCATION", "located_at", "found_at"],
    "Causes": ["Causes", "causes", "CAUSES", "leads_to", "results_in", "produces"],
    "HasSubevent": ["HasSubevent", "has_subevent", "HAS_SUBEVENT", "includes_step"],
    "HasFirstSubevent": ["HasFirstSubevent", "has_first_subevent", "starts_with_step"],
    "HasLastSubevent": ["HasLastSubevent", "has_last_subevent", "ends_with_step"],
    "HasPrerequisite": ["HasPrerequisite", "has_prerequisite", "REQUIRES", "depends_on"],
    "HasProperty": ["HasProperty", "has_property", "HAS_PROPERTY", "has_attribute"],
    "MotivatedByGoal": ["MotivatedByGoal", "motivated_by_goal", "driven_by_goal"],
    "ObstructedBy": ["ObstructedBy", "obstructed_by", "blocked_by", "hindered_by"],
    "Desires": ["Desires", "desires", "DESIRES", "wants", "wishes_for"],
    "CreatedBy": ["CreatedBy", "created_by", "CREATED_BY", "made_by", "authored_by"],
    "Synonym": ["Synonym", "synonym", "SYNONYM", "same_as", "equivalent_to"],
    "Antonym": ["Antonym", "antonym", "ANTONYM", "opposite_of"],
    "DistinctFrom": ["DistinctFrom", "distinct_from", "different_from"],
    "DerivedFrom": ["DerivedFrom", "derived_from", "originates_from"],
    "SymbolOf": ["SymbolOf", "symbol_of", "represents"],
    "DefinedAs": ["DefinedAs", "defined_as", "is_defined_as"],
    "MannerOf": ["MannerOf", "manner_of", "way_of"],
    "LocatedNear": ["LocatedNear", "located_near", "near", "close_to"],
    "HasContext": ["HasContext", "has_context", "in_context_of"],
    "SimilarTo": ["SimilarTo", "similar_to", "resembles"],
    "EtymologicallyRelatedTo": ["EtymologicallyRelatedTo", "etymologically_related"],
    "EtymologicallyDerivedFrom": ["EtymologicallyDerivedFrom", "etymologically_derived_from"],
    "CausesDesire": ["CausesDesire", "causes_desire", "makes_want"],
    "MadeOf": ["MadeOf", "made_of", "MADE_OF", "composed_of", "consists_of"],
    "ReceivesAction": ["ReceivesAction", "receives_action", "acted_upon_by"],
    "ExternalURL": ["ExternalURL", "external_url", "EXTERNAL_LINK"],
    "RelatedTo": ["RelatedTo", "related_to", "RELATED_TO", "associated_with"],
    "FormOf": ["FormOf", "form_of", "variant_of"],
}


def load():
    """Return the deterministic workload stream.

    Each entry is one write event. Single-tenant workload, so source_id
    is "default" for every entry.
    """
    from . import WorkloadEntry

    entries: list[WorkloadEntry] = []
    for canonical, surface_forms in _SYNONYMS.items():
        for sf in surface_forms:
            entries.append(WorkloadEntry("default", sf, canonical))
    return entries


def oracle_cardinality() -> int:
    return len(_SYNONYMS)

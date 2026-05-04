"""
Zep entity labels → EcoSim canonical types mapping.

Zep Cloud's LLM extraction trả về `EntityNode.labels: List[str]` (vd
`["Entity", "Company"]`, `["Entity", "Person"]`). EcoSim có canonical types
hardcode ở `apps/simulation/campaign_knowledge.py` (CANONICAL_ENTITY_TYPES =
14 types: Company, Consumer, Investor, Regulator, Competitor, Supplier,
MediaOutlet, EconomicIndicator, Product, Market, Person, Organization,
Campaign, Policy).

Module này map Zep labels → canonical sao cho FalkorDB schema (`:Entity:<canonical>`)
nhất quán với existing direct-write path. Heuristic: exact match → alias map
→ fallback "Entity".

Usage:
    from ecosim_common.zep_label_map import zep_labels_to_canonical
    canonical = zep_labels_to_canonical(["Entity", "Company"])  # → "Company"
    canonical = zep_labels_to_canonical(["Entity", "Brand"])    # → "Company" (alias)
    canonical = zep_labels_to_canonical(["Entity", "Foo"])      # → "Entity" (fallback)
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("ecosim_common.zep_label_map")

# Canonical types EcoSim — sync với apps/simulation/campaign_knowledge.py
# CANONICAL_ENTITY_TYPES set. Update khi thay đổi schema.
CANONICAL_ENTITY_TYPES = frozenset({
    "Company",
    "Consumer",
    "Investor",
    "Regulator",
    "Competitor",
    "Supplier",
    "MediaOutlet",
    "EconomicIndicator",
    "Product",
    "Market",
    "Person",
    "Organization",
    "Campaign",
    "Policy",
})

# Alias map cho labels Zep extract khác canonical name của EcoSim. Mapping
# giống ENTITY_TYPE_ALIASES ở campaign_knowledge.py + thêm common Zep labels.
ZEP_LABEL_ALIASES = {
    # Direct EcoSim canonical mappings
    "Brand": "Company",
    "Audience": "Consumer",
    "Platform": "Company",
    "Event": "Campaign",
    "Location": "Market",
    "Place": "Market",
    "Metric": "EconomicIndicator",
    # Zep-common labels không có trong EcoSim canonical
    "Country": "Market",
    "City": "Market",
    "Region": "Market",
    "User": "Consumer",
    "Customer": "Consumer",
    "Demographic": "Consumer",
    "News": "MediaOutlet",
    "Publisher": "MediaOutlet",
    "Government": "Regulator",
    "Authority": "Regulator",
    "Service": "Product",
    "Feature": "Product",
    "Technology": "Product",
    # Reject (returned None → fallback "Entity")
    "Unknown": None,
    "Misc": None,
    "Other": None,
}


def zep_labels_to_canonical(labels: Optional[List[str]]) -> str:
    """Map Zep `EntityNode.labels` → canonical type string.

    Logic:
      1. Iterate qua labels (skip "Entity" — generic)
      2. Nếu label ∈ CANONICAL_ENTITY_TYPES → return luôn (exact match)
      3. Nếu label ∈ ZEP_LABEL_ALIASES → return alias (hoặc skip nếu None)
      4. Fallback "Entity" nếu không match cái nào

    Args:
        labels: List labels từ Zep node, vd ["Entity", "Company"].

    Returns:
        Canonical type string (one of CANONICAL_ENTITY_TYPES, hoặc "Entity").
    """
    if not labels:
        return "Entity"

    # Filter "Entity" (generic Graphiti label, không informative)
    candidates = [lab for lab in labels if lab and lab != "Entity"]

    if not candidates:
        return "Entity"

    # Exact match canonical
    for lab in candidates:
        if lab in CANONICAL_ENTITY_TYPES:
            return lab

    # Alias map
    for lab in candidates:
        if lab in ZEP_LABEL_ALIASES:
            mapped = ZEP_LABEL_ALIASES[lab]
            if mapped is None:
                continue  # rejected alias → try next
            logger.debug("Zep label '%s' → alias '%s'", lab, mapped)
            return mapped

    # Fallback — log so user thấy unmapped labels accumulate (có thể bổ sung)
    logger.info(
        "Zep label(s) %s không match canonical/alias, fallback 'Entity'", candidates,
    )
    return "Entity"


def is_safe_cypher_label(name: str) -> bool:
    """Validate label safe để inject vào Cypher (chống injection).

    FalkorDB Cypher chỉ chấp nhận ASCII [A-Za-z0-9_] cho label/relationship
    types. Python `str.isalnum()` là Unicode-aware nên Vietnamese diacritics
    (Ù, Ề, ...) đều pass — đó là BUG. Phải restrict ASCII only.
    """
    if not name:
        return False
    # ASCII alphanum + underscore. First char phải alpha (Cypher rule).
    if not (name[0].isascii() and name[0].isalpha()):
        return False
    return all(
        (c.isascii() and (c.isalnum() or c == "_"))
        for c in name
    )

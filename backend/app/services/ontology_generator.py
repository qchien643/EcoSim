"""
Ontology Generator — Define economic entity/edge types via LLM.

Given campaign text, determines which entity and edge types are relevant.
"""

import logging
from typing import List

from ..models.ontology import EntityType, EdgeType, OntologySpec
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.ontology")

ONTOLOGY_SYSTEM_PROMPT = """\
You are an economic domain expert. Given a campaign description, determine which entity \
types and relationship types are relevant for building a knowledge graph.

Available entity types:
Company, Consumer, Investor, Regulator, Competitor, Supplier, MediaOutlet, \
EconomicIndicator, Product, Market, Person, Organization, Campaign, Policy

Available edge types:
INVESTS_IN, COMPETES_WITH, SUPPLIES_TO, REGULATES, CONSUMES, REPORTS_ON, \
PARTNERS_WITH, AFFECTS, RUNS, TARGETS, PRODUCES, EMPLOYS

Return JSON:
{
    "entity_types": ["Company", "Consumer", ...],
    "edge_types": ["COMPETES_WITH", "AFFECTS", ...],
    "domain_description": "Brief description of the economic domain"
}

Rules:
- Select ONLY types that are actually relevant to the campaign
- Always include Campaign as an entity type
- Always include AFFECTS as an edge type
- Return ONLY valid JSON
"""


class OntologyGenerator:
    """Generate economic ontology from campaign text."""

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    def generate(self, campaign_text: str, campaign_type: str = "") -> OntologySpec:
        """Analyze campaign text → determine relevant entity/edge types."""
        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Campaign type: {campaign_type}\n\n"
                    f"Campaign text:\n{campaign_text[:4000]}"
                ),
            },
        ]

        result = self.llm.chat_json(messages, temperature=0.2, max_tokens=500)

        # Parse entity types
        entity_types = []
        for et in result.get("entity_types", []):
            try:
                entity_types.append(EntityType(et))
            except ValueError:
                logger.warning(f"Unknown entity type: {et}")

        # Parse edge types
        edge_types = []
        for et in result.get("edge_types", []):
            try:
                edge_types.append(EdgeType(et))
            except ValueError:
                logger.warning(f"Unknown edge type: {et}")

        # Ensure Campaign and AFFECTS are always included
        if EntityType.CAMPAIGN not in entity_types:
            entity_types.append(EntityType.CAMPAIGN)
        if EdgeType.AFFECTS not in edge_types:
            edge_types.append(EdgeType.AFFECTS)

        spec = OntologySpec(
            entity_types=entity_types,
            edge_types=edge_types,
            domain_description=result.get("domain_description", ""),
        )

        logger.info(
            f"Ontology generated: {len(spec.entity_types)} entities, "
            f"{len(spec.edge_types)} edges"
        )
        return spec

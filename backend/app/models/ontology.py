"""
Economic Ontology models — Entity and Edge type definitions for the KG.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Economic entity types for the Knowledge Graph."""
    COMPANY = "Company"
    CONSUMER = "Consumer"
    INVESTOR = "Investor"
    REGULATOR = "Regulator"
    COMPETITOR = "Competitor"
    SUPPLIER = "Supplier"
    MEDIA_OUTLET = "MediaOutlet"
    ECONOMIC_INDICATOR = "EconomicIndicator"
    PRODUCT = "Product"
    MARKET = "Market"
    PERSON = "Person"
    ORGANIZATION = "Organization"
    CAMPAIGN = "Campaign"
    POLICY = "Policy"


class EdgeType(str, Enum):
    """Economic relationship types."""
    INVESTS_IN = "INVESTS_IN"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPLIES_TO = "SUPPLIES_TO"
    REGULATES = "REGULATES"
    CONSUMES = "CONSUMES"
    REPORTS_ON = "REPORTS_ON"
    PARTNERS_WITH = "PARTNERS_WITH"
    AFFECTS = "AFFECTS"
    RUNS = "RUNS"
    TARGETS = "TARGETS"
    PRODUCES = "PRODUCES"
    EMPLOYS = "EMPLOYS"


class EntityNode(BaseModel):
    """An entity extracted from campaign text."""
    name: str
    entity_type: EntityType
    description: str = ""


class EntityEdge(BaseModel):
    """A relationship between two entities."""
    source: str
    target: str
    edge_type: EdgeType
    description: str = ""


class OntologySpec(BaseModel):
    """Complete ontology definition for a campaign domain."""
    entity_types: List[EntityType] = Field(default_factory=list)
    edge_types: List[EdgeType] = Field(default_factory=list)
    domain_description: str = ""


class ChunkExtractionResult(BaseModel):
    """Entities and edges extracted from a single text chunk."""
    entities: List[EntityNode] = Field(default_factory=list)
    edges: List[EntityEdge] = Field(default_factory=list)
    chunk_index: int = 0

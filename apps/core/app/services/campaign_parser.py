"""
Campaign Parser — Extract structured campaign data from raw text via LLM.

E2E Flow: U→API→CP→LLM→CampaignSpec
"""

import logging
from typing import List

from ..models.campaign import CampaignSpec, CampaignType
from ..utils.llm_client import LLMClient
from ..utils.file_parser import FileParser

logger = logging.getLogger("ecosim.campaign_parser")

EXTRACTION_SYSTEM_PROMPT = """\
You are an expert economic analyst. Extract structured campaign information from \
the given document. Return ONLY a JSON object with the following fields:

{
    "name": "Campaign name (string)",
    "campaign_type": "One of: marketing, pricing, expansion, policy, product_launch, other",
    "market": "Target market description (string)",
    "budget": "Budget estimate (string, keep original currency)",
    "timeline": "Campaign period (string)",
    "stakeholders": ["List of key stakeholder names/types"],
    "kpis": ["List of KPI metrics"],
    "identified_risks": ["List of identified risks"],
    "summary": "2-3 sentence summary of the campaign"
}

Rules:
- Extract ALL stakeholders mentioned, including competitors, regulators, media.
- For KPIs, extract specific metrics if mentioned (GMV, market share, etc.)
- For risks, extract both explicitly stated risks and implied ones.
- If a field is not found in the document, use empty string "" or empty list [].
- Return ONLY valid JSON, no explanations.
"""


class CampaignParser:
    """Parse campaign documents → structured CampaignSpec."""

    def __init__(self, llm_client: LLMClient = None, file_parser: FileParser = None):
        self.llm = llm_client or LLMClient()
        self.file_parser = file_parser or FileParser()

    def parse_file(self, file_path: str) -> CampaignSpec:
        """Parse a file → CampaignSpec.

        1. FileParser extracts text and splits into chunks
        2. LLM extracts structured campaign data
        3. Returns validated CampaignSpec
        """
        # Step 1: Parse file into text + chunks
        raw_text = self.file_parser.parse(file_path)
        chunks = self.file_parser.split_into_chunks(raw_text)
        logger.info(f"Parsed file: {len(raw_text)} chars → {len(chunks)} chunks")

        # Step 2: LLM extraction (send full text, not chunks)
        # For large docs, we could summarize chunks first, but for typical campaign
        # docs (<5000 chars) sending full text is fine.
        spec = self._extract_campaign_spec(raw_text)

        # Step 3: Attach raw data
        spec.raw_text = raw_text
        spec.chunks = chunks

        logger.info(
            f"Campaign parsed: '{spec.name}' | type={spec.campaign_type} | "
            f"{len(spec.stakeholders)} stakeholders | {len(spec.kpis)} KPIs"
        )
        return spec

    def parse_text(self, text: str) -> CampaignSpec:
        """Parse raw text → CampaignSpec."""
        chunks = self.file_parser.split_into_chunks(text)
        spec = self._extract_campaign_spec(text)
        spec.raw_text = text
        spec.chunks = chunks
        return spec

    def _extract_campaign_spec(self, text: str) -> CampaignSpec:
        """Use LLM to extract structured data from campaign text."""
        # Truncate if very long (GPT-4o-mini context = 128k, but keep cost low)
        max_chars = 8000
        input_text = text[:max_chars] if len(text) > max_chars else text

        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract campaign information from:\n\n{input_text}"},
        ]

        result = self.llm.chat_json(messages, temperature=0.2, max_tokens=1500)
        logger.debug(f"LLM extraction result keys: {list(result.keys())}")

        # Validate campaign_type
        raw_type = result.get("campaign_type", "other").lower()
        try:
            campaign_type = CampaignType(raw_type)
        except ValueError:
            campaign_type = CampaignType.OTHER

        return CampaignSpec(
            name=result.get("name", "Unnamed Campaign"),
            campaign_type=campaign_type,
            market=result.get("market", ""),
            budget=result.get("budget", ""),
            timeline=result.get("timeline", ""),
            stakeholders=result.get("stakeholders", []),
            kpis=result.get("kpis", []),
            identified_risks=result.get("identified_risks", []),
            summary=result.get("summary", ""),
        )

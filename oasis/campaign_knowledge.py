"""
Campaign Document Knowledge Extraction Pipeline
Chiết xuất thông tin từ tài liệu chiến dịch → nạp vào FalkorDB knowledge graph.

Pipeline 3 giai đoạn:
  Stage 1: PARSE — Tách tài liệu theo section headers
  Stage 2: ANALYZE — LLM phân tích từng section → trích xuất entities + facts
  Stage 3: LOAD — Nạp từng analyzed section vào Graphiti/FalkorDB as episodes
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("ecosim.campaign_knowledge")


# ======================================================================
# Data Models
# ======================================================================
@dataclass
class DocumentSection:
    """A parsed section from a campaign document."""
    title: str
    content: str
    level: int = 1  # heading level (1=H1, 2=H2, etc.)
    index: int = 0  # position in document
    metadata: Dict = field(default_factory=dict)

    def __repr__(self):
        return f"Section({self.index}: '{self.title}' [{len(self.content)} chars])"


@dataclass
class ExtractedEntity:
    """An entity extracted from a section by LLM."""
    name: str
    entity_type: str  # Campaign, Product, Audience, Brand, etc.
    description: str = ""


@dataclass
class ExtractedFact:
    """A structured fact extracted from a section."""
    subject: str
    predicate: str
    object: str

    def to_text(self) -> str:
        return f"{self.subject} {self.predicate} {self.object}"


@dataclass
class AnalyzedSection:
    """Result of LLM analysis on a document section."""
    original: DocumentSection
    summary: str  # Concise summary for episode_body
    entities: List[ExtractedEntity] = field(default_factory=list)
    facts: List[ExtractedFact] = field(default_factory=list)
    episode_name: str = ""

    def to_episode_body(self) -> str:
        """Build natural language episode body from analysis."""
        parts = [self.summary]
        if self.facts:
            facts_text = ". ".join(f.to_text() for f in self.facts)
            parts.append(facts_text)
        return " ".join(parts)


# ======================================================================
# Stage 1: Document Parser
# ======================================================================
class CampaignDocumentParser:
    """Parse campaign documents into semantic sections.

    Supports: Markdown (.md), plain text (.txt)
    Strategy: Split by headers/section boundaries, not arbitrary chunks.
    """

    def parse(self, file_path: str) -> List[DocumentSection]:
        """Parse document into semantic sections."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        ext = path.suffix.lower()

        if ext == ".md":
            sections = self._parse_markdown(content)
        elif ext in (".txt", ".text"):
            sections = self._parse_plaintext(content)
        elif ext == ".json":
            sections = self._parse_json(content)
        else:
            # Fallback: treat as plain text
            sections = self._parse_plaintext(content)

        # Add metadata
        for i, section in enumerate(sections):
            section.index = i
            section.metadata["source_file"] = path.name
            section.metadata["file_path"] = str(path.absolute())

        logger.info(
            "Parsed '%s' → %d sections", path.name, len(sections)
        )
        return sections

    def _parse_markdown(self, content: str) -> List[DocumentSection]:
        """Split markdown by headers (## or #)."""
        sections = []
        # Split by markdown headers
        header_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

        matches = list(header_pattern.finditer(content))

        if not matches:
            # No headers → treat entire doc as one section
            return [DocumentSection(
                title="Full Document",
                content=content.strip(),
                level=1,
            )]

        # Handle text before first header
        if matches[0].start() > 0:
            preamble = content[:matches[0].start()].strip()
            if preamble:
                sections.append(DocumentSection(
                    title="Overview",
                    content=preamble,
                    level=0,
                ))

        # Extract each header section
        for i, match in enumerate(matches):
            level = len(match.group(1))
            title = match.group(2).strip()

            # Content = text between this header and the next
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[start:end].strip()

            if body:  # Skip empty sections
                sections.append(DocumentSection(
                    title=title,
                    content=body,
                    level=level,
                ))

        return sections

    def _parse_plaintext(self, content: str) -> List[DocumentSection]:
        """Split plain text by blank-line-separated blocks with uppercase headers."""
        sections = []
        # Split by double newlines
        blocks = re.split(r"\n\s*\n", content)

        current_title = "Introduction"
        current_content = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Check if block starts with an uppercase line (likely a header)
            lines = block.split("\n")
            first_line = lines[0].strip()

            if (first_line.isupper() or
                first_line.endswith(":") or
                (len(first_line) < 80 and not first_line.endswith("."))):
                # Flush previous section
                if current_content:
                    sections.append(DocumentSection(
                        title=current_title,
                        content="\n".join(current_content),
                        level=1,
                    ))
                current_title = first_line.rstrip(":")
                current_content = lines[1:] if len(lines) > 1 else []
            else:
                current_content.append(block)

        # Flush last section
        if current_content:
            sections.append(DocumentSection(
                title=current_title,
                content="\n".join(current_content),
                level=1,
            ))

        return sections if sections else [DocumentSection(
            title="Full Document",
            content=content.strip(),
            level=1,
        )]

    def _parse_json(self, content: str) -> List[DocumentSection]:
        """Parse JSON campaign data into sections per key."""
        data = json.loads(content)
        sections = []

        if isinstance(data, dict):
            for key, value in data.items():
                body = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
                sections.append(DocumentSection(
                    title=key.replace("_", " ").title(),
                    content=body,
                    level=1,
                ))
        else:
            sections.append(DocumentSection(
                title="Campaign Data",
                content=json.dumps(data, ensure_ascii=False, indent=2),
                level=1,
            ))

        return sections


# ======================================================================
# Stage 2: Section Analyzer (LLM-based)
# ======================================================================
ANALYSIS_PROMPT = """You are a knowledge extraction expert. Analyze the following campaign document section and extract structured information.

## Section Title: {title}
## Section Content:
{content}

## Task
1. Write a concise summary (2-3 sentences) capturing the key information.
2. Extract key entities (people, brands, products, events, audiences, platforms).
3. Extract key facts as subject-predicate-object triples.

## Output Format (JSON)
{{
  "summary": "Concise summary of this section...",
  "entities": [
    {{"name": "Entity Name", "type": "Brand|Product|Event|Audience|Platform|Person|Location|Metric", "description": "Brief description"}}
  ],
  "facts": [
    {{"subject": "Subject", "predicate": "relationship verb", "object": "Object"}}
  ]
}}

IMPORTANT:
- Summary should be factual and self-contained (someone should understand it without reading the original)
- Entity names should be canonical (consistent naming)
- Facts should be specific and actionable
- Output ONLY valid JSON, no markdown fences
"""


class CampaignSectionAnalyzer:
    """LLM-based analysis of campaign document sections.

    Uses OpenAI-compatible API to extract entities, facts, and summaries.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def analyze(self, section: DocumentSection) -> AnalyzedSection:
        """Analyze a single section using LLM."""
        prompt = ANALYSIS_PROMPT.format(
            title=section.title,
            content=section.content[:3000],  # Cap to avoid token overflow
        )

        response = await self._call_llm(prompt)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                logger.warning(
                    "Failed to parse LLM response for section '%s', using raw summary",
                    section.title,
                )
                data = {
                    "summary": response[:500],
                    "entities": [],
                    "facts": [],
                }

        entities = [
            ExtractedEntity(
                name=e.get("name", ""),
                entity_type=e.get("type", "Unknown"),
                description=e.get("description", ""),
            )
            for e in data.get("entities", [])
            if e.get("name")
        ]

        facts = [
            ExtractedFact(
                subject=f.get("subject", ""),
                predicate=f.get("predicate", ""),
                object=f.get("object", ""),
            )
            for f in data.get("facts", [])
            if f.get("subject") and f.get("object")
        ]

        return AnalyzedSection(
            original=section,
            summary=data.get("summary", ""),
            entities=entities,
            facts=facts,
            episode_name=f"campaign_doc_{section.metadata.get('source_file', 'unknown')}_s{section.index}_{section.title[:40]}",
        )

    async def analyze_all(self, sections: List[DocumentSection]) -> List[AnalyzedSection]:
        """Analyze all sections sequentially (ordered for graph coherence)."""
        analyzed = []
        for i, section in enumerate(sections):
            logger.info(
                "  Analyzing section %d/%d: '%s' (%d chars)...",
                i + 1, len(sections), section.title, len(section.content),
            )
            try:
                result = await self.analyze(section)
                analyzed.append(result)
                logger.info(
                    "    → %d entities, %d facts extracted",
                    len(result.entities), len(result.facts),
                )
            except Exception as e:
                logger.error("    ✗ Failed to analyze '%s': %s", section.title, e)

        return analyzed

    async def _call_llm(self, prompt: str) -> str:
        """Call OpenAI-compatible API."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a knowledge extraction expert. Output only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


# ======================================================================
# Stage 3: Graph Loader
# ======================================================================
class CampaignGraphLoader:
    """Load analyzed campaign sections into FalkorDB via Graphiti.

    Uses the same group_id as the simulation for unified graph.
    """

    def __init__(
        self,
        falkor_host: str = "localhost",
        falkor_port: int = 6379,
        group_id: str = "default",
    ):
        self.falkor_host = falkor_host
        self.falkor_port = falkor_port
        self.group_id = group_id
        self._graphiti = None

    async def connect(self):
        """Initialize Graphiti connection to FalkorDB."""
        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver

        logger.info(
            "Connecting to FalkorDB at %s:%s (database=%s)...",
            self.falkor_host, self.falkor_port, self.group_id,
        )
        driver = FalkorDriver(
            host=self.falkor_host,
            port=self.falkor_port,
            database=self.group_id,
        )
        self._graphiti = Graphiti(graph_driver=driver)
        await self._graphiti.build_indices_and_constraints()
        logger.info("✅ FalkorDB Graphiti connected (database=%s)", self.group_id)

    async def close(self):
        """Close Graphiti connection."""
        if self._graphiti:
            await self._graphiti.close()
            logger.info("FalkorDB connection closed")

    async def load(
        self,
        sections: List[AnalyzedSection],
        source_description: str = "Campaign document",
        reference_time: Optional[datetime] = None,
    ) -> Dict:
        """Load analyzed sections into graph as episodes.

        Returns stats: {episodes_written, entities_total, facts_total}
        """
        from graphiti_core.nodes import EpisodeType

        if not self._graphiti:
            raise RuntimeError("Not connected. Call connect() first.")

        ref_time = reference_time or datetime.now(timezone.utc)
        stats = {"episodes_written": 0, "entities_total": 0, "facts_total": 0}

        for i, section in enumerate(sections):
            episode_body = section.to_episode_body()
            if not episode_body.strip():
                logger.warning("Skipping empty section: %s", section.original.title)
                continue

            logger.info(
                "  Loading section %d/%d: '%s' (%d chars → episode)...",
                i + 1, len(sections), section.original.title,
                len(episode_body),
            )

            try:
                await self._graphiti.add_episode(
                    name=section.episode_name,
                    episode_body=episode_body,
                    source=EpisodeType.text,
                    reference_time=ref_time,
                    source_description=source_description,
                    group_id=self.group_id,
                )
                stats["episodes_written"] += 1
                stats["entities_total"] += len(section.entities)
                stats["facts_total"] += len(section.facts)
                logger.info("    ✅ Episode loaded")

            except Exception as e:
                logger.error(
                    "    ✗ Failed to load section '%s': %s",
                    section.original.title, e,
                )

        return stats


# ======================================================================
# Full Pipeline
# ======================================================================
class CampaignKnowledgePipeline:
    """End-to-end pipeline: Document → Parse → Analyze → Load → FalkorDB.

    Usage:
        pipeline = CampaignKnowledgePipeline(
            api_key="sk-...",
            group_id="shopee_bf_2026",
        )
        stats = await pipeline.run("campaign_brief.md")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        falkor_host: str = "localhost",
        falkor_port: int = 6379,
        group_id: str = "default",
    ):
        self.parser = CampaignDocumentParser()
        self.analyzer = CampaignSectionAnalyzer(
            api_key=api_key, base_url=base_url, model=model
        )
        self.loader = CampaignGraphLoader(
            falkor_host=falkor_host,
            falkor_port=falkor_port,
            group_id=group_id,
        )
        self.group_id = group_id

    async def run(
        self,
        document_path: str,
        source_description: Optional[str] = None,
        reference_time: Optional[datetime] = None,
    ) -> Dict:
        """Run full pipeline: Parse → Analyze → Load.

        Returns:
            {
                "sections_parsed": int,
                "sections_analyzed": int,
                "episodes_written": int,
                "entities_total": int,
                "facts_total": int,
                "group_id": str,
            }
        """
        doc_name = Path(document_path).name
        src_desc = source_description or f"Campaign document: {doc_name}"

        logger.info("=" * 60)
        logger.info("📄 Campaign Knowledge Pipeline")
        logger.info("   Document: %s", document_path)
        logger.info("   Group ID: %s", self.group_id)
        logger.info("=" * 60)

        # Stage 1: Parse
        logger.info("\n📋 Stage 1: Parsing document...")
        sections = self.parser.parse(document_path)
        logger.info("   → %d sections extracted", len(sections))
        for s in sections:
            logger.info("   [%d] %s (%d chars)", s.index, s.title, len(s.content))

        # Stage 2: Analyze
        logger.info("\n🔍 Stage 2: Analyzing sections with LLM...")
        analyzed = await self.analyzer.analyze_all(sections)
        logger.info("   → %d sections analyzed", len(analyzed))

        # Stage 3: Load
        logger.info("\n📥 Stage 3: Loading into FalkorDB (group=%s)...", self.group_id)
        await self.loader.connect()
        try:
            stats = await self.loader.load(
                analyzed,
                source_description=src_desc,
                reference_time=reference_time,
            )
        finally:
            await self.loader.close()

        result = {
            "sections_parsed": len(sections),
            "sections_analyzed": len(analyzed),
            "group_id": self.group_id,
            **stats,
        }

        logger.info("\n✅ Pipeline complete!")
        logger.info("   Sections: %d parsed → %d analyzed → %d loaded",
                     result["sections_parsed"],
                     result["sections_analyzed"],
                     result["episodes_written"])
        logger.info("   Entities: %d | Facts: %d",
                     result["entities_total"], result["facts_total"])
        logger.info("   FalkorDB graph: %s", self.group_id)

        return result

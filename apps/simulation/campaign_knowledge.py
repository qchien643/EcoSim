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


# Canonical entity types (aligned với backend/app/models/ontology.py EntityType)
CANONICAL_ENTITY_TYPES = {
    "Company", "Consumer", "Investor", "Regulator", "Competitor", "Supplier",
    "MediaOutlet", "EconomicIndicator", "Product", "Market", "Person",
    "Organization", "Campaign", "Policy",
}

# Canonical edge types (aligned với EdgeType enum)
CANONICAL_EDGE_TYPES = {
    "INVESTS_IN", "COMPETES_WITH", "SUPPLIES_TO", "REGULATES", "CONSUMES",
    "REPORTS_ON", "PARTNERS_WITH", "AFFECTS", "RUNS", "TARGETS",
    "PRODUCES", "EMPLOYS",
}

# Map alias → canonical entity type
ENTITY_TYPE_ALIASES = {
    "Brand": "Company",
    "Audience": "Consumer",
    "Platform": "Company",
    "Event": "Campaign",
    "Location": "Market",
    "Metric": "EconomicIndicator",
    "Unknown": None,  # reject
}


@dataclass
class ExtractedEntity:
    """An entity extracted from a section by LLM."""
    name: str
    entity_type: str  # Canonical: Company, Consumer, Campaign, ...
    description: str = ""


@dataclass
class ExtractedFact:
    """A structured fact extracted from a section.

    `edge_type` là loại quan hệ canonical (COMPETES_WITH, SUPPLIES_TO, ...);
    `predicate` là câu tự nhiên (dùng cho description của edge và cho episode_body).
    """
    subject: str
    predicate: str
    object: str
    edge_type: str = "AFFECTS"  # Canonical EdgeType, default fallback

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


# ──────────────────────────────────────────────
# Serialization helpers cho cache extracted/sections.json + analyzed.json
# ──────────────────────────────────────────────
# Build idempotent: nếu cache file tồn tại → skip LLM stage, load từ disk.
# Force re-run: rm -rf <UPLOAD_DIR>/<campaign_id>/extracted/
_CACHE_VERSION = 1  # bump khi schema DocumentSection/AnalyzedSection thay đổi


def _save_sections(path, sections: "List[DocumentSection]") -> None:
    """Persist parsed DocumentSection list → JSON (Stage 2 cache)."""
    payload = {
        "_version": _CACHE_VERSION,
        "data": [
            {
                "title": s.title,
                "content": s.content,
                "level": s.level,
                "index": s.index,
                "metadata": s.metadata,
            }
            for s in sections
        ],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_sections(path) -> "Optional[List[DocumentSection]]":
    """Load DocumentSection list từ cache. Trả None nếu không có / version mismatch."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("_version") != _CACHE_VERSION:
            logger.info("sections.json version mismatch, re-extracting")
            return None
        return [DocumentSection(**d) for d in payload.get("data", [])]
    except Exception as e:
        logger.warning("Failed to load sections cache %s: %s — re-extracting", p, e)
        return None


def _save_analyzed(path, analyzed: "List[AnalyzedSection]") -> None:
    """Persist AnalyzedSection list (entities + facts) → JSON (Stage 3 cache).

    Đây là cache đắt nhất — mỗi section = 1 LLM call gpt-4o ~$0.01-0.03.
    """
    payload = {
        "_version": _CACHE_VERSION,
        "data": [
            {
                "original": {
                    "title": a.original.title,
                    "content": a.original.content,
                    "level": a.original.level,
                    "index": a.original.index,
                    "metadata": a.original.metadata,
                },
                "summary": a.summary,
                "entities": [
                    {"name": e.name, "entity_type": e.entity_type, "description": e.description}
                    for e in a.entities
                ],
                "facts": [
                    {"subject": f.subject, "predicate": f.predicate,
                     "object": f.object, "edge_type": f.edge_type}
                    for f in a.facts
                ],
                "episode_name": a.episode_name,
            }
            for a in analyzed
        ],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_analyzed(path) -> "Optional[List[AnalyzedSection]]":
    """Load AnalyzedSection list từ cache. None nếu không có / version mismatch."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("_version") != _CACHE_VERSION:
            logger.info("analyzed.json version mismatch, re-running LLM")
            return None
        result = []
        for a in payload.get("data", []):
            orig = DocumentSection(**a["original"])
            entities = [ExtractedEntity(**e) for e in a.get("entities", [])]
            facts = [ExtractedFact(**f) for f in a.get("facts", [])]
            result.append(AnalyzedSection(
                original=orig,
                summary=a.get("summary", ""),
                entities=entities,
                facts=facts,
                episode_name=a.get("episode_name", ""),
            ))
        return result
    except Exception as e:
        logger.warning("Failed to load analyzed cache %s: %s — re-running LLM", p, e)
        return None


# ======================================================================
# Stage 1: Document Parser
# ======================================================================
class CampaignDocumentParser:
    """Parse campaign documents into semantic sections.

    Supports: Markdown (.md), plain text (.txt)
    Strategy: Split by headers/section boundaries, not arbitrary chunks.
    """

    # Giới hạn size cho mỗi section khi feed vào LLM.
    # Section lớn hơn → chia nhỏ theo đoạn văn để tránh compression bias.
    MAX_SECTION_CHARS = 1500

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

        # Section size guard: split section > MAX_SECTION_CHARS
        sections = self._split_oversized(sections)

        # Add metadata
        for i, section in enumerate(sections):
            section.index = i
            section.metadata["source_file"] = path.name
            section.metadata["file_path"] = str(path.absolute())

        logger.info(
            "Parsed '%s' → %d sections (after size guard)", path.name, len(sections)
        )
        return sections

    def _split_oversized(
        self, sections: List[DocumentSection]
    ) -> List[DocumentSection]:
        """Tách section > MAX_SECTION_CHARS theo paragraph boundary.

        Giữ title gốc (thêm hậu tố " (part N)"), preserve level + metadata.
        """
        result: List[DocumentSection] = []
        for s in sections:
            if len(s.content) <= self.MAX_SECTION_CHARS:
                result.append(s)
                continue

            # Split theo double-newline (paragraph), gộp lại theo giới hạn
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", s.content) if p.strip()]
            buckets: List[List[str]] = []
            current: List[str] = []
            current_size = 0
            for p in paragraphs:
                p_size = len(p) + 2  # +2 cho \n\n
                # Nếu paragraph đơn lẻ quá lớn → bucket riêng (không còn cách nào)
                if p_size > self.MAX_SECTION_CHARS:
                    if current:
                        buckets.append(current)
                        current, current_size = [], 0
                    buckets.append([p])
                    continue
                if current_size + p_size > self.MAX_SECTION_CHARS and current:
                    buckets.append(current)
                    current, current_size = [p], p_size
                else:
                    current.append(p)
                    current_size += p_size
            if current:
                buckets.append(current)

            if len(buckets) == 1:
                result.append(s)
                continue

            for idx, bucket in enumerate(buckets, start=1):
                result.append(DocumentSection(
                    title=f"{s.title} (part {idx}/{len(buckets)})",
                    content="\n\n".join(bucket),
                    level=s.level,
                    metadata=dict(s.metadata),
                ))
            logger.debug(
                "Split oversized section '%s' (%d chars) → %d parts",
                s.title, len(s.content), len(buckets),
            )
        return result

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
ANALYSIS_PROMPT = """You are an expert at extracting economic entities and relationships from \
Vietnamese business/campaign documents for building a knowledge graph.

## Section Title: {title}
## Section Content:
{content}

## Task
1. Write a concise summary (2-3 sentences) capturing the key information.
2. Extract entities with CANONICAL entity types.
3. Extract facts as subject-predicate-object triples WITH a canonical edge_type.

## Valid Entity Types
Company, Consumer, Investor, Regulator, Competitor, Supplier, MediaOutlet, \
EconomicIndicator, Product, Market, Person, Organization, Campaign, Policy

## Valid Edge Types
INVESTS_IN, COMPETES_WITH, SUPPLIES_TO, REGULATES, CONSUMES, REPORTS_ON, \
PARTNERS_WITH, AFFECTS, RUNS, TARGETS, PRODUCES, EMPLOYS

## Output Format (JSON)
{{
  "summary": "Concise factual summary...",
  "entities": [
    {{"name": "Entity Name", "type": "Company", "description": "Brief desc"}}
  ],
  "facts": [
    {{"subject": "Entity A", "predicate": "competes with", "object": "Entity B", "edge_type": "COMPETES_WITH"}}
  ]
}}

## CRITICAL RULES (Vietnamese business domain)

### Entity extraction:
1. Entity names MUST be proper nouns or specific brand names, NOT generic words.
   - ✅ "Shopee", "Gen Z", "Bộ Công Thương"
   - ❌ "công ty", "người dùng", "thị trường" (generic)
2. Use EXACT entity type values from the valid list above. NO custom types.
3. Deduplicate: same entity mentioned multiple times = ONE entry.

### Entity classification:
- Social media platforms (Facebook, Instagram, TikTok, Zalo) → "Company" ONLY if a main \
  business actor. If mentioned as marketing channels → DO NOT extract.
- Sub-services/features ("Shopee Live", "Shopee Feed", "ShopeePay") → \
  DO NOT extract as separate entities. They are features of the parent company.
- Specific products (iPhone 16, Galaxy S24, AirPods) → type "Product", NOT "Campaign".
- Named campaign events ("Black Friday 2026", "12.12 Sale") → type "Campaign".
- Consumer segments ("Gen Z", "Millennial", "sinh viên") → type "Consumer".
- KOL/Influencer → type "Person" ONLY if a specific named individual; \
  generic "influencers" → DO NOT extract.
- Government bodies (Bộ Công Thương, Quốc hội) → type "Regulator".
- News/media outlets (VnExpress, Tuổi Trẻ) → type "MediaOutlet".
- Investors (SEA Group, Alibaba as parent) → type "Investor".
- Logistics/warehouse partners → type "Supplier".

### Naming rules:
- Use the canonical name: "Shopee" not "Shopee Vietnam" (unless truly different entity).
- Full brand + model for products: "iPhone 16 Pro Max".
- If text is cut mid-word or fragment → DO NOT create entity from fragment.
- Preserve Vietnamese diacritics: "Giao Hàng Nhanh" not "Giao Hang Nhanh".

### Facts/edges:
1. Extract IMPLICIT relationships — reason from context, don't require exact keywords.
   - "đối thủ của Shopee là Lazada" → (Shopee, COMPETES_WITH, Lazada)
   - "SEA Group sở hữu Shopee" → (SEA Group, INVESTS_IN, Shopee)
2. Both subject AND object MUST be entities in your entities list.
3. Choose the CLOSEST canonical edge_type. Use AFFECTS only when nothing else fits.
4. Keep natural-language `predicate` for readability (used as edge description).

### Quality:
- Aim for 5-10 entities per section (dense coverage). Single section should not have >15.
- Aim for 3-8 facts per section.
- If section is purely narrative/filler → return small counts, do NOT fabricate.

Output ONLY valid JSON. No markdown fences, no explanations before/after.
"""


class CampaignSectionAnalyzer:
    """LLM-based analysis of campaign document sections.

    Dùng shared `LLMClient` — hưởng retry + JSON parsing + strip code fences.
    Constructor args giữ nguyên cho backward-compat với call site hiện tại.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ):
        from ecosim_common.llm_client import LLMClient
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._llm = LLMClient(api_key=api_key, base_url=self.base_url, model=model)

    async def analyze(self, section: DocumentSection) -> AnalyzedSection:
        """Analyze a single section using LLM."""
        prompt = ANALYSIS_PROMPT.format(
            title=section.title,
            content=section.content[:3000],  # Cap to avoid token overflow
        )
        messages = [
            {"role": "system", "content": "You are a knowledge extraction expert. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ]

        try:
            data = await self._llm.chat_json_async(
                messages, temperature=0.1, max_tokens=2000,
            )
        except (ValueError, Exception) as e:
            logger.warning(
                "LLM analyze failed for section '%s': %s — returning empty extraction",
                section.title, e,
            )
            data = {"summary": "", "entities": [], "facts": []}

        entities = []
        for e in data.get("entities", []):
            name = (e.get("name") or "").strip()
            etype = (e.get("type") or "Unknown").strip()
            if not name or len(name) < 2:
                continue
            # Normalize alias → canonical type, hoặc reject nếu rác
            if etype in ENTITY_TYPE_ALIASES:
                canonical = ENTITY_TYPE_ALIASES[etype]
                if canonical is None:
                    continue  # "Unknown" — reject
                etype = canonical
            if etype not in CANONICAL_ENTITY_TYPES:
                logger.debug("Rejected entity '%s' with invalid type: %s", name, etype)
                continue
            entities.append(ExtractedEntity(
                name=name,
                entity_type=etype,
                description=e.get("description", ""),
            ))

        facts = []
        for f in data.get("facts", []):
            subj = (f.get("subject") or "").strip()
            obj = (f.get("object") or "").strip()
            if not subj or not obj:
                continue
            edge_type = (f.get("edge_type") or "AFFECTS").strip().upper()
            if edge_type not in CANONICAL_EDGE_TYPES:
                edge_type = "AFFECTS"
            facts.append(ExtractedFact(
                subject=subj,
                predicate=(f.get("predicate") or "").strip(),
                object=obj,
                edge_type=edge_type,
            ))

        return AnalyzedSection(
            original=section,
            summary=data.get("summary", ""),
            entities=entities,
            facts=facts,
            episode_name=f"campaign_doc_{section.metadata.get('source_file', 'unknown')}_s{section.index}_{section.title[:40]}",
        )

    async def analyze_all(
        self,
        sections: List[DocumentSection],
        batch_size: int = 5,
    ) -> List[AnalyzedSection]:
        """Analyze all sections in parallel batches.

        Trước đây sequential loop → 17 sections × 30-60s = 8-17 min cho cold
        cache. Giờ chạy parallel với asyncio.gather batch_size sections cùng
        lúc → ~5x speedup. Không quá lớn (batch=5) để tránh overwhelm
        provider RPM khi user dùng OpenAI tier 1.

        Section order preserved (gather giữ thứ tự input). Failed sections
        log + skip; section khác trong cùng batch không bị ảnh hưởng nhờ
        return_exceptions=True.

        Note: Stage 2 cache (`extracted/analyzed.json`) skip toàn bộ method
        này khi cache hit → optimization chỉ matter cho first build.
        """
        import asyncio

        async def _analyze_one(idx: int, section: DocumentSection) -> Optional[AnalyzedSection]:
            logger.info(
                "  Analyzing section %d/%d: '%s' (%d chars)...",
                idx + 1, len(sections), section.title, len(section.content),
            )
            try:
                result = await self.analyze(section)
                logger.info(
                    "    → '%s' done: %d entities, %d facts",
                    section.title, len(result.entities), len(result.facts),
                )
                return result
            except Exception as e:
                logger.error("    ✗ Failed to analyze '%s': %s", section.title, e)
                return None

        analyzed: List[AnalyzedSection] = []
        for batch_start in range(0, len(sections), batch_size):
            batch = sections[batch_start : batch_start + batch_size]
            batch_indexed = [(batch_start + j, s) for j, s in enumerate(batch)]
            results = await asyncio.gather(
                *[_analyze_one(idx, s) for idx, s in batch_indexed],
                return_exceptions=False,  # _analyze_one đã catch
            )
            for r in results:
                if r is not None:
                    analyzed.append(r)

        return analyzed


# ======================================================================
# Stage 2.5: Cross-section Post-processing
# ======================================================================
# Sub-services không tạo entity riêng, gộp vào parent nếu parent có trong graph
_SUB_SERVICE_TOKENS = ("Live", "Feed", "Pay", "Mall", "NOW", "Express")


def postprocess_entities(
    entities: List[ExtractedEntity],
    facts: List[ExtractedFact],
) -> tuple[List[ExtractedEntity], List[ExtractedFact], Dict[str, str]]:
    """Dedup + filter fragments + gộp sub-service → parent.

    Returns (cleaned_entities, cleaned_facts, name_map).
    `name_map` map từ tên gốc → tên canonical (dùng để fix edge references).
    """
    if not entities:
        return [], facts, {}

    # Step 1: filter rác (fragment/lowercase-no-space)
    valid = []
    for e in entities:
        name = e.name.strip()
        if len(name) < 2:
            continue
        if name and name[0].islower() and " " not in name:
            logger.debug("Filtered fragment entity: '%s'", name)
            continue
        valid.append(e)

    # Step 2: canonical dedup — entity ngắn hơn là canonical (e.g. "Shopee" < "Shopee Việt Nam")
    name_map: Dict[str, str] = {}
    sorted_entities = sorted(valid, key=lambda e: len(e.name))
    deduped: List[ExtractedEntity] = []
    seen: Dict[str, ExtractedEntity] = {}  # lowercase_name → entity

    for entity in sorted_entities:
        ename_lower = entity.name.lower()
        merged = False
        for canon_lower, canon_entity in list(seen.items()):
            if canon_lower == ename_lower:
                merged = True
                break
            # canonical "shopee" chứa trong "shopee việt nam" → merge xuống
            if canon_lower in ename_lower and canon_lower != ename_lower:
                name_map[entity.name] = canon_entity.name
                merged = True
                logger.debug("Merged '%s' → '%s'", entity.name, canon_entity.name)
                break
        if not merged:
            seen[ename_lower] = entity
            deduped.append(entity)

    # Step 3: sub-service filter — "ShopeePay" → gộp vào "Shopee" nếu "Shopee" đã có
    parent_names_lower = {e.name.lower() for e in deduped}
    final_entities: List[ExtractedEntity] = []
    for entity in deduped:
        is_sub = False
        for token in _SUB_SERVICE_TOKENS:
            if token in entity.name:
                base = entity.name.replace(token, "").strip()
                base_lower = base.lower()
                if base and base_lower in parent_names_lower and base_lower != entity.name.lower():
                    name_map[entity.name] = base
                    is_sub = True
                    logger.debug(
                        "Filtered sub-service '%s' → '%s'", entity.name, base
                    )
                    break
        if not is_sub:
            final_entities.append(entity)

    # Step 4: fix fact/edge references — cập nhật subject/object theo name_map
    final_names_lower = {e.name.lower() for e in final_entities}
    fixed_facts: List[ExtractedFact] = []
    for fact in facts:
        subj = name_map.get(fact.subject, fact.subject)
        obj = name_map.get(fact.object, fact.object)
        if subj.lower() in final_names_lower and obj.lower() in final_names_lower:
            fixed_facts.append(ExtractedFact(
                subject=subj,
                predicate=fact.predicate,
                object=obj,
                edge_type=fact.edge_type,
            ))

    logger.info(
        "Post-processing: entities %d → %d, facts %d → %d, %d renames",
        len(entities), len(final_entities), len(facts), len(fixed_facts),
        len(name_map),
    )
    return final_entities, fixed_facts, name_map


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
        self._raw_graph = None  # falkordb.Graph cho direct Cypher MERGE

    def _get_raw_graph(self):
        """Lấy kết nối raw FalkorDB cho structured MERGE (cùng database với Graphiti)."""
        if self._raw_graph is None:
            try:
                from falkordb import FalkorDB
                client = FalkorDB(host=self.falkor_host, port=self.falkor_port)
                self._raw_graph = client.select_graph(self.group_id)
                logger.debug("Raw FalkorDB graph opened: %s", self.group_id)
            except Exception as e:
                logger.warning("Raw FalkorDB connection failed: %s", e)
                return None
        return self._raw_graph

    def merge_structured(
        self,
        entities: List[ExtractedEntity],
        facts: List[ExtractedFact],
    ) -> Dict[str, int]:
        """Direct Cypher MERGE entities + facts vào FalkorDB với proper labels.

        Entities được tạo với label canonical (:Company, :Consumer, ...) — tách biệt
        với node :Entity của Graphiti (Graphiti tự tạo :Entity khi add_episode).
        """
        graph = self._get_raw_graph()
        if graph is None:
            logger.warning("Skip merge_structured: FalkorDB unavailable")
            return {"nodes_merged": 0, "edges_merged": 0}

        nodes_merged = 0
        for e in entities:
            try:
                # Label được lấy từ entity_type canonical — an toàn vì đã validate
                cypher = (
                    f"MERGE (n:{e.entity_type} {{name: $name}}) "
                    "SET n.description = COALESCE(n.description, '') + "
                    "CASE WHEN $desc <> '' AND NOT n.description CONTAINS $desc "
                    "THEN CASE WHEN n.description = '' THEN $desc ELSE '. ' + $desc END "
                    "ELSE '' END, "
                    "n.entity_type = $etype, "
                    "n.group_id = $gid "
                    "RETURN n"
                )
                graph.query(cypher, params={
                    "name": e.name,
                    "desc": e.description or "",
                    "etype": e.entity_type,
                    "gid": self.group_id,
                })
                nodes_merged += 1
            except Exception as exc:
                logger.warning("MERGE node '%s' failed: %s", e.name, exc)

        edges_merged = 0
        for f in facts:
            try:
                # MATCH any labeled node by name (không biết label chính xác của subject/object
                # vì có thể merge trước đó với label khác)
                cypher = (
                    "MATCH (a {name: $src}), (b {name: $tgt}) "
                    "WHERE a.group_id = $gid AND b.group_id = $gid "
                    f"MERGE (a)-[r:{f.edge_type}]->(b) "
                    "SET r.description = $desc, r.predicate = $pred "
                    "RETURN r"
                )
                result = graph.query(cypher, params={
                    "src": f.subject,
                    "tgt": f.object,
                    "gid": self.group_id,
                    "desc": f"{f.subject} {f.predicate} {f.object}",
                    "pred": f.predicate,
                })
                if result.result_set:
                    edges_merged += 1
            except Exception as exc:
                logger.warning(
                    "MERGE edge %s -[%s]-> %s failed: %s",
                    f.subject, f.edge_type, f.object, exc,
                )

        logger.info(
            "Structured merge: %d nodes, %d edges MERGED into '%s'",
            nodes_merged, edges_merged, self.group_id,
        )
        return {"nodes_merged": nodes_merged, "edges_merged": edges_merged}

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
        extracted_dir=None,
    ):
        """Args:
            extracted_dir: Path tới `<UPLOAD_DIR>/<campaign_id>/extracted/`
                để cache sections.json + analyzed.json. None → no cache,
                LLM stages chạy mỗi lần. Caller (build_graph endpoint) pass
                `EcoSimConfig.campaign_extracted_dir(campaign_id)`.
        """
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
        self.extracted_dir = extracted_dir

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

        # Stage 2.5: Cross-section post-processing (dedup + sub-service filter)
        logger.info("\n🧹 Stage 2.5: Post-processing entities across sections...")
        all_entities: List[ExtractedEntity] = []
        all_facts: List[ExtractedFact] = []
        for s in analyzed:
            all_entities.extend(s.entities)
            all_facts.extend(s.facts)
        clean_entities, clean_facts, _name_map = postprocess_entities(
            all_entities, all_facts
        )
        logger.info(
            "   → %d canonical entities, %d facts after cleanup",
            len(clean_entities), len(clean_facts),
        )

        # Stage 3: Load
        logger.info("\n📥 Stage 3: Loading into FalkorDB (group=%s)...", self.group_id)
        await self.loader.connect()
        try:
            # 3a — Structured MERGE: entities/facts với proper labels (primary)
            struct_stats = self.loader.merge_structured(clean_entities, clean_facts)

            # 3b — Graphiti add_episode: auxiliary search index (BM25 + Vector + RRF)
            episode_stats = await self.loader.load(
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
            "entities_extracted": len(all_entities),
            "entities_canonical": len(clean_entities),
            "facts_extracted": len(all_facts),
            "facts_canonical": len(clean_facts),
            **struct_stats,     # nodes_merged, edges_merged
            **episode_stats,    # episodes_written, entities_total, facts_total
        }

        logger.info("\n✅ Pipeline complete!")
        logger.info("   Sections: %d parsed → %d analyzed", len(sections), len(analyzed))
        logger.info(
            "   Structured: %d nodes, %d edges MERGED (canonical labels)",
            result["nodes_merged"], result["edges_merged"],
        )
        logger.info(
            "   Graphiti:   %d episodes indexed (for hybrid search)",
            result["episodes_written"],
        )
        logger.info("   FalkorDB graph: %s", self.group_id)

        return result

    async def run_from_text(
        self,
        text: str,
        doc_name: str = "campaign_text",
        source_description: Optional[str] = None,
        reference_time: Optional[datetime] = None,
    ) -> Dict:
        """Run pipeline trực tiếp từ text (không qua file).

        Dùng cho endpoint `/api/graph/build` khi text lấy từ spec.json chunks.
        Content được parse bằng markdown splitter (nếu có heading) hoặc plaintext.
        """
        src_desc = source_description or f"Campaign document: {doc_name}"
        logger.info("=" * 60)
        logger.info("📄 Campaign Knowledge Pipeline (from text)")
        logger.info("   Doc name: %s (%d chars)", doc_name, len(text))
        logger.info("   Group ID: %s", self.group_id)
        logger.info("   Cache dir: %s", self.extracted_dir or "(disabled)")
        logger.info("=" * 60)

        # Build progress tracker — write JSON file mỗi stage để frontend
        # poll show "stage X: Y" thay vì "building..." chung chung.
        from build_progress import start as _bp_start, update as _bp_update
        _bp_start(self.group_id, "Initializing pipeline...")

        # Path setup cho cache
        sections_cache = None
        analyzed_cache = None
        if self.extracted_dir:
            sections_cache = Path(self.extracted_dir) / "sections.json"
            analyzed_cache = Path(self.extracted_dir) / "analyzed.json"

        # ─── Stage 1: Parse text (with cache) ───
        _bp_update(self.group_id, "stage_1_parse", 5, "Parsing document sections...")
        sections = _load_sections(sections_cache) if sections_cache else None
        if sections is not None:
            logger.info("\n📋 Stage 1: SKIPPED (loaded %d sections từ cache)", len(sections))
            _bp_update(
                self.group_id, "stage_1_cache_hit", 10,
                f"Loaded {len(sections)} sections từ cache",
            )
        else:
            logger.info("\n📋 Stage 1: Parsing text...")
            if "#" in text.split("\n", 1)[0] or re.search(r"^#{1,4}\s+", text, re.MULTILINE):
                sections = self.parser._parse_markdown(text)
            else:
                sections = self.parser._parse_plaintext(text)
            sections = self.parser._split_oversized(sections)
            for i, s in enumerate(sections):
                s.index = i
                s.metadata.setdefault("source_file", doc_name)
            logger.info("   → %d sections", len(sections))
            if sections_cache:
                _save_sections(sections_cache, sections)
                logger.info("   💾 Saved sections cache: %s", sections_cache)
            _bp_update(
                self.group_id, "stage_1_done", 10,
                f"Parsed {len(sections)} sections",
            )

        # ─── Stage 2: Analyze (with cache — biggest cost savings) ───
        analyzed = _load_analyzed(analyzed_cache) if analyzed_cache else None
        if analyzed is not None:
            logger.info("\n🔍 Stage 2: SKIPPED (loaded %d analyzed sections từ cache, NO LLM cost)", len(analyzed))
            _bp_update(
                self.group_id, "stage_2_cache_hit", 50,
                f"Loaded {len(analyzed)} analyzed sections từ cache (skip LLM)",
            )
        else:
            logger.info("\n🔍 Stage 2: Analyzing sections with LLM (extraction model)...")
            _bp_update(
                self.group_id, "stage_2_analyzing", 15,
                f"LLM analyze {len(sections)} sections (gpt-4o)...",
            )
            analyzed = await self.analyzer.analyze_all(sections)
            logger.info("   → %d sections analyzed", len(analyzed))
            if analyzed_cache:
                _save_analyzed(analyzed_cache, analyzed)
                logger.info("   💾 Saved analyzed cache: %s", analyzed_cache)
            _bp_update(
                self.group_id, "stage_2_done", 50,
                f"Analyzed {len(analyzed)} sections",
            )

        # Stage 2.5: Post-processing (always run, cheap)
        _bp_update(
            self.group_id, "stage_2_5_postprocess", 55,
            "Deduplicating entities + canonical map...",
        )
        all_entities: List[ExtractedEntity] = []
        all_facts: List[ExtractedFact] = []
        for s in analyzed:
            all_entities.extend(s.entities)
            all_facts.extend(s.facts)
        clean_entities, clean_facts, _ = postprocess_entities(all_entities, all_facts)

        # ─── Stage 3: Dispatch theo KG_BUILDER env ───
        # zep_hybrid: Zep server-side LLM extract → mirror FalkorDB (rich)
        # direct: Stage 2 entities → direct Cypher write (fast, info-lossy)
        # graphiti: Legacy add_episode (slow, fallback debug)
        from ecosim_common.config import EcoSimConfig
        kg_builder = EcoSimConfig.kg_builder()
        logger.info("\n📥 Stage 3: KG_BUILDER=%s", kg_builder)

        if kg_builder == "zep_hybrid":
            from ecosim_common.zep_client import ZepKeyMissing
            try:
                from zep_kg_writer import write_kg_via_zep
                # Zep extract dùng `analyzed` cho `original.content` chỉ —
                # Zep tự extract entities/facts (KHÔNG dùng Stage 2 output)
                result_stage3 = await write_kg_via_zep(
                    graph_name=self.group_id,
                    sections=analyzed,
                    llm=self.analyzer._llm,
                    falkor_host=self.loader.falkor_host,
                    falkor_port=self.loader.falkor_port,
                    extracted_dir=self.extracted_dir,
                    source_description=src_desc,
                    reference_time=reference_time,
                )
            except ZepKeyMissing as e:
                logger.warning(
                    "Zep unavailable (%s) — fallback KG_BUILDER=direct", e,
                )
                kg_builder = "direct"  # fall through to direct path
            except Exception as e:
                logger.error(
                    "Zep build failed: %s — fallback direct path", e, exc_info=True,
                )
                kg_builder = "direct"

        if kg_builder == "direct":
            _bp_update(
                self.group_id, "stage_3_writing", 65,
                f"Direct Cypher write: {len(clean_entities)} entities + "
                f"{len(clean_facts)} facts + {len(analyzed)} episodes...",
            )
            from kg_direct_writer import write_kg_direct
            result_stage3 = await write_kg_direct(
                graph_name=self.group_id,
                sections=analyzed,
                entities=clean_entities,
                facts=clean_facts,
                llm=self.analyzer._llm,
                falkor_host=self.loader.falkor_host,
                falkor_port=self.loader.falkor_port,
                source_description=src_desc,
                reference_time=reference_time,
            )

        # graphiti path: KHÔNG support nữa trong dispatch (legacy code in
        # CampaignGraphLoader.load() vẫn hoạt động nhưng dispatch chỉ
        # accept zep_hybrid/direct). User cần explicit gọi loader.load qua
        # script.

        _bp_update(
            self.group_id, "stage_3_indexes", 95,
            "Building Graphiti indexes (HNSW vector + lookup)...",
        )

        result = {
            "sections_parsed": len(sections),
            "sections_analyzed": len(analyzed),
            "group_id": self.group_id,
            "entities_extracted": len(all_entities),
            "entities_canonical": len(clean_entities),
            "facts_extracted": len(all_facts),
            "facts_canonical": len(clean_facts),
            **result_stage3,  # nodes_merged, edges_merged, episodes_written, mentions_written, ...
        }
        logger.info(
            "✅ Direct write: %d nodes + %d edges + %d episodes (%.1fs)",
            result["nodes_merged"], result["edges_merged"],
            result["episodes_written"], result_stage3["elapsed_ms"] / 1000,
        )
        from build_progress import done as _bp_done
        _bp_done(
            self.group_id,
            f"Build done: {result['nodes_merged']} nodes, {result['edges_merged']} edges, "
            f"{result['episodes_written']} episodes",
        )
        return result

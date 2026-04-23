"""
Document parser — PDF/MD/TXT → text → chunks.

Merge 2 implementation cũ:
  - backend/app/utils/file_parser.py `FileParser` (3-tier: markdown → semantic → size)
  - oasis/campaign_knowledge.py `CampaignDocumentParser` (section-based: markdown headers)

Cả 2 tái export từ file này. API cũ giữ nguyên — call site hiện có không cần đổi.

API chính:
  - `FileParser.parse(path) -> str`              # full text
  - `FileParser.parse_and_chunk(path) -> list`   # 3-tier chunking
  - `FileParser.split_into_chunks(text) -> list`
  - `CampaignDocumentParser.parse(path) -> list[DocumentSection]`
  - `parse_markdown(text)`, `parse_plaintext(text)` module-level helpers
  - `split_oversized(sections, max_chars)` — cắt section > max_chars
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("ecosim_common.file_parser")

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".markdown"}
DEFAULT_MAX_SECTION_CHARS = 1500
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 200


# ════════════════════════════════════════════════════════════════
# Raw text extraction (shared)
# ════════════════════════════════════════════════════════════════

def extract_text(file_path: str) -> str:
    """Extract raw text from PDF/MD/TXT."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {ext}. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if ext == ".pdf":
        return _parse_pdf(file_path)
    if ext == ".json":
        return Path(file_path).read_text(encoding="utf-8")
    return _parse_text(file_path)


def _parse_pdf(file_path: str) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise ImportError("PyMuPDF required for PDF: pip install PyMuPDF") from e
    doc = fitz.open(file_path)
    pages = [doc.load_page(i).get_text() for i in range(len(doc))]
    doc.close()
    text = "\n\n".join(pages)
    logger.info("PDF parsed: %d pages, %d chars", len(pages), len(text))
    return text


def _parse_text(file_path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode file: {file_path}")


# ════════════════════════════════════════════════════════════════
# Section-based parsing (ported từ oasis/campaign_knowledge.py)
# ════════════════════════════════════════════════════════════════

@dataclass
class DocumentSection:
    """A parsed section from a campaign document."""
    title: str
    content: str
    level: int = 1
    index: int = 0
    metadata: Dict = field(default_factory=dict)

    def __repr__(self):
        return f"Section({self.index}: '{self.title}' [{len(self.content)} chars])"


def parse_markdown(content: str) -> List[DocumentSection]:
    """Split markdown theo header `#`, `##`, `###`, `####`."""
    sections: List[DocumentSection] = []
    header_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
    matches = list(header_pattern.finditer(content))

    if not matches:
        return [DocumentSection(title="Full Document", content=content.strip(), level=1)]

    if matches[0].start() > 0:
        preamble = content[: matches[0].start()].strip()
        if preamble:
            sections.append(DocumentSection(title="Overview", content=preamble, level=0))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            sections.append(DocumentSection(title=title, content=body, level=level))
    return sections


def parse_plaintext(content: str) -> List[DocumentSection]:
    """Split plain text theo double-newline, heuristic header detection."""
    sections: List[DocumentSection] = []
    blocks = re.split(r"\n\s*\n", content)
    current_title = "Introduction"
    current_content: List[str] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        first = lines[0].strip()
        if first.isupper() or first.endswith(":") or (len(first) < 80 and not first.endswith(".")):
            if current_content:
                sections.append(
                    DocumentSection(title=current_title, content="\n".join(current_content), level=1)
                )
            current_title = first.rstrip(":")
            current_content = lines[1:] if len(lines) > 1 else []
        else:
            current_content.append(block)

    if current_content:
        sections.append(
            DocumentSection(title=current_title, content="\n".join(current_content), level=1)
        )
    return sections or [DocumentSection(title="Full Document", content=content.strip(), level=1)]


def parse_json_sections(content: str) -> List[DocumentSection]:
    """Parse JSON → 1 section per top-level key."""
    data = json.loads(content)
    sections: List[DocumentSection] = []
    if isinstance(data, dict):
        for key, value in data.items():
            body = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
            sections.append(DocumentSection(title=key.replace("_", " ").title(), content=body, level=1))
    else:
        sections.append(DocumentSection(
            title="Campaign Data", content=json.dumps(data, ensure_ascii=False, indent=2), level=1,
        ))
    return sections


def split_oversized(
    sections: List[DocumentSection],
    max_chars: int = DEFAULT_MAX_SECTION_CHARS,
) -> List[DocumentSection]:
    """Tách section > max_chars theo paragraph boundary."""
    result: List[DocumentSection] = []
    for s in sections:
        if len(s.content) <= max_chars:
            result.append(s)
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", s.content) if p.strip()]
        buckets: List[List[str]] = []
        current: List[str] = []
        current_size = 0
        for p in paragraphs:
            p_size = len(p) + 2
            if p_size > max_chars:
                if current:
                    buckets.append(current)
                    current, current_size = [], 0
                buckets.append([p])
                continue
            if current_size + p_size > max_chars and current:
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
    return result


class CampaignDocumentParser:
    """Section-based parser — giữ API của oasis/campaign_knowledge.

    Internally dùng `parse_markdown` / `parse_plaintext` / `split_oversized` module-level.
    """

    MAX_SECTION_CHARS = DEFAULT_MAX_SECTION_CHARS

    def parse(self, file_path: str) -> List[DocumentSection]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")
        content = path.read_text(encoding="utf-8")
        ext = path.suffix.lower()
        if ext == ".md":
            sections = parse_markdown(content)
        elif ext == ".json":
            sections = parse_json_sections(content)
        else:
            sections = parse_plaintext(content)
        sections = split_oversized(sections, self.MAX_SECTION_CHARS)
        for i, s in enumerate(sections):
            s.index = i
            s.metadata["source_file"] = path.name
            s.metadata["file_path"] = str(path.absolute())
        logger.info("Parsed '%s' → %d sections (after size guard)", path.name, len(sections))
        return sections

    # Backward-compat aliases — oasis/campaign_knowledge.py gọi các _method
    def _parse_markdown(self, content: str) -> List[DocumentSection]:
        return parse_markdown(content)

    def _parse_plaintext(self, content: str) -> List[DocumentSection]:
        return parse_plaintext(content)

    def _parse_json(self, content: str) -> List[DocumentSection]:
        return parse_json_sections(content)

    def _split_oversized(self, sections: List[DocumentSection]) -> List[DocumentSection]:
        return split_oversized(sections, self.MAX_SECTION_CHARS)


# ════════════════════════════════════════════════════════════════
# 3-tier chunking (ported từ backend/app/utils/file_parser.py)
# ════════════════════════════════════════════════════════════════

class FileParser:
    """Parse documents và chia chunks tier-based.

    Tier 1: MarkdownHeaderTextSplitter
    Tier 2: SemanticChunker (OpenAI embeddings)
    Tier 3: RecursiveCharacterTextSplitter (size guard)
    """

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        use_semantic: bool = True,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_semantic = use_semantic

    def parse(self, file_path: str) -> str:
        return extract_text(file_path)

    def parse_and_chunk(self, file_path: str) -> List[str]:
        text = self.parse(file_path)
        chunks = self.split_into_chunks(text)
        logger.info("Parsed %s: %d chars → %d chunks", file_path, len(text), len(chunks))
        return chunks

    def split_into_chunks(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        if not text or not text.strip():
            return []
        text = text.strip()
        size = chunk_size or self.chunk_size
        overlap = chunk_overlap or self.chunk_overlap
        try:
            return self._smart_chunk(text, size, overlap)
        except Exception as e:
            logger.warning("Smart chunking failed, falling back to basic: %s", e)
            return self._basic_chunk(text, size, overlap)

    def _smart_chunk(self, text: str, size: int, overlap: int) -> List[str]:
        sections = self._split_by_markdown(text)
        logger.info("Tier 1 (Markdown): %d sections", len(sections))
        if self.use_semantic:
            semantic_chunks = self._semantic_split(sections, size)
            logger.info("Tier 2 (Semantic): %d chunks", len(semantic_chunks))
        else:
            semantic_chunks = sections
        final = self._size_guard(semantic_chunks, size, overlap)
        logger.info("Tier 3 (Size Guard): %d final chunks", len(final))
        return final

    def _split_by_markdown(self, text: str) -> List[str]:
        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter
            splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
                strip_headers=False,
            )
            docs = splitter.split_text(text)
            sections = []
            for doc in docs:
                content = doc.page_content.strip()
                if not content:
                    continue
                header_prefix = ""
                for key in ("h1", "h2", "h3"):
                    if key in doc.metadata:
                        header_prefix += f"[{doc.metadata[key]}] "
                if header_prefix:
                    content = f"{header_prefix.strip()}\n{content}"
                sections.append(content)
            return sections if sections else [text]
        except ImportError:
            return [s.strip() for s in re.split(r"\n(?=#{1,3}\s)", text) if s.strip()]

    def _semantic_split(self, sections: List[str], max_size: int) -> List[str]:
        try:
            from langchain_experimental.text_splitter import SemanticChunker
            from langchain_openai import OpenAIEmbeddings
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            chunker = SemanticChunker(
                embeddings=embeddings,
                breakpoint_threshold_type="percentile",
                breakpoint_threshold_amount=75,
            )
            out: List[str] = []
            for section in sections:
                if len(section) > max_size:
                    try:
                        out.extend(chunker.split_text(section))
                    except Exception as e:
                        logger.debug("Semantic split failed, keep: %s", e)
                        out.append(section)
                else:
                    out.append(section)
            return out
        except ImportError:
            logger.warning("SemanticChunker unavailable, skip semantic splitting")
            return sections
        except Exception as e:
            logger.warning("Semantic chunking error: %s", e)
            return sections

    def _size_guard(self, chunks: List[str], size: int, overlap: int) -> List[str]:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                separators=["\n\n", "\n", ". ", ", ", " "],
                length_function=len,
            )
            out: List[str] = []
            for chunk in chunks:
                if len(chunk) > size:
                    out.extend(splitter.split_text(chunk))
                elif chunk.strip():
                    out.append(chunk.strip())
            return out
        except ImportError:
            out: List[str] = []
            for chunk in chunks:
                if len(chunk) > size:
                    out.extend(self._basic_chunk(chunk, size, overlap))
                elif chunk.strip():
                    out.append(chunk.strip())
            return out

    def _basic_chunk(self, text: str, size: int, overlap: int) -> List[str]:
        if len(text) <= size:
            return [text]
        out: List[str] = []
        start = 0
        while start < len(text):
            end = start + size
            chunk = text[start:end].strip()
            if chunk:
                out.append(chunk)
            start = end - overlap
        return out

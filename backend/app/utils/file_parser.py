"""
File Parser — Smart document parsing with semantic-aware chunking.

3-Tier Chunking Strategy:
  Tier 1: Markdown structure splitting (headings)
  Tier 2: Semantic chunking within sections (embedding similarity)
  Tier 3: Safety limit with RecursiveCharacterTextSplitter

Pipeline: Raw Text → Markdown Split → Semantic Split → Size Guard → Chunks
"""

import logging
import os
from typing import List, Optional

logger = logging.getLogger("ecosim.parser")


class FileParser:
    """Parse documents and split into semantically-coherent chunks.

    Uses LangChain's MarkdownHeaderTextSplitter for structure-aware splitting,
    plus SemanticChunker for embedding-based within-section splitting.
    Falls back to RecursiveCharacterTextSplitter if semantic chunking unavailable.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".markdown"}

    def __init__(
        self,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        use_semantic: bool = True,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_semantic = use_semantic

    def parse(self, file_path: str) -> str:
        """Extract full text from a file.

        Supports: PDF (via PyMuPDF), Markdown, Plain text.
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                f"Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        if ext == ".pdf":
            return self._parse_pdf(file_path)
        else:
            return self._parse_text(file_path)

    def parse_and_chunk(self, file_path: str) -> List[str]:
        """Parse file → full text → smart chunks."""
        text = self.parse(file_path)
        chunks = self.split_into_chunks(text)
        logger.info(
            f"Parsed {file_path}: {len(text)} chars → {len(chunks)} chunks"
        )
        return chunks

    def split_into_chunks(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        """Smart 3-tier chunking: Markdown → Semantic → Size Guard.

        Tier 1: Split by markdown headings (preserves section context)
        Tier 2: Semantic chunking within sections (embedding similarity)
        Tier 3: Safety split for oversized chunks (recursive char split)

        Falls back to recursive character splitting if LangChain unavailable.
        """
        if not text or not text.strip():
            return []

        text = text.strip()
        size = chunk_size or self.chunk_size
        overlap = chunk_overlap or self.chunk_overlap

        try:
            return self._smart_chunk(text, size, overlap)
        except Exception as e:
            logger.warning(f"Smart chunking failed, falling back to basic: {e}")
            return self._basic_chunk(text, size, overlap)

    def _smart_chunk(self, text: str, size: int, overlap: int) -> List[str]:
        """3-tier smart chunking with LangChain."""

        # ── Tier 1: Markdown structure splitting ──
        sections = self._split_by_markdown(text)
        logger.info(f"Tier 1 (Markdown): {len(sections)} sections")

        # ── Tier 2: Semantic splitting within sections ──
        semantic_chunks = []
        if self.use_semantic:
            semantic_chunks = self._semantic_split(sections, size)
            logger.info(f"Tier 2 (Semantic): {len(semantic_chunks)} chunks")
        else:
            semantic_chunks = sections

        # ── Tier 3: Safety guard — enforce max size ──
        final_chunks = self._size_guard(semantic_chunks, size, overlap)
        logger.info(f"Tier 3 (Size Guard): {len(final_chunks)} final chunks")

        return final_chunks

    def _split_by_markdown(self, text: str) -> List[str]:
        """Tier 1: Split by markdown headings, keeping context."""
        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter

            headers_to_split_on = [
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
            ]

            splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=headers_to_split_on,
                strip_headers=False,  # Keep headers for LLM context
            )

            docs = splitter.split_text(text)

            # Extract text content, prepend header metadata for context
            sections = []
            for doc in docs:
                content = doc.page_content.strip()
                if content:
                    # Prepend header path for context
                    header_prefix = ""
                    for key in ["h1", "h2", "h3"]:
                        if key in doc.metadata:
                            header_prefix += f"[{doc.metadata[key]}] "
                    if header_prefix:
                        content = f"{header_prefix.strip()}\n{content}"
                    sections.append(content)

            return sections if sections else [text]

        except ImportError:
            logger.warning("langchain_text_splitters not available, splitting by heading regex")
            return self._regex_markdown_split(text)

    def _regex_markdown_split(self, text: str) -> List[str]:
        """Fallback: split by markdown headings with regex."""
        import re

        # Split on lines starting with # (any level)
        sections = re.split(r'\n(?=#{1,3}\s)', text)
        return [s.strip() for s in sections if s.strip()]

    def _semantic_split(self, sections: List[str], max_size: int) -> List[str]:
        """Tier 2: Semantic chunking within sections using embedding similarity."""
        try:
            from langchain_experimental.text_splitter import SemanticChunker
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

            chunker = SemanticChunker(
                embeddings=embeddings,
                breakpoint_threshold_type="percentile",
                breakpoint_threshold_amount=75,  # Split at top 25% dissimilarity
            )

            all_chunks = []
            for section in sections:
                # Only semantic-split if section is large enough
                if len(section) > max_size:
                    try:
                        sub_chunks = chunker.split_text(section)
                        all_chunks.extend(sub_chunks)
                    except Exception as e:
                        logger.debug(f"Semantic split failed for section, keeping as-is: {e}")
                        all_chunks.append(section)
                else:
                    all_chunks.append(section)

            return all_chunks

        except ImportError:
            logger.warning("SemanticChunker not available, skipping semantic splitting")
            return sections
        except Exception as e:
            logger.warning(f"Semantic chunking error: {e}")
            return sections

    def _size_guard(self, chunks: List[str], size: int, overlap: int) -> List[str]:
        """Tier 3: Safety split oversized chunks with RecursiveCharacterTextSplitter."""
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                separators=["\n\n", "\n", ". ", ", ", " "],
                length_function=len,
            )

            final = []
            for chunk in chunks:
                if len(chunk) > size:
                    sub_chunks = splitter.split_text(chunk)
                    final.extend(sub_chunks)
                else:
                    if chunk.strip():
                        final.append(chunk.strip())
            return final

        except ImportError:
            # Fallback: basic character split
            final = []
            for chunk in chunks:
                if len(chunk) > size:
                    final.extend(self._basic_chunk(chunk, size, overlap))
                elif chunk.strip():
                    final.append(chunk.strip())
            return final

    def _basic_chunk(self, text: str, size: int, overlap: int) -> List[str]:
        """Baseline character-level chunking (original method)."""
        if len(text) <= size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap
        return chunks

    def _parse_pdf(self, file_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            pages = []
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pages.append(page.get_text())
            doc.close()

            text = "\n\n".join(pages)
            logger.info(f"PDF parsed: {len(doc)} pages, {len(text)} chars")
            return text

        except ImportError:
            raise ImportError(
                "PyMuPDF (fitz) is required for PDF parsing. "
                "Install: pip install PyMuPDF"
            )

    def _parse_text(self, file_path: str) -> str:
        """Read plain text or markdown file."""
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    text = f.read()
                logger.info(f"Text file parsed ({enc}): {len(text)} chars")
                return text
            except UnicodeDecodeError:
                continue

        raise ValueError(f"Could not decode file: {file_path}")

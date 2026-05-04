"""
Parquet Profile Reader — DuckDB-based memory-efficient reader for profile.parquet.

Reads 20M+ persona records without loading into RAM using DuckDB's smart scanning.
Supports domain-filtered and random sampling for profile generation pipeline.

Schema of profile.parquet:
    json: STRUCT(
        persona: VARCHAR,
        "general domain (top 1 percent)": VARCHAR,
        "specific domain (top 1 percent)": VARCHAR,
        "general domain (top 0.1 percent)": VARCHAR,
        "specific domain (top 0.1 percent)": VARCHAR,
    )
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional

import duckdb

# Chỉ cho phép chữ, số, space, dấu gạch, underscore, ampersand — đủ cho domain name
# (vd "Computer Science", "Healthcare & Biotech"). Mọi ký tự khác bị strip.
_DOMAIN_SAFE_RE = re.compile(r"[^A-Za-z0-9 \-_&]")


def _sanitize_domain(raw: str) -> str:
    """Strip về allowlist chars để inject an toàn vào DuckDB ILIKE."""
    if not raw:
        return ""
    cleaned = _DOMAIN_SAFE_RE.sub("", raw.strip().strip('"'))
    return cleaned.strip()


def _seed_to_float(seed: int) -> float:
    """DuckDB `setseed()` yêu cầu float trong [-1, 1]. Ánh xạ int seed bất kỳ."""
    # Dùng modulo để giữ deterministic, tránh precision issue cho int lớn
    return ((int(seed) % 20001) - 10000) / 10000.0

logger = logging.getLogger("ecosim.parquet_reader")


class ParquetProfileReader:
    """Memory-efficient reader for large profile.parquet using DuckDB.

    Features:
    - Zero-copy scanning: DuckDB reads parquet directly, no pandas/RAM overhead
    - Domain-filtered sampling: USING SAMPLE for true random selection
    - Keyword search on persona text
    - Thread-safe (each instance has its own connection)

    Usage:
        reader = ParquetProfileReader("data/dataGenerator/profile.parquet")
        profiles = reader.sample_by_domains(["Computer Science", "Economics"], n=10)
        reader.close()
    """

    def __init__(self, parquet_path: str):
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

        self.parquet_path = os.path.abspath(parquet_path)
        self.conn = duckdb.connect()  # In-memory connection
        self._row_count: Optional[int] = None

        logger.info(f"ParquetProfileReader initialized: {self.parquet_path}")

    def get_row_count(self) -> int:
        """Get total row count in parquet (cached after first call)."""
        if self._row_count is None:
            result = self.conn.execute(
                f"SELECT count(*) FROM '{self.parquet_path}'"
            ).fetchone()
            self._row_count = result[0] if result else 0
            logger.info(f"Parquet row count: {self._row_count:,}")
        return self._row_count

    def get_available_domains(self, top_n: int = 30) -> List[Dict[str, int]]:
        """Get top domains with counts for UI/filtering."""
        rows = self.conn.execute(f"""
            SELECT
                CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as domain,
                count(*) as cnt
            FROM '{self.parquet_path}'
            WHERE CAST(json->>'general domain (top 1 percent)' AS VARCHAR) IS NOT NULL
              AND CAST(json->>'general domain (top 1 percent)' AS VARCHAR) != '"None"'
            GROUP BY 1
            ORDER BY cnt DESC
            LIMIT {top_n}
        """).fetchall()

        return [
            {"domain": self._clean_quoted(str(row[0])), "count": row[1]}
            for row in rows
        ]

    def sample_by_domains(
        self,
        domains: List[str],
        n: int,
        include_specific: bool = True,
        seed: Optional[int] = None,
    ) -> List[Dict]:
        """Sample n profiles matching given domains.

        Searches both general and specific domain fields.
        Uses DuckDB TABLESAMPLE for efficient random selection from filtered results.

        Args:
            domains: List of domain strings to match (case-insensitive)
            n: Number of profiles to sample
            include_specific: Also search specific domain field
            seed: Reproducibility seed cho TABLESAMPLE `REPEATABLE`

        Returns:
            List of dicts with keys: persona, general_domain, specific_domain
        """
        if not domains:
            return self.sample_random(n, seed=seed)

        # Build domain filter — input được sanitize qua allowlist regex
        conditions = []
        for domain in domains:
            clean = _sanitize_domain(domain)
            if not clean or clean.lower() == "none":
                continue
            conditions.append(
                f"CAST(json->>'general domain (top 1 percent)' AS VARCHAR) ILIKE '%{clean}%'"
            )
            if include_specific:
                conditions.append(
                    f"CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) ILIKE '%{clean}%'"
                )

        if not conditions:
            return self.sample_random(n, seed=seed)

        where_clause = " OR ".join(conditions)
        repeat_clause = f" REPEATABLE ({int(seed)})" if seed is not None else ""

        # 2-stage sampling: TABLESAMPLE first to reduce scan, then filter
        # Stage 1: Try with 10% sample (~2M rows) for speed
        for sample_pct in [10, 50, 100]:
            if sample_pct < 100:
                # TABLESAMPLE first to reduce 20M → ~2M/10M rows, then filter
                query = f"""
                    SELECT
                        CAST(json->>'persona' AS VARCHAR) as persona,
                        CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as general_domain,
                        CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) as specific_domain
                    FROM (
                        SELECT * FROM '{self.parquet_path}'
                        USING SAMPLE {sample_pct} PERCENT (bernoulli){repeat_clause}
                    ) t
                    WHERE ({where_clause})
                      AND CAST(json->>'persona' AS VARCHAR) IS NOT NULL
                      AND length(CAST(json->>'persona' AS VARCHAR)) > 50
                    LIMIT {n}
                """
            else:
                # Full scan as last resort — `random()` được seeded bằng setseed() bên trên
                query = f"""
                    SELECT
                        CAST(json->>'persona' AS VARCHAR) as persona,
                        CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as general_domain,
                        CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) as specific_domain
                    FROM '{self.parquet_path}'
                    WHERE ({where_clause})
                      AND CAST(json->>'persona' AS VARCHAR) IS NOT NULL
                      AND length(CAST(json->>'persona' AS VARCHAR)) > 50
                    ORDER BY random()
                    LIMIT {n}
                """

            try:
                if seed is not None:
                    # setseed cho `random()` trong DuckDB — phải ở khoảng [-1, 1]
                    self.conn.execute(f"SELECT setseed({_seed_to_float(seed)})")
                rows = self.conn.execute(query).fetchall()
                results = [self._row_to_dict(row) for row in rows]
                if len(results) >= n or sample_pct >= 100:
                    logger.info(
                        f"Sampled {len(results)} domain-filtered profiles "
                        f"(requested {n}, domains={domains}, sample={sample_pct}%, seed={seed})"
                    )
                    return results
                logger.info(f"Only got {len(results)}/{n} from {sample_pct}% sample, retrying...")
            except Exception as e:
                logger.warning(f"Domain sampling ({sample_pct}%) failed: {e}")
                if sample_pct >= 100:
                    logger.warning("Falling back to random sampling")
                    return self.sample_random(n, seed=seed)

    def sample_random(self, n: int, seed: Optional[int] = None) -> List[Dict]:
        """Random sample from entire dataset.

        Uses DuckDB USING SAMPLE for efficient reservoir sampling.
        Passing `seed` ⇒ `REPEATABLE(...)` để query lặp lại được.
        """
        repeat_clause = f" REPEATABLE ({int(seed)})" if seed is not None else ""
        query = f"""
            SELECT
                CAST(json->>'persona' AS VARCHAR) as persona,
                CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as general_domain,
                CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) as specific_domain
            FROM '{self.parquet_path}'
            WHERE CAST(json->>'persona' AS VARCHAR) IS NOT NULL
              AND length(CAST(json->>'persona' AS VARCHAR)) > 50
            USING SAMPLE reservoir({n} ROWS){repeat_clause}
        """
        rows = self.conn.execute(query).fetchall()
        results = [self._row_to_dict(row) for row in rows]
        logger.info(f"Sampled {len(results)} random profiles (requested {n}, seed={seed})")
        return results

    def sample_by_keywords(self, keywords: List[str], n: int) -> List[Dict]:
        """Full-text keyword search on persona field.

        Useful for finding profiles related to specific campaign topics.
        """
        if not keywords:
            return self.sample_random(n)

        conditions = []
        for kw in keywords:
            kw_clean = kw.strip().replace("'", "''")
            if kw_clean:
                conditions.append(
                    f"CAST(json->>'persona' AS VARCHAR) ILIKE '%{kw_clean}%'"
                )

        if not conditions:
            return self.sample_random(n)

        where_clause = " OR ".join(conditions)

        # 2-stage: TABLESAMPLE then filter for speed on 20M rows
        for sample_pct in [10, 50, 100]:
            if sample_pct < 100:
                query = f"""
                    SELECT
                        CAST(json->>'persona' AS VARCHAR) as persona,
                        CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as general_domain,
                        CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) as specific_domain
                    FROM (SELECT * FROM '{self.parquet_path}' USING SAMPLE {sample_pct} PERCENT (bernoulli)) t
                    WHERE ({where_clause})
                      AND CAST(json->>'persona' AS VARCHAR) IS NOT NULL
                      AND length(CAST(json->>'persona' AS VARCHAR)) > 50
                    LIMIT {n}
                """
            else:
                query = f"""
                    SELECT
                        CAST(json->>'persona' AS VARCHAR) as persona,
                        CAST(json->>'general domain (top 1 percent)' AS VARCHAR) as general_domain,
                        CAST(json->>'specific domain (top 1 percent)' AS VARCHAR) as specific_domain
                    FROM '{self.parquet_path}'
                    WHERE ({where_clause})
                      AND CAST(json->>'persona' AS VARCHAR) IS NOT NULL
                      AND length(CAST(json->>'persona' AS VARCHAR)) > 50
                    ORDER BY random()
                    LIMIT {n}
                """

            try:
                rows = self.conn.execute(query).fetchall()
                results = [self._row_to_dict(row) for row in rows]
                if len(results) >= n or sample_pct >= 100:
                    logger.info(
                        f"Sampled {len(results)} keyword-filtered profiles "
                        f"(requested {n}, keywords={keywords}, sample={sample_pct}%)"
                    )
                    return results
            except Exception as e:
                logger.warning(f"Keyword sampling ({sample_pct}%) failed: {e}")
                if sample_pct >= 100:
                    return self.sample_random(n)

        return self.sample_random(n)

    def close(self):
        """Close DuckDB connection."""
        try:
            self.conn.close()
            logger.info("ParquetProfileReader closed")
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Private helpers ──

    def _row_to_dict(self, row) -> Dict:
        """Convert a DuckDB row tuple to a clean dict."""
        persona_raw = row[0] or ""
        general_domain = row[1] or ""
        specific_domain = row[2] or ""

        return {
            "persona": self._clean_quoted(persona_raw),
            "general_domain": self._clean_quoted(general_domain),
            "specific_domain": self._clean_quoted(specific_domain),
        }

    @staticmethod
    def _clean_quoted(val: str) -> str:
        """Remove surrounding escaped quotes from parquet JSON string values.

        Parquet stores JSON strings with extra quotes like:
            '"Computer Science"'  →  'Computer Science'
            '\"A software developer...\"'  →  'A software developer...'
        """
        if not val:
            return ""
        s = val.strip()
        # Remove surrounding double quotes
        if s.startswith('"') and s.endswith('"') and len(s) > 2:
            s = s[1:-1]
        # Remove escaped quotes
        s = s.replace('\\"', '"').replace("\\'", "'")
        return s.strip()

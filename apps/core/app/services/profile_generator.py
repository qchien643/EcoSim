"""
Profile Generator — OASIS Reddit-Compatible Agent Pipeline.

3-Phase Pipeline (simplified):
  Phase 1 (SAMPLE): DuckDB scans 20M-row profile.parquet → sample personas by domain
  Phase 2 (LLM COMPLETE): Batch LLM enriches persona with name + campaign context
  Phase 3 (ASSEMBLE): Build 8-field AgentProfile objects for OASIS Reddit

Output fields (matches OASIS generate_reddit_agent_graph):
  username, realname, bio, persona, age, gender, mbti, country
"""

import json
import logging
import os
import random
import unicodedata
from typing import Any, Callable, Dict, List, Optional

from ecosim_common.atomic_io import atomic_write_json

from ..config import Config
from ..models.simulation import AgentProfile
from ..services.parquet_reader import ParquetProfileReader
from ..services.name_pool import NamePool
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.profile_generator")


MBTI_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
]

# ── LLM Prompts ──────────────────────────────────────────────────

BATCH_COMPLETION_SYSTEM = """\
You are an expert at creating realistic social media user personas for campaign simulations.
You will receive base personas from a real dataset, each paired with a Vietnamese name.
Your job is to:
1. Enrich each persona with campaign awareness
2. Naturally embed the person's Vietnamese name into the persona text
3. Generate consistent demographics (age, gender, mbti)
4. Write a catchy social media bio
All output must be valid JSON. All string values must NOT contain literal newlines — use spaces instead."""

BATCH_COMPLETION_PROMPT = """\
CAMPAIGN CONTEXT:
{campaign_context}

Below are {count} base personas sampled from a real-world profile dataset.
Each persona is paired with a Vietnamese name that MUST be embedded naturally into the enriched persona.
The country for ALL personas is Vietnam.

PERSONAS:
{personas_block}

For EACH persona, generate:
1. "enriched_persona": Rewrite the persona in 150-200 words. MUST start with or naturally include the person's name. Add 1-2 sentences about their view on the campaign. Keep the original personality/interests intact.
2. "bio": Social media bio, max 160 chars, catchy and personal
3. "age": 18-65, realistic for the persona's expertise level
4. "gender": "male" or "female"
5. "mbti": One of the 16 MBTI types, fitting the persona's personality

Return a JSON object:
{{
  "profiles": [
    {{
      "id": 0,
      "enriched_persona": "<persona text with name embedded, 150-200 words>",
      "bio": "<max 160 chars>",
      "age": <18-65>,
      "gender": "<male|female>",
      "mbti": "<e.g. INTJ>"
    }}
  ]
}}"""


class ProfileGenerator:
    """Generate OASIS Reddit-compatible agent profiles.

    Pipeline:
    1. SAMPLE: DuckDB reads profile.parquet → domain-filtered personas
    2. LLM COMPLETE: NamePool picks names → LLM enriches persona (embed name + campaign) + demographics
    3. ASSEMBLE: Build AgentProfile(8 fields) objects
    """

    def __init__(self, llm_client: LLMClient = None, parquet_path: str = None):
        self.llm = llm_client or LLMClient()
        self.name_pool = NamePool()

        # Resolve parquet path
        pq_path = parquet_path or getattr(Config, "PARQUET_PROFILE_PATH", None)
        if not pq_path:
            pq_path = os.path.join(Config.BASE_DIR, "data", "dataGenerator", "profile.parquet")

        self.reader = ParquetProfileReader(pq_path)
        logger.info(f"ProfileGenerator initialized (parquet: {pq_path})")

    def generate(
        self,
        campaign_id: str,
        num_agents: int = 10,
        campaign_context: str = "",
        batch_size: int = 5,
        parallel_count: int = 5,  # Backward compat alias (ignored)
        progress_callback: Optional[Callable] = None,
    ) -> List[AgentProfile]:
        """Generate agent profiles — 3-phase pipeline.

        Args:
            campaign_id: Campaign identifier
            num_agents: Number of agents to generate
            campaign_context: Campaign description for enrichment
            batch_size: Personas per LLM batch call (default 5)
            progress_callback: Optional callable(current, total, message)

        Returns:
            List of AgentProfile objects (8 fields each)
        """
        self.name_pool.reset()

        # Build campaign context
        campaign_ctx = self._build_campaign_context(campaign_id, campaign_context)

        # Extract domains for targeted sampling
        domains = self._extract_domains_from_context(campaign_ctx)
        logger.info(f"Extracted domains for sampling: {domains}")

        # ── Phase 1: SAMPLE from Parquet ──
        if progress_callback:
            progress_callback(0, num_agents, "Sampling personas from dataset...")

        raw_personas = self._sample_personas(num_agents, domains)
        logger.info(f"Phase 1 complete: sampled {len(raw_personas)} personas")

        # ── Phase 2: Pick names + LLM COMPLETE ──
        if progress_callback:
            progress_callback(len(raw_personas) // 3, num_agents, "LLM completing profiles...")

        # Pick names BEFORE LLM call so we can embed them into persona
        names = [self.name_pool.pick() for _ in range(len(raw_personas))]
        completed = self._llm_complete_batch(raw_personas, names, campaign_ctx, batch_size)
        logger.info(f"Phase 2 complete: LLM completed {len(completed)} profiles")

        # ── Phase 3: ASSEMBLE AgentProfile objects ──
        if progress_callback:
            progress_callback(num_agents * 2 // 3, num_agents, "Assembling agent profiles...")

        profiles = self._assemble_profiles(completed, raw_personas, names)
        logger.info(f"Phase 3 complete: assembled {len(profiles)} agent profiles")

        if progress_callback:
            progress_callback(num_agents, num_agents, "Done!")

        return profiles

    # ────────────────────────────────────────────────────────────────
    # Phase 1: SAMPLE
    # ────────────────────────────────────────────────────────────────

    def _sample_personas(self, n: int, domains: List[str]) -> List[Dict]:
        """Sample personas from parquet with domain relevance.

        Strategy: 60% domain-relevant, 40% random diversity.
        Falls back to 100% random if domain sampling fails.
        """
        if domains:
            n_domain = max(1, int(n * 0.6))
            n_random = n - n_domain

            domain_samples = self.reader.sample_by_domains(domains, n_domain)
            random_samples = self.reader.sample_random(n_random) if n_random > 0 else []

            combined = domain_samples + random_samples

            if len(combined) < n:
                shortfall = n - len(combined)
                combined += self.reader.sample_random(shortfall)

            logger.info(
                f"Sampling: {len(domain_samples)} domain-relevant + "
                f"{len(random_samples)} random = {len(combined)} total"
            )
            return combined[:n]
        else:
            return self.reader.sample_random(n)

    def _extract_domains_from_context(self, campaign_context: str) -> List[str]:
        """Extract relevant domain keywords from campaign context."""
        domain_keywords = {
            "technology": ["tech", "software", "app", "digital", "AI", "machine learning", "computer"],
            "economics": ["economy", "economic", "market", "financial", "finance", "trade"],
            "business": ["business", "startup", "company", "enterprise", "commerce", "e-commerce"],
            "marketing": ["marketing", "advertising", "brand", "promotion", "campaign"],
            "health": ["health", "medical", "healthcare", "wellness", "pharmaceutical"],
            "education": ["education", "university", "learning", "student", "academic"],
            "food": ["food", "restaurant", "cuisine", "nutrition", "culinary"],
            "environment": ["environment", "climate", "green", "sustainability", "eco"],
            "politics": ["politics", "policy", "government", "regulation", "law"],
            "media": ["media", "news", "journalism", "social media", "content"],
            "science": ["science", "research", "biology", "chemistry", "physics"],
            "engineering": ["engineering", "mechanical", "electrical", "civil"],
            "logistics": ["logistics", "supply chain", "delivery", "shipping", "transport"],
            "retail": ["retail", "shopping", "consumer", "store", "shop"],
        }

        context_lower = campaign_context.lower()
        matched_domains = []

        for domain, keywords in domain_keywords.items():
            for kw in keywords:
                if kw.lower() in context_lower:
                    matched_domains.append(domain)
                    break

        return matched_domains[:5]

    # ────────────────────────────────────────────────────────────────
    # Phase 2: LLM COMPLETE
    # ────────────────────────────────────────────────────────────────

    def _llm_complete_batch(
        self,
        personas: List[Dict],
        names: List[str],
        campaign_context: str,
        batch_size: int = 5,
    ) -> List[Dict]:
        """Batch LLM completion — enrich personas with names + campaign.

        Each call generates: enriched_persona (with name embedded),
        bio, age, gender, mbti.
        """
        results = []
        total_batches = (len(personas) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(personas))
            batch = personas[start:end]
            batch_names = names[start:end]

            try:
                batch_result = self._complete_one_batch(batch, batch_names, campaign_context, start)
                results.extend(batch_result)
                logger.info(
                    f"Batch {batch_idx + 1}/{total_batches}: "
                    f"completed {len(batch_result)} profiles"
                )
            except Exception as e:
                logger.warning(
                    f"Batch {batch_idx + 1}/{total_batches} failed: {e}. "
                    f"Using fallback for {len(batch)} profiles."
                )
                for i, persona in enumerate(batch):
                    results.append(self._fallback_completion(persona, batch_names[i], start + i))

        return results

    def _complete_one_batch(
        self,
        batch: List[Dict],
        batch_names: List[str],
        campaign_context: str,
        start_id: int,
    ) -> List[Dict]:
        """Send one batch of personas + names to LLM for completion."""
        personas_lines = []
        for i, p in enumerate(batch):
            persona_text = p.get("persona", "")[:500]
            domain = p.get("general_domain", "unknown")
            specific = p.get("specific_domain", "")
            domain_str = f"{domain}" + (f" / {specific}" if specific and specific.lower() != "none" else "")
            name = batch_names[i]
            personas_lines.append(
                f"[{i}] Name: \"{name}\"\n"
                f"    Domain: \"{domain_str}\"\n"
                f"    Persona: \"{persona_text}\""
            )

        personas_block = "\n\n".join(personas_lines)

        prompt = BATCH_COMPLETION_PROMPT.format(
            campaign_context=campaign_context,
            count=len(batch),
            personas_block=personas_block,
        )

        response = self.llm.chat_json(
            messages=[
                {"role": "system", "content": BATCH_COMPLETION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
        )

        profiles = response.get("profiles", [])
        if not profiles and isinstance(response, list):
            profiles = response

        validated = []
        for i, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                continue
            profile["_batch_index"] = i
            profile["_global_index"] = start_id + i
            validated.append(profile)

        return validated

    def _fallback_completion(self, persona_data: Dict, name: str, index: int) -> Dict:
        """Generate a basic profile without LLM (fallback on error)."""
        persona_text = persona_data.get("persona", "")
        domain = persona_data.get("general_domain", "General")

        # Embed name into persona manually
        enriched = f"{name} is a Vietnamese individual with interests in {domain}. {persona_text}"

        return {
            "_batch_index": 0,
            "_global_index": index,
            "enriched_persona": enriched[:800],
            "bio": f"{domain} enthusiast sharing insights and experiences.",
            "age": random.randint(22, 50),
            "gender": random.choice(["male", "female"]),
            "mbti": random.choice(MBTI_TYPES),
        }

    # ────────────────────────────────────────────────────────────────
    # Phase 3: ASSEMBLE
    # ────────────────────────────────────────────────────────────────

    def _assemble_profiles(
        self,
        completed: List[Dict],
        raw_personas: List[Dict],
        names: List[str],
    ) -> List[AgentProfile]:
        """Assemble final 8-field AgentProfile objects.

        Combines:
        - Vietnamese name from NamePool
        - LLM-enriched persona (with name + campaign embedded)
        - LLM-generated demographics (age, gender, mbti)
        - Country = "Vietnam" (hardcoded)
        """
        profiles = []

        for idx, data in enumerate(completed):
            name = names[idx] if idx < len(names) else self.name_pool.pick()
            username = self._make_username(name)

            # Get persona — prefer enriched, fall back to raw
            enriched_persona = data.get("enriched_persona", "")
            if not enriched_persona and idx < len(raw_personas):
                raw_text = raw_personas[idx].get("persona", "")
                enriched_persona = f"{name} is a Vietnamese individual. {raw_text}"

            # Ensure name is actually in persona
            if name not in enriched_persona:
                enriched_persona = f"{name} — {enriched_persona}"

            bio = data.get("bio", "")[:160] or f"{name} on social media"
            age = self._safe_int(data.get("age"), 18, 65, default=random.randint(22, 45))
            gender = self._normalize_gender(data.get("gender"))
            mbti = data.get("mbti", random.choice(MBTI_TYPES))
            if mbti not in MBTI_TYPES:
                mbti = random.choice(MBTI_TYPES)

            profile = AgentProfile(
                agent_id=idx,
                username=username,
                realname=name,
                bio=bio,
                persona=enriched_persona,
                age=age,
                gender=gender,
                mbti=mbti,
                country="Vietnam",
            )
            profiles.append(profile)

        return profiles

    # ────────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────────

    def _build_campaign_context(self, campaign_id: str, campaign_context: str = "") -> str:
        """Build campaign context from spec file."""
        if not campaign_context and campaign_id:
            spec_path = os.path.join(Config.UPLOAD_DIR, f"{campaign_id}_spec.json")
            if os.path.exists(spec_path):
                with open(spec_path, "r", encoding="utf-8") as f:
                    spec = json.load(f)
                campaign_context = (
                    f"Campaign: {spec.get('name', '')}\n"
                    f"Type: {spec.get('campaign_type', '')}\n"
                    f"Market: {spec.get('market', '')}\n"
                    f"Summary: {spec.get('summary', '')}"
                )
        return campaign_context or "General economic simulation"

    def _make_username(self, name: str) -> str:
        """Generate ASCII-safe username from Vietnamese name."""
        nfkd = unicodedata.normalize("NFKD", name)
        ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
        clean = ascii_name.lower().replace(" ", "_")
        clean = "".join(c for c in clean if c.isalnum() or c == "_")
        if not clean:
            clean = "user"
        return f"{clean}_{random.randint(100, 999)}"

    @staticmethod
    def _safe_int(val, min_v: int, max_v: int, default=None):
        """Safely convert to int within range."""
        if val is None:
            return default
        try:
            v = int(val)
            return max(min_v, min(max_v, v))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _normalize_gender(val) -> str:
        """Normalize gender to male/female."""
        if not val:
            return random.choice(["male", "female"])
        v = str(val).lower().strip()
        if v in ("male", "nam"):
            return "male"
        if v in ("female", "nữ"):
            return "female"
        return random.choice(["male", "female"])

    # ────────────────────────────────────────────────────────────────
    # Export — OASIS Reddit format
    # ────────────────────────────────────────────────────────────────

    def save_json(self, profiles: List[AgentProfile], output_path: str) -> str:
        """Save profiles as OASIS Reddit-compatible JSON.

        Output format matches OASIS `user_data_36.json`:
        [
          {
            "realname": "Nguyễn Văn An",
            "username": "nguyen_van_an_123",
            "bio": "...",
            "persona": "Nguyễn Văn An is a ... Regarding Shopee Black Friday...",
            "age": 35,
            "gender": "male",
            "mbti": "INTJ",
            "country": "Vietnam"
          }
        ]
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        data = []
        for p in profiles:
            data.append({
                "realname": p.realname,
                "username": p.username,
                "bio": p.bio,
                "persona": p.persona.replace("\n", " ").replace("\r", " "),
                "age": p.age,
                "gender": p.gender,
                "mbti": p.mbti,
                "country": p.country,
            })
        atomic_write_json(output_path, data)
        logger.info(f"Saved {len(profiles)} OASIS-compatible profiles to {output_path}")
        return output_path

    def close(self):
        """Clean up resources."""
        self.reader.close()

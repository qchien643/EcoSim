"""
Simulation Config Generator — MiroFish-style 3-step LLM pipeline.
Ported from socialSim/sim_config_generator.py, adapted for EcoSim economic context.

Pipeline:
  campaign_spec + KG_entities
    → LLM Step 1: TimeConfig (duration, period multipliers, peak hours)
    → LLM Step 2: EventConfig (initial posts, hot topics, narrative)
    → LLM Step 3: Per-agent behavior configs (stance, posting, delay, hours)
"""

import json
import logging
import math
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional

from ..models.simulation import (
    AgentProfile,
    EventConfig,
    InitialPost,
    RecConfig,
    TimeConfig,
    TimePeriod,
)
from ..services.graph_query import GraphQuery
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.sim_config_gen")


class SimConfigGenerator:
    """
    Generate MiroFish-style simulation config from campaign + KG.

    Usage:
        gen = SimConfigGenerator()
        result = gen.generate(
            campaign_id="shopee_bf",
            campaign_context="Shopee Black Friday 2026...",
            entities=[{name, type, description}],
            num_agents=10,
        )
        # result = {time_config, event_config, rec_config, agent_behavior_configs, reasoning}
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def generate(
        self,
        campaign_context: str,
        entities: List[Dict[str, Any]],
        num_agents: int = 10,
        custom_rounds: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Generate complete sim config — 3 LLM steps.

        Returns dict with: time_config, event_config, rec_config,
                          agent_behavior_configs, reasoning, estimated_duration
        """
        total_steps = 3
        reasoning_parts = []

        def report(step, msg):
            if progress_callback:
                progress_callback(step, total_steps, msg)
            logger.info(f"[{step}/{total_steps}] {msg}")

        context = self._build_context(campaign_context, entities)

        # ── Step 1: Time Config ──
        report(1, "Generating time config...")
        time_config = self._generate_time_config(context, num_agents)
        reasoning_parts.append(
            f"Time: {time_config.total_simulation_hours}h, "
            f"{time_config.total_rounds} rounds"
        )

        # Custom mode: override rounds
        if custom_rounds and custom_rounds < time_config.total_rounds:
            logger.info(f"Custom mode: {time_config.total_rounds} → {custom_rounds} rounds")
            time_config.total_rounds = custom_rounds

        # ── Step 2: Event Config (behavior is now rule-based in ProfileGenerator) ──
        report(2, "Generating event config...")
        event_config = self._generate_event_config(context, entities)

        reasoning_parts.append(
            f"Events: {len(event_config.initial_posts)} initial posts, "
            f"{len(event_config.hot_topics)} hot topics"
        )

        # Assign initial post poster_agent_id using entities
        event_config = self._assign_poster_agents(event_config, entities)

        # Auto-generate rec_config
        rec_config = RecConfig(
            rec_type="reddit" if num_agents < 15 else "twitter",
            timeliness_weight=0.4,
            popularity_weight=0.3,
            relevance_weight=0.3,
            virality_threshold=max(5, num_agents // 5),
            echo_chamber_intensity=0.5,
        )

        # Estimate wall-clock duration
        estimated_minutes = self._estimate_duration(num_agents, time_config.total_rounds)

        return {
            "time_config": time_config,
            "event_config": event_config,
            "rec_config": rec_config,
            "reasoning": " | ".join(reasoning_parts),
            "estimated_duration_minutes": estimated_minutes,
        }

    def _build_context(
        self, campaign_context: str, entities: List[Dict[str, Any]]
    ) -> str:
        """Build LLM context from campaign + entities."""
        parts = [f"## Campaign Context\n{campaign_context}"]

        if entities:
            entity_lines = []
            for e in entities[:40]:
                name = e.get("name") or "?"
                etype = e.get("type") or e.get("entity_type") or "Entity"
                desc = (e.get("description") or e.get("summary") or "")[:200]
                entity_lines.append(f"- [{etype}] {name}: {desc}")
            parts.append(f"\n## Entities ({len(entities)})\n" + "\n".join(entity_lines))

        return "\n".join(parts)

    def _estimate_duration(self, num_agents: int, total_rounds: int) -> int:
        """Estimate wall-clock duration in minutes."""
        seconds_per_agent_round = 12  # ~12s per agent per round (LLM call)
        total_seconds = num_agents * total_rounds * seconds_per_agent_round
        return max(1, total_seconds // 60)

    # ──────────────────────────────────────────────
    # Step 1: Time Config
    # ──────────────────────────────────────────────

    def _generate_time_config(self, context: str, num_agents: int) -> TimeConfig:
        """LLM generates time parameters based on campaign scenario."""
        max_active = max(1, int(num_agents * 0.9))

        prompt = f"""Based on this economic simulation scenario, generate time configuration.

{context[:6000]}

Return JSON:
{{
    "total_simulation_hours": <24-168, shorter for flash sales, longer for sustained campaigns>,
    "minutes_per_round": <30-120, default 60>,
    "agents_per_round_min": <1-{max_active}>,
    "agents_per_round_max": <1-{max_active}>,
    "peak_hours": [<hours 0-23 when consumers most active>],
    "off_peak_hours": [<hours 0-23 when least active>],
    "period_multipliers": [
        {{"name": "peak_hours", "hours": [<peak>], "multiplier": 1.5, "label": "<readable>"}},
        {{"name": "working_hours", "hours": [<9-18>], "multiplier": 0.7, "label": "<readable>"}},
        {{"name": "morning_hours", "hours": [<6-8>], "multiplier": 0.4, "label": "<readable>"}},
        {{"name": "low_period", "hours": [<0-5>], "multiplier": 0.05, "label": "<readable>"}}
    ],
    "time_reasoning": "<2-3 sentences explaining WHY these time parameters fit the campaign>"
}}"""

        try:
            result = self.llm.chat_json([
                {"role": "system", "content": "You are an economic simulation expert. Return pure JSON."},
                {"role": "user", "content": prompt},
            ])
            return self._parse_time_config(result, num_agents)
        except Exception as e:
            logger.warning(f"Time config LLM failed: {e}, using defaults")
            return self._default_time_config(num_agents)

    def _parse_time_config(self, result: Dict, num_agents: int) -> TimeConfig:
        hours = result.get("total_simulation_hours", 72)
        mpr = result.get("minutes_per_round", 60)
        total_rounds = max(1, (hours * 60) // mpr)

        amin = min(result.get("agents_per_round_min", 2), num_agents)
        amax = min(result.get("agents_per_round_max", num_agents), num_agents)
        if amin >= amax:
            amin = max(1, amax // 2)

        # Parse period_multipliers
        raw_periods = result.get("period_multipliers", [])
        period_multipliers = []
        for p in raw_periods:
            period_multipliers.append(TimePeriod(
                name=p.get("name", "unknown"),
                hours=p.get("hours", []),
                multiplier=max(0.01, min(3.0, p.get("multiplier", 1.0))),
                label=p.get("label", ""),
            ))

        if not period_multipliers:
            peak = result.get("peak_hours", [19, 20, 21, 22])
            period_multipliers = [
                TimePeriod(name="peak_hours", hours=peak, multiplier=1.5,
                           label=", ".join(f"{h}:00" for h in peak)),
                TimePeriod(name="working_hours", hours=list(range(9, 19)), multiplier=0.7, label="9:00-18:00"),
                TimePeriod(name="morning_hours", hours=[6, 7, 8], multiplier=0.4, label="6:00-8:00"),
                TimePeriod(name="low_period", hours=[0, 1, 2, 3, 4, 5], multiplier=0.05, label="0:00-5:00"),
            ]

        return TimeConfig(
            total_simulation_hours=hours,
            minutes_per_round=mpr,
            total_rounds=total_rounds,
            agents_per_round_min=max(1, amin),
            agents_per_round_max=max(2, amax),
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            period_multipliers=period_multipliers,
            time_reasoning=result.get("time_reasoning", ""),
        )

    def _default_time_config(self, num_agents: int) -> TimeConfig:
        return TimeConfig(
            total_simulation_hours=72,
            minutes_per_round=60,
            total_rounds=72,
            agents_per_round_min=max(1, num_agents // 3),
            agents_per_round_max=num_agents,
        )

    # ──────────────────────────────────────────────
    # Step 2: Event Config
    # ──────────────────────────────────────────────

    def _generate_event_config(
        self, context: str, entities: List[Dict[str, Any]]
    ) -> EventConfig:
        """LLM generates initial posts, hot topics, narrative direction."""
        # Build entity type examples
        type_examples = {}
        for e in entities:
            etype = e.get("type") or e.get("entity_type") or "Entity"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.get("name") or "?")

        type_info = "\n".join(
            f"- {t}: {', '.join(names)}" for t, names in type_examples.items()
        )

        prompt = f"""Based on this economic campaign scenario, generate the INITIAL social media posts
that would appear when this event launches, plus hot topic keywords.

{context[:5000]}

Available entity types and examples:
{type_info}

Return JSON:
{{
    "hot_topics": ["keyword1", "keyword2", ...],
    "narrative_direction": "<how public/market opinion will likely evolve>",
    "initial_posts": [
        {{"content": "<post content, 50-200 chars>", "poster_type": "<entity type>", "poster_name": "<entity name>"}},
        ...
    ],
    "event_reasoning": "<2-3 sentences explaining the event dynamics>"
}}

IMPORTANT:
- Generate 3-6 initial posts representing different stakeholder perspectives
- poster_type MUST match one of the available entity types above
- Posts should feel authentic (official announcements, consumer reactions, competitor comments, etc.)"""

        try:
            result = self.llm.chat_json([
                {"role": "system", "content": "You are an economic simulation expert. Return pure JSON."},
                {"role": "user", "content": prompt},
            ])
            posts = [
                InitialPost(
                    content=p.get("content", ""),
                    poster_type=p.get("poster_type", ""),
                    poster_name=p.get("poster_name", ""),
                )
                for p in result.get("initial_posts", [])
            ]
            return EventConfig(
                initial_posts=posts,
                hot_topics=result.get("hot_topics", []),
                narrative_direction=result.get("narrative_direction", ""),
                event_reasoning=result.get("event_reasoning", ""),
            )
        except Exception as e:
            logger.warning(f"Event config LLM failed: {e}, using empty events")
            return EventConfig()

    # ──────────────────────────────────────────────
    # Step 3: Agent Behavior Configs
    # ──────────────────────────────────────────────

    def _generate_agent_behavior_configs(
        self, context: str, entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """LLM assigns stance, sentiment, activity, and behavior params to each entity/agent.

        Batched: splits entities into groups of ≤10 to avoid token overflow.
        With 20 agents, each needing ~150 output tokens, a single call would
        require ~3000 tokens and exceed the default max_tokens → truncated JSON.
        """
        BATCH_SIZE = 10
        all_configs = []

        for batch_start in range(0, len(entities), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(entities))
            batch = entities[batch_start:batch_end]

            batch_configs = self._generate_behavior_batch(
                context, batch, batch_start,
            )
            all_configs.extend(batch_configs)

            if batch_end < len(entities):
                logger.info(
                    f"Behavior batch {batch_start}-{batch_end}: "
                    f"{len(batch_configs)} configs generated"
                )

        return all_configs

    def _generate_behavior_batch(
        self, context: str, batch_entities: List[Dict[str, Any]],
        id_offset: int,
    ) -> List[Dict[str, Any]]:
        """Generate behavior configs for a single batch of entities."""
        entity_list = []
        for local_idx, e in enumerate(batch_entities):
            global_idx = id_offset + local_idx
            etype = e.get("type") or e.get("entity_type") or "Entity"
            name = e.get("name") or "?"
            desc = (e.get("description") or e.get("summary") or "")[:150]
            entity_list.append(f"{global_idx}. [{etype}] {name}: {desc}")

        prompt = f"""For each entity below, assign their stance, behavior parameters, and interaction style for this economic campaign.

{context[:4000]}

Entities:
{chr(10).join(entity_list)}

Return JSON:
{{
    "agents": [
        {{
            "agent_id": <index>,
            "stance": "<supportive|opposing|neutral>",
            "sentiment_bias": <-1.0 to 1.0>,
            "activity_level": <0.0-1.0>,
            "active_hours": [<hours 0-23>],
            "influence_weight": <0.1-3.0>,
            "posting_probability": <0.0-1.0>,
            "comments_per_time": <0.0-20.0>,
            "response_delay_min": <minutes>,
            "response_delay_max": <minutes>,
            "topics": ["topic1", "topic2", "topic3"]
        }},
        ...
    ]
}}

Rules:
- stance: how this entity would respond to the campaign
- sentiment_bias: negative = critical, positive = supportive
- activity_level: 1.0 = very active, 0.1 = observer
- active_hours: when online (consumers: 18-23, officials: 9-17, media: 8-22)
- influence_weight: media/officials > 2.0, consumers ~1.0
- posting_probability: high for influencers (0.8), low for observers (0.1)
- comments_per_time: high for engaged users (5-15), low for lurkers (0.1)
- response_delay_min/max: fast for active users (1-5min), slow for officials (60-240min)
- topics: 3-5 relevant topics this entity cares about"""

        try:
            result = self.llm.chat_json(
                [
                    {"role": "system", "content": "You are an economic behavior analyst. Return pure JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4000,
            )

            configs = []
            for agent_data in result.get("agents", []):
                aid = agent_data.get("agent_id", 0)
                # Map back to the correct entity (could be offset)
                local_idx = aid - id_offset
                entity = batch_entities[local_idx] if 0 <= local_idx < len(batch_entities) else {}
                if not entity and aid < len(batch_entities):
                    entity = batch_entities[aid]

                delay_min = max(1, agent_data.get("response_delay_min", 5))
                delay_max = max(delay_min + 1, agent_data.get("response_delay_max", 30))

                configs.append({
                    "agent_id": aid,
                    "entity_name": entity.get("name", f"agent_{aid}"),
                    "entity_type": entity.get("type", entity.get("entity_type", "Entity")),
                    "stance_label": agent_data.get("stance", "neutral"),
                    "sentiment_bias": max(-1.0, min(1.0, agent_data.get("sentiment_bias", 0.0))),
                    "activity_level": max(0.0, min(1.0, agent_data.get("activity_level", 0.5))),
                    "active_hours": agent_data.get("active_hours", list(range(8, 23))),
                    "influence_score": max(0.1, min(3.0, agent_data.get("influence_weight", 1.0))),
                    "posting_probability": max(0.0, min(1.0, agent_data.get("posting_probability", 0.5))),
                    "comments_per_time": max(0.0, min(20.0, agent_data.get("comments_per_time", 0.5))),
                    "response_delay_min": delay_min,
                    "response_delay_max": delay_max,
                    "response_delay_label": self._format_delay(delay_min, delay_max),
                    "topics": agent_data.get("topics", [])[:5],
                })
            return configs

        except Exception as e:
            logger.warning(f"Agent config batch LLM failed: {e}, using defaults for batch")
            return [
                {
                    "agent_id": id_offset + idx,
                    "entity_name": e.get("name", f"agent_{id_offset + idx}"),
                    "entity_type": e.get("type", "Entity"),
                    "stance_label": "neutral",
                    "activity_level": 0.5,
                    "posting_probability": 0.5,
                    "active_hours": list(range(8, 23)),
                    "topics": [],
                }
                for idx, e in enumerate(batch_entities)
            ]

    @staticmethod
    def _format_delay(min_m: int, max_m: int) -> str:
        if max_m < 60:
            return f"{min_m}-{max_m} phút"
        elif min_m >= 60:
            return f"{min_m // 60}-{max_m // 60} giờ"
        else:
            return f"{min_m} phút-{max_m // 60} giờ"

    # ──────────────────────────────────────────────
    # Post-processing
    # ──────────────────────────────────────────────

    def _assign_poster_agents(
        self,
        event_config: EventConfig,
        entities: List[Dict[str, Any]],
    ) -> EventConfig:
        """Match initial_posts poster_type to actual entity agent_ids."""
        if not event_config.initial_posts or not entities:
            return event_config

        # Build type → entities index
        entities_by_type: Dict[str, List[Dict]] = {}
        for idx, e in enumerate(entities):
            t = (e.get("type") or e.get("entity_type") or "").lower()
            entities_by_type.setdefault(t, []).append({"agent_id": idx, "name": e.get("name", "")})

        # Build name → entity index
        entities_by_name: Dict[str, int] = {}
        for idx, e in enumerate(entities):
            entities_by_name[(e.get("name") or "").lower()] = idx

        used_idx: Dict[str, int] = {}
        updated_posts = []

        for post in event_config.initial_posts:
            poster_type = post.poster_type.lower()
            poster_name = post.poster_name.lower()
            matched_id = None

            # Try name match first
            if poster_name and poster_name in entities_by_name:
                matched_id = entities_by_name[poster_name]
            # Then type match
            elif poster_type in entities_by_type:
                agents = entities_by_type[poster_type]
                idx = used_idx.get(poster_type, 0) % len(agents)
                matched_id = agents[idx]["agent_id"]
                used_idx[poster_type] = idx + 1
            # Fuzzy type match
            else:
                for atype, agents in entities_by_type.items():
                    if poster_type in atype or atype in poster_type:
                        idx = used_idx.get(atype, 0) % len(agents)
                        matched_id = agents[idx]["agent_id"]
                        used_idx[atype] = idx + 1
                        break

            # Fallback: agent 0
            if matched_id is None:
                matched_id = 0

            post.poster_agent_id = matched_id
            updated_posts.append(post)

        event_config.initial_posts = updated_posts
        return event_config

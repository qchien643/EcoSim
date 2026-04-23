"""
Crisis Injector — Generate crisis scenarios from campaign context via LLM.

E2E Flow: API→CI→LLM→Crisis scenarios
"""

import json
import logging
import os
from typing import List

from ecosim_common.atomic_io import atomic_write_json

from ..config import Config
from ..models.campaign import CrisisEvent, CrisisScenario
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.crisis_injector")

CRISIS_SYSTEM_PROMPT = """\
You are an expert at designing realistic crisis scenarios for economic campaign simulations.

Given a campaign description, generate 3 crisis scenarios + 1 smooth (no-crisis) scenario.
Each crisis should be realistic and domain-appropriate.

Return JSON:
[
    {{
        "name": "Scenario name",
        "description": "What happens",
        "is_smooth": false,
        "events": [
            {{
                "name": "Crisis event name",
                "description": "Detailed description of the crisis",
                "trigger_round": {middle_round},
                "severity": "medium",
                "affected_stakeholders": ["Consumer", "Seller"],
                "news_headline": "BREAKING: ..."
            }}
        ]
    }},
    {{
        "name": "Smooth Scenario",
        "description": "No crisis — campaign runs normally",
        "is_smooth": true,
        "events": []
    }}
]

Rules:
- trigger_round: 1-{total_rounds} (the simulation runs {total_rounds} rounds total)
- Best crisis timing: middle rounds {range_start}-{range_end} are most interesting
- severity: low, medium, high, critical
- news_headline: realistic breaking news for social media
- Include diverse crisis types: supply chain, PR, competitor, regulatory, technical
- The smooth scenario should always be the last one
- Return ONLY valid JSON array
"""


class CrisisInjector:
    """Generate and manage crisis scenarios."""

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    def generate_scenarios(
        self,
        campaign_context: str,
        campaign_id: str = "",
        total_rounds: int = 24,
    ) -> List[CrisisScenario]:
        """Generate crisis scenarios from campaign context."""
        # Load campaign spec if context not provided
        if not campaign_context and campaign_id:
            spec_path = os.path.join(Config.UPLOAD_DIR, f"{campaign_id}_spec.json")
            if os.path.exists(spec_path):
                with open(spec_path, "r", encoding="utf-8") as f:
                    spec = json.load(f)
                campaign_context = (
                    f"Campaign: {spec.get('name', '')}\n"
                    f"Type: {spec.get('campaign_type', '')}\n"
                    f"Market: {spec.get('market', '')}\n"
                    f"Risks: {spec.get('identified_risks', [])}\n"
                    f"Stakeholders: {spec.get('stakeholders', [])}\n"
                    f"Summary: {spec.get('summary', '')}"
                )

        # Format system prompt with dynamic round values
        range_start = max(1, total_rounds // 3)
        range_end = total_rounds * 2 // 3
        middle_round = total_rounds // 2
        system_prompt = CRISIS_SYSTEM_PROMPT.format(
            total_rounds=total_rounds,
            range_start=range_start,
            range_end=range_end,
            middle_round=middle_round,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate crisis scenarios:\n\n{campaign_context}"},
        ]

        result = self.llm.chat_json(messages, temperature=0.6, max_tokens=2000)

        # Parse as list
        scenarios_data = result if isinstance(result, list) else result.get("scenarios", [])

        scenarios = []
        for s in scenarios_data:
            events = []
            for e in s.get("events", []):
                try:
                    events.append(CrisisEvent(
                        name=e.get("name", ""),
                        description=e.get("description", ""),
                        trigger_round=int(e.get("trigger_round", 12)),
                        severity=e.get("severity", "medium"),
                        affected_stakeholders=e.get("affected_stakeholders", []),
                        news_headline=e.get("news_headline", ""),
                    ))
                except (ValueError, KeyError) as err:
                    logger.warning(f"Invalid crisis event: {err}")

            scenarios.append(CrisisScenario(
                name=s.get("name", ""),
                description=s.get("description", ""),
                is_smooth=s.get("is_smooth", False),
                events=events,
            ))

        logger.info(f"Generated {len(scenarios)} crisis scenarios")
        return scenarios

    def save_scenarios(
        self,
        scenarios: List[CrisisScenario],
        output_path: str,
    ) -> str:
        """Save crisis scenarios to JSON."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        data = [s.model_dump(mode="json") for s in scenarios]
        atomic_write_json(output_path, data)

        logger.info(f"Scenarios saved: {output_path}")
        return output_path

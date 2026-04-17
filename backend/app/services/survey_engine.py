"""
Survey Engine — Post-simulation agent survey system.

Conducts surveys by prompting each agent (via LLM) to answer questions
based on their profile and simulation experience.

E2E Flow: API → SurveyEngine.conduct() → [LLM per agent×question] → Results
"""

import random

import hashlib
import json
import logging
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from ..config import Config
from ..models.survey import (
    AgentResponse,
    QuestionCategory,
    QuestionSummary,
    QuestionType,
    Survey,
    SurveyQuestion,
    SurveyResults,
)
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.survey_engine")

# Default economic survey questions
DEFAULT_QUESTIONS = [
    SurveyQuestion(
        id="q1",
        text="Bạn đánh giá mức độ tác động của chiến dịch này đến hoạt động kinh doanh/tiêu dùng của bạn như thế nào?",
        question_type=QuestionType.SCALE_1_10,
        category=QuestionCategory.ECONOMIC,
    ),
    SurveyQuestion(
        id="q2",
        text="Bạn có thay đổi hành vi mua sắm/kinh doanh sau khi xảy ra biến cố không?",
        question_type=QuestionType.YES_NO,
        category=QuestionCategory.BEHAVIOR,
    ),
    SurveyQuestion(
        id="q3",
        text="Cảm nhận chung của bạn về chiến dịch này là gì?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Rất tích cực", "Tích cực", "Trung lập", "Tiêu cực", "Rất tiêu cực"],
        category=QuestionCategory.SENTIMENT,
    ),
    SurveyQuestion(
        id="q4",
        text="Theo bạn, đâu là rủi ro lớn nhất mà chiến dịch này có thể gặp phải?",
        question_type=QuestionType.OPEN_ENDED,
        category=QuestionCategory.ECONOMIC,
    ),
    SurveyQuestion(
        id="q5",
        text="Nếu có biến cố tương tự xảy ra trong tương lai, bạn sẽ phản ứng như thế nào?",
        question_type=QuestionType.OPEN_ENDED,
        category=QuestionCategory.BEHAVIOR,
    ),
]

SURVEY_AGENT_PROMPT = """\
You are role-playing as the following person in an economic simulation:

Name: {agent_name}
Role: {agent_role}
Description: {agent_description}

During the simulation of campaign "{campaign_name}":
- You participated in {total_rounds} rounds
- Your actions during the simulation: {agent_actions_summary}
{crisis_context}
{memory_context}

Now answer this survey question IN CHARACTER as {agent_name}.
Stay true to your role and personality.

Question: {question_text}
{format_instruction}

Respond in Vietnamese with this JSON format:
{{
    "answer": "your answer here",
    "reasoning": "brief explanation of why you chose this answer (1-2 sentences)"
}}
"""


class SurveyEngine:
    """Post-simulation agent survey system."""

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()
        self._surveys: Dict[str, Survey] = {}
        self._results: Dict[str, SurveyResults] = {}

    def create_survey(
        self,
        sim_id: str,
        questions: List[SurveyQuestion] = None,
        num_agents: int = None,
        include_sim_context: bool = True,
    ) -> Survey:
        """Create a survey with questions.

        Args:
            sim_id: Simulation ID to survey
            questions: List of questions (uses defaults if None)
            num_agents: Max agents to survey (None = all)
            include_sim_context: Whether to include sim actions/memories in prompts
        """
        if questions is None:
            questions = DEFAULT_QUESTIONS

        # Assign IDs if missing
        for i, q in enumerate(questions):
            if not q.id:
                q.id = f"q{i+1}"

        survey_id = hashlib.md5(f"{sim_id}_{len(self._surveys)}".encode()).hexdigest()[:8]
        survey = Survey(
            survey_id=f"srv_{survey_id}",
            sim_id=sim_id,
            questions=questions,
            num_agents=num_agents,
            include_sim_context=include_sim_context,
        )

        self._surveys[survey.survey_id] = survey
        logger.info(f"Survey created: {survey.survey_id} with {len(questions)} questions, num_agents={num_agents}, context={include_sim_context}")
        return survey

    def conduct_survey(self, survey_id: str) -> SurveyResults:
        """Conduct the survey: ask each agent each question via LLM.

        Returns aggregated results.
        """
        survey = self._surveys.get(survey_id)
        if not survey:
            raise ValueError(f"Survey {survey_id} not found")

        sim_id = survey.sim_id
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        include_ctx = survey.include_sim_context

        # Load simulation data
        profiles = self._load_profiles(sim_dir)
        actions = self._load_actions(sim_dir) if include_ctx else []
        campaign_spec = self._load_campaign_spec(sim_dir)
        crisis_info = self._load_crisis_info(sim_dir) if include_ctx else ""

        # Sample agents if num_agents is set
        if survey.num_agents and survey.num_agents < len(profiles):
            sampled_indices = sorted(random.sample(range(len(profiles)), survey.num_agents))
            profiles_to_survey = [(i, profiles[i]) for i in sampled_indices]
        else:
            profiles_to_survey = list(enumerate(profiles))

        # Load agent memories from FalkorDB (if available and context enabled)
        memory_mgr = None
        if include_ctx:
            try:
                from .agent_memory import AgentMemoryManager
                memory_mgr = AgentMemoryManager(sim_id=sim_id)
                mem_stats = memory_mgr.get_memory_stats()
                if mem_stats.get("memories", 0) > 0:
                    logger.info(f"Agent memories available: {mem_stats}")
                else:
                    memory_mgr = None
            except Exception as e:
                logger.debug(f"Agent memory not available: {e}")

        # Load agent KG interactions (from GraphMemoryUpdater)
        kg_interactions = {}
        if include_ctx:
            try:
                from falkordb import FalkorDB
                client = FalkorDB(host=Config.FALKORDB_HOST, port=Config.FALKORDB_PORT)
                kg_graph = client.select_graph("ecosim")
                for agent_idx, _ in profiles_to_survey:
                    interactions = self._query_agent_kg_interactions(kg_graph, sim_id, agent_idx)
                    if interactions:
                        kg_interactions[agent_idx] = interactions
                if kg_interactions:
                    logger.info(f"Loaded KG interactions for {len(kg_interactions)} agents")
            except Exception as e:
                logger.debug(f"KG interactions not available: {e}")

        logger.info(
            f"Conducting survey {survey_id}: "
            f"{len(profiles_to_survey)}/{len(profiles)} agents × {len(survey.questions)} questions"
            f"{' (with context)' if include_ctx else ' (no context)'}"
        )

        # Ask each agent each question
        all_responses: Dict[str, List[AgentResponse]] = {
            q.id: [] for q in survey.questions
        }

        for agent_idx, profile in profiles_to_survey:
            agent_actions = self._get_agent_actions(actions, agent_idx)
            agent_name = profile.get("name", f"Agent_{agent_idx}")
            agent_role = profile.get("description", "Unknown role")

            # Load agent memories
            agent_memory_text = ""
            if memory_mgr:
                try:
                    memories = memory_mgr.get_all_agent_memories(str(agent_idx))
                    if memories:
                        mem_lines = []
                        for mem in memories:
                            mem_lines.append(f"  - {mem.get('text', '')}")
                        agent_memory_text = (
                            "\nYour memories from the simulation:\n"
                            + "\n".join(mem_lines[:10])
                        )
                except Exception as e:
                    logger.debug(f"Memory load failed for agent {agent_idx}: {e}")

            # Append KG interaction context (from GraphMemoryUpdater)
            kg_ctx = kg_interactions.get(agent_idx, "")
            if kg_ctx:
                agent_memory_text += f"\n\nYour specific interactions during the simulation:\n{kg_ctx}"

            for question in survey.questions:
                try:
                    response = self._ask_agent(
                        agent_idx=agent_idx,
                        agent_name=agent_name,
                        agent_role=agent_role,
                        agent_description=profile.get("user_char", agent_role),
                        agent_actions=agent_actions,
                        question=question,
                        campaign_name=campaign_spec.get("name", "Unknown"),
                        total_rounds=len(set(a.get("created_at", 0) for a in actions)),
                        crisis_info=crisis_info,
                        memory_context=agent_memory_text,
                    )
                    all_responses[question.id].append(response)
                except Exception as e:
                    logger.warning(f"Failed to survey Agent {agent_idx} on {question.id}: {e}")

        # Aggregate results
        results = self._aggregate(survey, all_responses, len(profiles_to_survey))

        # Save results
        self._results[survey_id] = results
        results_path = os.path.join(sim_dir, "survey_results.json")
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"Survey completed: {results.total_respondents} respondents, saved to {results_path}")
        return results

    def get_results(self, survey_id: str) -> Optional[SurveyResults]:
        """Get cached survey results."""
        return self._results.get(survey_id)

    # ── Private Methods ──

    def _ask_agent(
        self,
        agent_idx: int,
        agent_name: str,
        agent_role: str,
        agent_description: str,
        agent_actions: List[Dict],
        question: SurveyQuestion,
        campaign_name: str,
        total_rounds: int,
        crisis_info: str,
        memory_context: str = "",
    ) -> AgentResponse:
        """Ask one agent one question via LLM."""
        # Summarize agent actions
        action_summary = self._summarize_actions(agent_actions)

        prompt = SURVEY_AGENT_PROMPT.format(
            agent_name=agent_name,
            agent_role=agent_role,
            agent_description=agent_description[:300],
            campaign_name=campaign_name,
            total_rounds=total_rounds,
            agent_actions_summary=action_summary,
            crisis_context=f"\nCrisis event: {crisis_info}" if crisis_info else "",
            memory_context=memory_context,
            question_text=question.text,
            format_instruction=question.format_instruction(),
        )

        result = self.llm.chat_json(
            messages=[
                {"role": "system", "content": "You are role-playing as a survey respondent. Respond in Vietnamese JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=500,
        )

        return AgentResponse(
            agent_id=str(agent_idx),
            agent_name=agent_name,
            agent_role=agent_role,
            question_id=question.id,
            answer=str(result.get("answer", "")),
            reasoning=str(result.get("reasoning", "")),
        )

    def _aggregate(
        self,
        survey: Survey,
        all_responses: Dict[str, List[AgentResponse]],
        total_agents: int,
    ) -> SurveyResults:
        """Aggregate responses into summaries per question."""
        question_summaries = []

        for question in survey.questions:
            responses = all_responses.get(question.id, [])
            summary = QuestionSummary(
                question_id=question.id,
                question_text=question.text,
                question_type=question.question_type.value,
                responses=responses,
            )

            if question.question_type == QuestionType.SCALE_1_10:
                scores = []
                for r in responses:
                    try:
                        # Extract number from answer
                        num = "".join(c for c in r.answer if c.isdigit())
                        if num:
                            scores.append(int(num[:2]))  # max 2 digits
                    except ValueError:
                        pass
                if scores:
                    summary.average = round(sum(scores) / len(scores), 1)
                    summary.min_val = min(scores)
                    summary.max_val = max(scores)

            elif question.question_type == QuestionType.YES_NO:
                dist = Counter()
                for r in responses:
                    ans = r.answer.strip().upper()
                    if "YES" in ans or "CÓ" in ans.upper():
                        dist["YES"] += 1
                    else:
                        dist["NO"] += 1
                summary.distribution = dict(dist)

            elif question.question_type == QuestionType.MULTIPLE_CHOICE:
                dist = Counter(r.answer for r in responses)
                summary.distribution = dict(dist)

            elif question.question_type == QuestionType.OPEN_ENDED:
                # Extract key themes via simple word frequency
                all_text = " ".join(r.answer for r in responses)
                words = [w.lower() for w in all_text.split() if len(w) > 3]
                common = Counter(words).most_common(5)
                summary.key_themes = [w for w, _ in common]

            question_summaries.append(summary)

        # Cross-analysis by role
        cross = {}
        roles = set(r.agent_role for resps in all_responses.values() for r in resps)
        for role in roles:
            role_data = {}
            for question in survey.questions:
                role_responses = [
                    r for r in all_responses.get(question.id, [])
                    if r.agent_role == role
                ]
                if role_responses:
                    role_data[question.id] = {
                        "count": len(role_responses),
                        "answers": [r.answer for r in role_responses],
                    }
            if role_data:
                cross[role[:50]] = role_data

        return SurveyResults(
            survey_id=survey.survey_id,
            sim_id=survey.sim_id,
            total_respondents=total_agents,
            questions=question_summaries,
            cross_analysis=cross,
        )

    # ── Data Loading Helpers ──

    def _load_profiles(self, sim_dir: str) -> List[Dict]:
        """Load agent profiles from CSV."""
        import csv
        profiles_path = os.path.join(sim_dir, "profiles.csv")
        if not os.path.exists(profiles_path):
            return []
        with open(profiles_path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _load_actions(self, sim_dir: str) -> List[Dict]:
        """Load actions from JSONL."""
        actions_path = os.path.join(sim_dir, "actions.jsonl")
        actions = []
        if os.path.exists(actions_path):
            with open(actions_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            actions.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return actions

    def _load_campaign_spec(self, sim_dir: str) -> Dict:
        """Load campaign spec from simulation config."""
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                campaign_id = config.get("campaign_id", "")
                spec_path = os.path.join(Config.UPLOAD_DIR, f"{campaign_id}_spec.json")
                if os.path.exists(spec_path):
                    with open(spec_path, "r", encoding="utf-8") as sf:
                        return json.load(sf)
        return {"name": "Unknown"}

    def _load_crisis_info(self, sim_dir: str) -> str:
        """Load crisis info summary."""
        crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")
        if os.path.exists(crisis_path):
            with open(crisis_path, "r", encoding="utf-8") as f:
                scenarios = json.load(f)
                if scenarios and isinstance(scenarios[0], dict):
                    first = scenarios[0]
                    events = first.get("events", [])
                    if events:
                        ev = events[0]
                        return f"{ev.get('name', 'Unknown')}: {ev.get('description', '')}"
        return ""

    def _get_agent_actions(self, actions: List[Dict], agent_idx: int) -> List[Dict]:
        """Filter actions for a specific agent."""
        return [a for a in actions if a.get("user_id") == agent_idx]

    def _summarize_actions(self, agent_actions: List[Dict]) -> str:
        """Create a detailed summary of agent's actions (not just counts)."""
        if not agent_actions:
            return "No actions taken"

        types = Counter(a.get("action_type", "unknown") for a in agent_actions)
        parts = [f"{count} {atype}" for atype, count in types.most_common()]

        # Include sample content (up to 3 samples)
        contents = [a.get("content", "") for a in agent_actions if a.get("content")]
        samples = contents[:3]

        summary = f"Actions: {', '.join(parts)}"
        if samples:
            sample_text = "; ".join(f'"{s[:80]}"' for s in samples)
            summary += f'. Content samples: {sample_text}'
        return summary

    def _query_agent_kg_interactions(self, graph, sim_id: str, agent_idx: int) -> str:
        """Query FalkorDB campaign KG for agent's simulation interactions.
        
        Returns formatted text describing the agent's posts, likes, follows.
        """
        lines = []

        try:
            # Agent's posts
            result = graph.query(
                "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid})-[:SIM_POSTED]->(p:SimPost) "
                "RETURN p.content AS content, p.round AS round "
                "ORDER BY p.round "
                "LIMIT 5",
                params={"aid": agent_idx, "sid": sim_id},
            )
            if result.result_set:
                lines.append("Bài viết của bạn:")
                for record in result.result_set:
                    content = (record[0] or "")[:100]
                    rnd = record[1]
                    lines.append(f"  - [Round {rnd}] \"{content}\"")
        except Exception:
            pass

        try:
            # Agent's comments
            result = graph.query(
                "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid})-[:SIM_COMMENTED]->(p:SimPost) "
                "RETURN p.content AS content, p.round AS round "
                "ORDER BY p.round "
                "LIMIT 5",
                params={"aid": agent_idx, "sid": sim_id},
            )
            if result.result_set:
                lines.append("Bình luận của bạn:")
                for record in result.result_set:
                    content = (record[0] or "")[:100]
                    rnd = record[1]
                    lines.append(f"  - [Round {rnd}] \"{content}\"")
        except Exception:
            pass

        try:
            # Agent's follows
            result = graph.query(
                "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid})-[:SIM_FOLLOWED]->(b:SimAgent) "
                "RETURN b.name AS name "
                "LIMIT 10",
                params={"aid": agent_idx, "sid": sim_id},
            )
            if result.result_set:
                names = [record[0] for record in result.result_set if record[0]]
                if names:
                    lines.append(f"Bạn đã follow: {', '.join(names)}")
        except Exception:
            pass

        try:
            # Agent's likes count
            result = graph.query(
                "MATCH (a:SimAgent {agent_id: $aid, sim_id: $sid})-[:SIM_LIKED]->(p:SimPost) "
                "RETURN count(p) AS like_count",
                params={"aid": agent_idx, "sid": sim_id},
            )
            if result.result_set and result.result_set[0][0] > 0:
                lines.append(f"Bạn đã like {result.result_set[0][0]} bài viết")
        except Exception:
            pass

        return "\n".join(lines) if lines else ""


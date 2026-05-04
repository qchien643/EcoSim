"""
ecosim_common — shared utilities cho Core Service và Simulation Service.

Dùng:
    from ecosim_common.config import EcoSimConfig
    from ecosim_common.llm_client import LLMClient
    from ecosim_common.file_parser import FileParser, CampaignDocumentParser
    from ecosim_common.atomic_io import atomic_write_json, atomic_append_jsonl
    from ecosim_common.agent_schemas import AgentProfile, EnrichedAgentLLMOutput, MBTI_TYPES
    from ecosim_common.survey_question_gen import generate_survey_questions, FALLBACK_QUESTIONS
    from ecosim_common.graphiti_factory import make_graphiti, make_falkor_driver
"""

__version__ = "0.1.0"

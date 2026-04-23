"""
Survey Models — Data structures for post-simulation agent surveys.

Supports question types: scale_1_10, yes_no, open_ended, multiple_choice
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    SCALE_1_10 = "scale_1_10"
    YES_NO = "yes_no"
    OPEN_ENDED = "open_ended"
    MULTIPLE_CHOICE = "multiple_choice"


class QuestionCategory(str, Enum):
    GENERAL = "general"
    SENTIMENT = "sentiment"
    BEHAVIOR = "behavior"
    ECONOMIC = "economic"


class SurveyQuestion(BaseModel):
    """A single survey question."""
    id: str = ""
    text: str
    question_type: QuestionType = QuestionType.OPEN_ENDED
    options: List[str] = Field(default_factory=list)  # for multiple_choice
    category: QuestionCategory = QuestionCategory.GENERAL

    def format_instruction(self) -> str:
        """Return format instruction for LLM based on question type."""
        if self.question_type == QuestionType.SCALE_1_10:
            return "Answer with a number from 1 to 10, then explain your reasoning."
        elif self.question_type == QuestionType.YES_NO:
            return "Answer YES or NO, then explain your reasoning."
        elif self.question_type == QuestionType.MULTIPLE_CHOICE:
            opts = ", ".join(self.options)
            return f"Choose one of: [{opts}], then explain your reasoning."
        else:
            return "Provide a detailed answer (2-3 sentences)."


class AgentResponse(BaseModel):
    """One agent's response to one question."""
    agent_id: str
    agent_name: str
    agent_role: str
    question_id: str
    answer: str
    reasoning: str = ""


class QuestionSummary(BaseModel):
    """Aggregated summary for one question across all agents."""
    question_id: str
    question_text: str
    question_type: str
    responses: List[AgentResponse] = Field(default_factory=list)
    # For numeric questions
    average: Optional[float] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    # For categorical questions
    distribution: Dict[str, int] = Field(default_factory=dict)
    # For open-ended
    key_themes: List[str] = Field(default_factory=list)


class Survey(BaseModel):
    """A complete survey definition."""
    survey_id: str = ""
    sim_id: str = ""
    questions: List[SurveyQuestion] = Field(default_factory=list)
    num_agents: Optional[int] = None  # None = all agents
    include_sim_context: bool = True  # False = agent has no knowledge of sim events
    created_at: datetime = Field(default_factory=datetime.now)


class SurveyResults(BaseModel):
    """Complete survey results."""
    survey_id: str = ""
    sim_id: str = ""
    total_respondents: int = 0
    questions: List[QuestionSummary] = Field(default_factory=list)
    cross_analysis: Dict[str, Dict] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)

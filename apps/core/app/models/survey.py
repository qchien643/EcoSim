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


class ReportSection(str, Enum):
    """Map câu hỏi survey tới section nào của Report sẽ cite answer.

    Dùng bởi SurveyQuestionGenerator để đảm bảo mỗi Report section có data
    support. `_tool_survey_result` group questions by field này cho LLM dễ cite.
    """

    EXECUTIVE = "executive"           # Section 1: tổng hợp (hiếm — thường tổng từ sections khác)
    CONTEXT = "context"                # Section 2: demographic, cohort (MBTI/age/domain)
    CONTENT = "content"                # Section 3: topic relevance, share of voice, narrative
    KPI = "kpi"                        # Section 4: measurable behaviors (intent, retention, referral)
    RESPONSE = "response"              # Section 5: crisis reaction, sentiment, attribution
    RECOMMENDATION = "recommendation"  # Section 6: future intent, suggestions


class SurveyQuestion(BaseModel):
    """A single survey question."""
    id: str = ""
    text: str
    question_type: QuestionType = QuestionType.OPEN_ENDED
    options: List[str] = Field(default_factory=list)  # for multiple_choice
    category: QuestionCategory = QuestionCategory.GENERAL
    # Tier B+ redesign: rationale cho auto-generated questions — giải thích
    # vì sao câu hỏi này hữu ích cho context sim. Empty string cho manual questions.
    rationale: str = ""
    # Tier B++ redesign: tag target Report section để Report cite đúng context.
    # Empty = general (không gắn section cụ thể).
    report_section: str = ""

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


# ═══════════════════════════════════════════════
# Canonical DEFAULT_QUESTIONS — single source of truth
# ═══════════════════════════════════════════════
# Dùng ở `apps/core/app/services/survey_engine.py` và proxy qua
# `GET /api/survey/default-questions`. Trước đây duplicate ở 2 chỗ với
# category strings không khớp enum — unified ở đây.

DEFAULT_QUESTIONS: List["SurveyQuestion"] = [
    SurveyQuestion(
        id="q1",
        text="Bạn đánh giá mức độ tác động của chiến dịch này đến hoạt động kinh doanh/tiêu dùng của bạn như thế nào?",
        question_type=QuestionType.SCALE_1_10,
        category=QuestionCategory.ECONOMIC,
        report_section=ReportSection.KPI.value,
    ),
    SurveyQuestion(
        id="q2",
        text="Bạn có thay đổi hành vi mua sắm/kinh doanh sau khi xảy ra biến cố không?",
        question_type=QuestionType.YES_NO,
        options=["Yes", "No"],
        category=QuestionCategory.BEHAVIOR,
        report_section=ReportSection.RESPONSE.value,
    ),
    SurveyQuestion(
        id="q3",
        text="Cảm nhận chung của bạn về chiến dịch này là gì?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Rất tích cực", "Tích cực", "Trung lập", "Tiêu cực", "Rất tiêu cực"],
        category=QuestionCategory.SENTIMENT,
        report_section=ReportSection.RESPONSE.value,
    ),
    SurveyQuestion(
        id="q4",
        text="Theo bạn, đâu là rủi ro lớn nhất mà chiến dịch này có thể gặp phải?",
        question_type=QuestionType.OPEN_ENDED,
        category=QuestionCategory.ECONOMIC,
        report_section=ReportSection.RECOMMENDATION.value,
    ),
    SurveyQuestion(
        id="q5",
        text="Nếu có biến cố tương tự xảy ra trong tương lai, bạn sẽ phản ứng như thế nào?",
        question_type=QuestionType.OPEN_ENDED,
        category=QuestionCategory.BEHAVIOR,
        report_section=ReportSection.RECOMMENDATION.value,
    ),
]


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

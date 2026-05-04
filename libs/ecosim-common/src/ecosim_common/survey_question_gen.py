"""
Survey Question Generator — LLM tự sinh câu hỏi khảo sát hậu mô phỏng.

Input: campaign_spec + sim_overview (+ sentiment_summary, crisis_events).
Output: list of dicts khớp `QuestionDef` shape:
    {text, question_type, options, category, rationale}

Dùng `ecosim_common.llm_client.LLMClient` nên chạy được cả Core + Simulation venv.

Design quyết định:
- Không import Core's Pydantic models để tránh coupling lib → Core. Trả dict thuần.
- Caller (Core hoặc Sim endpoint) tự wrap thành Pydantic model nếu cần validate.
- Fallback: DEFAULT_QUESTIONS hardcoded (5 câu) nếu LLM fail 2 lần.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient

logger = logging.getLogger("ecosim_common.survey_gen")


# Canonical schema values — mirror apps/core/app/models/survey.py enums
VALID_QUESTION_TYPES = {"scale_1_10", "yes_no", "open_ended", "multiple_choice"}
VALID_CATEGORIES = {"general", "sentiment", "behavior", "economic"}

# Report section target cho từng câu hỏi — match apps/core/app/models/survey.py:ReportSection
# Dùng để Report cite survey evidence đúng section.
VALID_REPORT_SECTIONS = {
    "executive",       # S1: hiếm dùng — thường tổng hợp
    "context",         # S2: cohorts, demographics
    "content",         # S3: topics, narrative
    "kpi",             # S4: measurable behaviors
    "response",        # S5: crisis reaction, sentiment, attribution
    "recommendation",  # S6: future intent, suggestions
}
# Sections bắt buộc phải có ít nhất 1 câu hỏi cover (excluding executive — tổng hợp)
MANDATORY_REPORT_SECTIONS = ["context", "content", "response", "recommendation"]

# Mandatory categories theo campaign_type — nếu LLM miss, retry prompt force include.
CAMPAIGN_TYPE_MANDATORY: Dict[str, List[str]] = {
    "marketing": ["general", "sentiment", "behavior"],
    "pricing": ["economic", "behavior", "sentiment"],
    "policy": ["sentiment", "behavior"],
    "product_launch": ["behavior", "sentiment"],
    "expansion": ["general", "economic"],
    "other": ["general", "sentiment"],
}

# Fallback 5 câu khi LLM fail hoàn toàn — giữ đồng bộ với
# apps/core/app/models/survey.py:DEFAULT_QUESTIONS
FALLBACK_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "q1",
        "text": "Bạn đánh giá mức độ tác động của chiến dịch này đến quyết định của bạn như thế nào?",
        "question_type": "scale_1_10",
        "options": [str(i) for i in range(1, 11)],
        "category": "economic",
        "rationale": "Default fallback — đo direct impact trên hành vi",
        "report_section": "kpi",
    },
    {
        "id": "q2",
        "text": "Bối cảnh nghề nghiệp/sở thích của bạn có liên quan tới chiến dịch này không?",
        "question_type": "yes_no",
        "options": ["Yes", "No"],
        "category": "general",
        "rationale": "Default fallback — segment context cho Section Bối Cảnh",
        "report_section": "context",
    },
    {
        "id": "q3",
        "text": "Cảm nhận chung của bạn về chiến dịch này là gì?",
        "question_type": "multiple_choice",
        "options": ["Rất tích cực", "Tích cực", "Trung lập", "Tiêu cực", "Rất tiêu cực"],
        "category": "sentiment",
        "rationale": "Default fallback — aggregate sentiment Likert cho Section Khảo Sát",
        "report_section": "response",
    },
    {
        "id": "q4",
        "text": "Nội dung nào của chiến dịch thu hút bạn nhất và vì sao?",
        "question_type": "open_ended",
        "options": [],
        "category": "behavior",
        "rationale": "Default fallback — attribution cho Section Diễn Biến",
        "report_section": "content",
    },
    {
        "id": "q5",
        "text": "Bạn có đề xuất gì để cải thiện các chiến dịch tương tự trong tương lai?",
        "question_type": "open_ended",
        "options": [],
        "category": "behavior",
        "rationale": "Default fallback — feedback cho Section Khuyến Nghị",
        "report_section": "recommendation",
    },
]


SYSTEM_PROMPT = """\
You are a survey design expert for consumer behavior and marketing research.
Task: generate {count} survey questions to DEEPLY understand what happened in
the simulation.

Each question must have:
- "id": "q1", "q2", ... (sequential)
- "text": question body, in the language of the campaign market
  (Vietnam/VN → Vietnamese; otherwise English)
- "question_type": ONE of: "scale_1_10" | "yes_no" | "open_ended" | "multiple_choice"
- "options": list of strings (required for multiple_choice;
  scale_1_10 = ["1".."10"]; yes_no = ["Yes","No"]; open_ended = [])
- "category": ONE of: "general" | "sentiment" | "behavior" | "economic"
- "report_section": ONE of: "context" | "content" | "kpi" | "response" | "recommendation"
- "rationale": one sentence in English explaining why this question matters
  and which report section will cite it

REPORT SECTION ALIGNMENT — IMPORTANT:
The post-simulation report has 6 sections. Each question MUST tag `report_section`
so the Report can cite evidence in the right place. Section roles:
- "context" (S2 Background): demographics, cohort (MBTI/age/domain), segment relevance
- "content" (S3 Narrative): topic relevance, share of voice, what agents post/react to
- "kpi" (S4 KPI & Engagement): measurable behaviors (intent to participate,
  influence level, frequency, repeat intent). ONLY when the question is actually
  measurable from the answer (NOT revenue/orders — sim does not track those).
- "response" (S5 Survey & Sentiment): sentiment, crisis reaction, attribution
- "recommendation" (S6 Recommendations): future intent, suggestions, improvements

COVERAGE REQUIREMENT: every section in {{context, content, response, recommendation}}
MUST have at least 1 question. Section "kpi" is optional (only if campaign_type allows).
Section "executive" generally does not need its own question (synthesized elsewhere).

RULES:
1. Mix question types: ≥ 20% scale_1_10, ≥ 20% open_ended; rest mix yes_no + multiple_choice
2. Mandatory categories for campaign_type "{campaign_type}": {mandatory_categories}.
   Each mandatory category must have ≥ 1 question.
3. If crisis_events are present → add 1-2 questions tagged `report_section="response"`
   about reaction to the crisis.
4. Language: auto-detect from market. "Vietnam"/"VN" → Vietnamese text. Else English.
5. DO NOT invent campaign details. Use only text from campaign_spec + summary
   + sentiment data when provided.
6. Avoid leading questions (e.g. "Do you think the campaign is amazing?" → bias).
7. DO NOT ask about revenue/doanh thu/orders/đơn hàng/pricing/ROI — the simulation
   does not track these, so even if users answer, the report cannot cite the
   answers (not measurable).

Return STRICT JSON: {{"questions": [<object>, <object>, ...]}}
"""

USER_TEMPLATE = """\
## CAMPAIGN CONTEXT
Name: {name}
Type: {campaign_type}
Market: {market}
Summary: {summary}
KPIs: {kpis}
Identified risks: {risks}

## SIM OVERVIEW
{sim_overview}

## SENTIMENT ANALYSIS (cached, if available)
{sentiment_block}

## CRISIS EVENTS (triggered in sim)
{crisis_block}

Generate {count} diverse questions per the RULES in the system prompt.
"""


def _format_sentiment(sentiment_summary: Optional[Dict]) -> str:
    if not sentiment_summary:
        return "(Sentiment chưa được chạy — bỏ qua)"
    dist = sentiment_summary.get("distribution") or {}
    nss = sentiment_summary.get("nss")
    n = sentiment_summary.get("total_comments")
    return (
        f"Distribution: +{dist.get('positive', 0)} / ={dist.get('neutral', 0)} / -{dist.get('negative', 0)}. "
        f"NSS={nss}. n={n} comments."
    )


def _format_crisis(crisis_events: Optional[List[Dict]]) -> str:
    if not crisis_events:
        return "(Không có crisis)"
    lines = []
    for ev in crisis_events[:5]:
        title = ev.get("title") or ev.get("name", "Unknown crisis")
        rnd = ev.get("trigger_round", "?")
        sev = ev.get("severity", "?")
        domains = ev.get("affected_domains", [])
        lines.append(f"- [Round {rnd}, severity={sev}] {title} (domains={domains})")
    return "\n".join(lines)


def _validate_question(q: Any) -> Optional[Dict]:
    """Return cleaned question dict or None nếu invalid."""
    if not isinstance(q, dict):
        return None
    text = (q.get("text") or "").strip()
    qtype = (q.get("question_type") or "").strip().lower()
    category = (q.get("category") or "").strip().lower()
    options = q.get("options") or []
    rationale = (q.get("rationale") or "").strip()
    qid = (q.get("id") or "").strip()
    report_section = (q.get("report_section") or "").strip().lower()

    if not text or len(text) < 5:
        return None
    if qtype not in VALID_QUESTION_TYPES:
        return None
    if category not in VALID_CATEGORIES:
        alias_map = {
            "satisfaction": "sentiment", "nps": "behavior",
            "product_interest": "general", "feedback": "general",
            "purchase_intent": "behavior", "economics": "economic",
        }
        category = alias_map.get(category, "general")

    # Report section validate + alias rescue
    if report_section not in VALID_REPORT_SECTIONS:
        section_alias = {
            "summary": "executive", "overview": "executive",
            "demographic": "context", "cohort": "context",
            "narrative": "content", "topic": "content",
            "engagement": "kpi", "metric": "kpi",
            "sentiment": "response", "crisis": "response", "feedback": "response",
            "future": "recommendation", "suggestion": "recommendation",
            "improve": "recommendation",
        }
        report_section = section_alias.get(report_section, "")

    if not isinstance(options, list):
        options = []

    # Fix options cho từng type
    if qtype == "scale_1_10":
        options = [str(i) for i in range(1, 11)]
    elif qtype == "yes_no":
        if not options or len(options) != 2:
            options = ["Yes", "No"]
    elif qtype == "multiple_choice":
        if not options or len(options) < 2:
            return None  # MC cần ≥ 2 options
        options = [str(o) for o in options[:8]]
    elif qtype == "open_ended":
        options = []

    return {
        "id": qid,
        "text": text,
        "question_type": qtype,
        "options": options,
        "category": category,
        "rationale": rationale or "(no rationale provided)",
        "report_section": report_section,
    }


def _check_diversity(questions: List[Dict], mandatory_cats: List[str]) -> List[str]:
    """Return list các vi phạm rule (empty nếu OK)."""
    violations: List[str] = []
    if not questions:
        return ["empty"]
    types = [q["question_type"] for q in questions]
    cats = [q["category"] for q in questions]
    sections = [q.get("report_section", "") for q in questions]
    n = len(questions)
    scale_pct = sum(1 for t in types if t == "scale_1_10") / n
    open_pct = sum(1 for t in types if t == "open_ended") / n
    if scale_pct < 0.15:
        violations.append(f"too few scale_1_10 ({scale_pct:.0%}, need ≥ 20%)")
    if open_pct < 0.15:
        violations.append(f"too few open_ended ({open_pct:.0%}, need ≥ 20%)")
    for mcat in mandatory_cats:
        if mcat not in cats:
            violations.append(f"missing mandatory category '{mcat}'")
    # Section coverage: cần ≥ 3 mandatory sections (lỏng hơn 4 để flexibility)
    covered = set(sections) & set(MANDATORY_REPORT_SECTIONS)
    missing_sections = [s for s in MANDATORY_REPORT_SECTIONS if s not in covered]
    if len(covered) < 3:
        violations.append(
            f"only {len(covered)}/4 mandatory report sections covered "
            f"(missing: {missing_sections})"
        )
    return violations


def generate_survey_questions(
    campaign_spec: Dict[str, Any],
    sim_overview: Optional[Dict[str, Any]] = None,
    sentiment_summary: Optional[Dict[str, Any]] = None,
    crisis_events: Optional[List[Dict[str, Any]]] = None,
    count: int = 10,
    categories: Optional[List[str]] = None,
    llm: Optional[LLMClient] = None,
    max_retries: int = 1,
) -> List[Dict[str, Any]]:
    """Sinh `count` câu hỏi khảo sát đa dạng từ sim context.

    Args:
        campaign_spec: CampaignSpec dict (name, campaign_type, market, kpis, ...).
        sim_overview: {total_actions, total_agents, total_rounds, action_types, mbti_distribution}.
        sentiment_summary: `analysis_results.results.sentiment` từ Sentiment Analysis.
        crisis_events: list CrisisEvent dicts với trigger_round + title + affected_domains.
        count: số câu hỏi mong muốn (8-12 khuyến nghị).
        categories: allowlist — None = all relevant theo campaign_type.
        llm: inject LLMClient (test mock). None → tạo mới.
        max_retries: số lần retry với stricter prompt nếu validation fail.

    Returns:
        List[dict] — mỗi dict có schema QuestionDef + rationale. Nếu LLM fail
        hoàn toàn → FALLBACK_QUESTIONS (5 câu).
    """
    llm = llm or LLMClient()

    campaign_type = (campaign_spec.get("campaign_type") or "other").lower()
    mandatory_cats = CAMPAIGN_TYPE_MANDATORY.get(campaign_type, ["general", "sentiment"])
    if categories:
        # Intersect với whitelist nếu user chỉ định
        mandatory_cats = [c for c in mandatory_cats if c in categories]

    sys_prompt = SYSTEM_PROMPT.format(
        count=count,
        campaign_type=campaign_type,
        mandatory_categories=", ".join(mandatory_cats),
    )

    user_prompt = USER_TEMPLATE.format(
        name=campaign_spec.get("name", "Unknown"),
        campaign_type=campaign_type,
        market=campaign_spec.get("market", "N/A"),
        summary=campaign_spec.get("summary", "")[:800],
        kpis=", ".join((campaign_spec.get("kpis") or [])[:5]) or "(none)",
        risks=", ".join((campaign_spec.get("identified_risks") or [])[:5]) or "(none)",
        sim_overview=str(sim_overview or "(no overview)")[:600],
        sentiment_block=_format_sentiment(sentiment_summary),
        crisis_block=_format_crisis(crisis_events),
        count=count,
    )

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    attempt = 0
    while attempt <= max_retries:
        try:
            raw = llm.chat_json(messages=messages, temperature=0.4, max_tokens=3000)
            questions_raw = raw.get("questions") if isinstance(raw, dict) else raw
            if not isinstance(questions_raw, list):
                raise ValueError("LLM output missing 'questions' list")

            cleaned: List[Dict] = []
            for i, q in enumerate(questions_raw):
                v = _validate_question(q)
                if v is None:
                    continue
                if not v["id"]:
                    v["id"] = f"q{len(cleaned) + 1}"
                cleaned.append(v)

            violations = _check_diversity(cleaned, mandatory_cats)
            if not violations and len(cleaned) >= max(3, count - 2):
                logger.info(
                    "SurveyQuestionGenerator succeeded (attempt %d, %d questions)",
                    attempt + 1, len(cleaned),
                )
                return cleaned[:count + 2]  # allow slight overflow

            logger.warning(
                "SurveyQuestionGenerator validation failed (attempt %d): %s. Retrying.",
                attempt + 1, violations,
            )
            # Stricter retry
            messages.append({"role": "assistant", "content": str(raw)[:500]})
            messages.append({
                "role": "user",
                "content": (
                    f"Your output violates the rules: {violations}. "
                    "Regenerate STRICT JSON {\"questions\": [...]} that satisfies "
                    "every rule in the system prompt."
                ),
            })
        except Exception as e:
            logger.warning("SurveyQuestionGenerator LLM call failed (attempt %d): %s", attempt + 1, e)

        attempt += 1

    logger.warning("SurveyQuestionGenerator fell back to 5 default questions")
    return list(FALLBACK_QUESTIONS)

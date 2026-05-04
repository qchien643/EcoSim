"""
Economic Report Agent — Enterprise-grade ReACT-style (v3).

2-phase architecture (MiroFish pattern):
  Phase 1: LLM plans 3-5 section outline
  Phase 2: Per-section ReACT loop (min 3 / max 5 tool calls)

Output structure:
  data/simulations/{sim_id}/report/
  ├── meta.json, outline.json, progress.json
  ├── section_01.md … section_NN.md
  ├── full_report.md
  └── agent_log.jsonl
"""

import json
import logging
import os
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ecosim_common.atomic_io import atomic_write_json
from ecosim_common.agent_interview import (
    BUILTIN_LOADERS,
    INTENT_CLASSIFIER_PROMPT,
    INTENT_INFO_MAP,
    INTERVIEW_INTENTS,
    build_response_prompt,
    load_context_blocks,
)
from ecosim_common.config import EcoSimConfig

from ..config import Config
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.report_agent")


# ═══════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════

class ReportStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EvidenceItem:
    """Một mảnh dữ liệu cụ thể trích dẫn trong báo cáo.

    Source tag ⊂ {SIM, KG, SPEC, CALC, MEM} (xem SECTION_SYSTEM_PROMPT).
    Citation dùng anchor dạng `[EV-{id}]` trong final_answer, resolve ở bibliography.
    """

    evidence_id: int
    source: str                 # SIM | KG | SPEC | CALC | MEM
    summary: str                # one-sentence summary — sẽ xuất hiện trong bibliography
    quote: str = ""             # nguyên văn post/comment nếu là SIM content
    ref: str = ""               # post_id=XX / agent=YY / round=Z / entity=...
    raw: Optional[Dict] = None  # full data cho debugging

    def to_dict(self):
        return {
            "id": self.evidence_id,
            "source": self.source,
            "summary": self.summary,
            "quote": self.quote,
            "ref": self.ref,
        }


class EvidenceStore:
    """Tích luỹ evidence qua tool calls + render bibliography cuối báo cáo."""

    def __init__(self):
        self._items: List[EvidenceItem] = []
        self._next_id = 1

    def add(self, source: str, summary: str, quote: str = "",
            ref: str = "", raw: Optional[Dict] = None) -> EvidenceItem:
        item = EvidenceItem(
            evidence_id=self._next_id, source=source, summary=summary[:300],
            quote=quote[:500], ref=ref, raw=raw,
        )
        self._items.append(item)
        self._next_id += 1
        return item

    def render_anchors(self, items: List[EvidenceItem]) -> str:
        """Render list "(EV-1)(EV-2)" để nhắc LLM trích dẫn."""
        return " ".join(f"(EV-{it.evidence_id})" for it in items)

    def items(self) -> List[EvidenceItem]:
        return list(self._items)

    def bibliography_md(self) -> str:
        if not self._items:
            return ""
        lines = ["## Nguồn dữ liệu tham chiếu\n"]
        for it in self._items:
            anchor = f"**[EV-{it.evidence_id}]** `{it.source}`"
            body = f"{it.summary}"
            if it.quote:
                body += f' — "{it.quote[:200]}..."' if len(it.quote) > 200 else f' — "{it.quote}"'
            if it.ref:
                body += f"  _({it.ref})_"
            lines.append(f"- {anchor}: {body}")
        return "\n".join(lines)


@dataclass
class ReportSection:
    title: str
    description: str
    content: str = ""
    tool_calls_used: int = 0
    evidence_refs: List[int] = field(default_factory=list)  # [EV-id] referenced

    def to_dict(self):
        return asdict(self)


@dataclass
class ReportOutline:
    title: str
    summary: str
    sections: List[ReportSection] = field(default_factory=list)

    def to_dict(self):
        return {"title": self.title, "summary": self.summary,
                "sections": [s.to_dict() for s in self.sections]}


@dataclass
class Report:
    report_id: str
    sim_id: str
    status: ReportStatus = ReportStatus.PENDING
    outline: Optional[ReportOutline] = None
    sections: List[ReportSection] = field(default_factory=list)
    markdown_content: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self):
        return {
            "report_id": self.report_id, "sim_id": self.sim_id,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "sections_count": len(self.sections),
            "created_at": self.created_at, "completed_at": self.completed_at,
        }


class ReportLogger:
    """JSONL structured logger for full agent replay."""

    def __init__(self, log_path: str, report_id: str):
        self.log_path = log_path
        self.report_id = report_id
        self._start = time.time()
        self._file = open(log_path, "a", encoding="utf-8")

    def log(self, action: str, **kwargs):
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_s": round(time.time() - self._start, 2),
            "report_id": self.report_id, "action": action, **kwargs,
        }
        self._file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self):
        if self._file and not self._file.closed:
            self._file.close()


# ═══════════════════════════════════════════════
# PROMPT TEMPLATES (English; report OUTPUT language = campaign market language)
# ═══════════════════════════════════════════════

PLAN_SYSTEM_PROMPT = """\
You are an economic analyst with a god's-eye view of the simulation results.
Plan an outline for a campaign analysis report based on REAL SIMULATION DATA.
This report is a FORWARD-LOOKING projection based on simulation outcomes —
it is NOT an analysis of the present state.

Outline MUST adapt to campaign_type (marketing / pricing / policy / product_launch / ...).
Examples:
- "marketing" → focus on engagement, share-of-voice, sentiment, brand lift
- "pricing" → focus on price sensitivity, cohort response, competitor reaction
- "policy" → focus on stance shift, polarization, regulation narrative
- "product_launch" → focus on adoption curve, early adopter vs laggard, feedback themes

NOTE on section TITLES: write titles and descriptions in VIETNAMESE because
the final report will be rendered in Vietnamese. System instructions stay in English.
"""

PLAN_USER_PROMPT = """\
Based on the following data, plan the outline for the campaign analysis report.

CAMPAIGN SPEC:
- Name: {campaign_name}
- Type: {campaign_type}
- Market: {market}
- KPIs: {kpis}
- Identified risks: {risks}

KNOWLEDGE GRAPH STATS:
{graph_stats}

SIMULATION OVERVIEW:
{sim_overview}

REQUIREMENTS:
- Produce 5-6 sections in fixed order after "Executive Summary":
  1. Executive Summary (required) — 3-5 bullet point findings, most important first
  2. Context & Audience — stakeholders, cohorts, MBTI/demographics
  3. Narrative & Content — timeline, topic clusters, representative quotes
  4. KPI & Engagement — compare target vs actual per KPI
  5. Crisis impact & Sentiment — pre/post comparison if crisis exists
  6. Strategic recommendations — concrete action items with priority (high/medium/low)
- Each section MUST fit the campaign_type (adjust framing + suggested_tools).
- Write section titles and descriptions in VIETNAMESE (≤ 60 chars for title,
  1-2 sentences for description).

Return STRICT JSON:
{{"title": "...", "summary": "...", "sections": [{{"title": "...", "description": "...", "suggested_tools": ["tool1","tool2"]}}]}}
"""

SIM_DATA_CAPABILITIES = """\
═══════════════════════════════════════════════════════════════
SIMULATION DATA MODEL — STRICT COMPLIANCE REQUIRED:
═══════════════════════════════════════════════════════════════

Sim DOES track (citable with source [SIM] + (EV-n)):
- Actions: create_post, create_comment, like_post, follow_user, repost
- Per-agent metrics: post count, comment count, likes received, followers count
- Content: post body, comment body (Vietnamese/English text)
- Sentiment: RoBERTa positive/neutral/negative classification on comments
- Cognitive: MBTI type, interest vector (KeyBERT drift), memory buffer
- Knowledge Graph: campaign entities (Company/Product/Audience/...), relationships
- Crisis events: trigger_round, affected_domains, severity — only if injected

Sim DOES NOT track (FORBIDDEN to fabricate numbers for these — they do not exist):
- Revenue / doanh thu / money / transaction value (VNĐ / USD / millions / billions)
- Order count / orders / transactions / conversions
- CTR / click-through rate / ROI / ROAS / conversion rate
- Product prices / pricing / inventory / stock
- Customer satisfaction score / NPS / brand lift / brand awareness %
  (ONLY permitted when cited via (EV-n) from tool survey_result or interview_agents)
- Market share / competitor-specific metrics
- Physical-world events outside campaign spec or crisis log

STRICT RULES:
• If a KPI/claim mentions a metric in the "DOES NOT track" list → verdict='unmeasurable'
  + note "Sim does not track [category]; external data or survey needed"
• DO NOT fabricate numbers like "1.2 tỷ VNĐ" / "15,000 orders" / "85% customer satisfaction"
• Only cite numbers when you have tool evidence + matching (EV-n) anchor in the same sentence
• Instead of vague "no data available", be specific about what IS tracked:
  "Sim tracks X posts + Y comments + Z likes ([SIM] (EV-N)) — revenue not measured"
═══════════════════════════════════════════════════════════════
"""

SECTION_SYSTEM_PROMPT = """\
You are an economic analyst writing ONE SECTION of a campaign analysis report.

{sim_capabilities}

YOU HAVE {tool_count} DATA-COLLECTION TOOLS:
{tool_descriptions}

MANDATORY RULES:
1. You MUST call at least 3 DIFFERENT tools before writing content. Writing with
   fewer tool calls will be REJECTED.
   - "Executive Summary" and "Khuyến Nghị Chiến Lược" sections may use 2 tools
     (they synthesize from earlier sections).
2. Every number or specific claim MUST have a source tag + evidence anchor:
   - Source tags: [SIM] = simulation data, [KG] = knowledge graph,
     [SPEC] = campaign spec, [CALC] = derived calculation,
     [MEM] = agent memory / reflection / interview.
   - Evidence anchors: after each tool call you will receive `(EV-N)` tags — cite
     them at sentence end, e.g.: "Engagement giảm 34% sau crisis [SIM] (EV-3)".
     Anchors resolve in the final bibliography section.
3. ABSOLUTELY NO fabricated numbers. Re-read the SIM DATA MODEL above — if a
   metric is not in "Sim DOES track" → verdict='unmeasurable' or write
   "Sim không đo [metric], chỉ trace [replacement]".
   ABSOLUTELY FORBIDDEN examples: "Doanh thu đạt 1.2 tỷ VNĐ", "15.000 đơn hàng",
   "85% khách hàng hài lòng" (when there is no matching EV-id).
4. Quote agent posts/comments verbatim when analyzing content (at least 1 quote
   per content-heavy section), with agent name + round, e.g.:
   > "Mình thấy freeship không còn..." — Nguyễn Thị Lan (Round 5) (EV-7).
5. Clearly distinguish TARGET (from campaign spec, may be unmeasurable) vs
   RESULT (from simulation trace).
6. OUTPUT LANGUAGE: write the section body in VIETNAMESE with professional and
   specific tone (no vague "nhiều" / "đáng kể" — use numbers). System instructions
   stay in English; only the written section content is Vietnamese.
7. Use only **bold**, *italic*, bullet list `-`, and markdown table. DO NOT use
   headers `##`/`###` (reserved for outline level).
8. Recommendations and action items MUST have priority: 🔴 High / 🟡 Medium / 🟢 Low.

TOOL CALL FORMAT:
<tool_call>{{"name": "tool_name", "parameters": {{"key": "value"}}}}</tool_call>

WHEN DONE, WRITE:
<final_answer>
[Vietnamese section content with [SIM]/[KG]/[SPEC]/[CALC]/[MEM] tags + (EV-N) citations]
</final_answer>
"""

SECTION_USER_PROMPT = """\
CURRENT SECTION: {section_title}
DESCRIPTION: {section_description}

PREVIOUS SECTIONS ALREADY WRITTEN:
{previous_sections}

Collect data with the tools, then write the Vietnamese content for this section.
"""

REACT_OBSERVATION = """\
[Observation] Result from tool "{tool_name}" (tool {used}/{max}):
{result}

Evidence added: {evidence_anchors}
Unused tools: {unused_tools}

CITATION RULE: in <final_answer>, every number drawn from this tool must cite
the matching anchor above. If you have enough data (≥3 tools), write <final_answer>.
Otherwise call another tool."""

REACT_INSUFFICIENT_TOOLS = """\
[System] You have only called {used}/{min_required} tools. You MUST call more tools
to collect data before writing content.
Available tools: {available_tools}"""

REACT_TOOL_LIMIT = """\
[System] You have reached the limit of {max}/{max} tool calls. You MUST write
<final_answer> immediately with the data collected so far."""

REACT_FORCE_FINAL = """\
[System] Iteration budget exhausted. Write <final_answer> immediately with the
data you have."""

CHAT_SYSTEM_PROMPT = """\
You are an economic analysis assistant. The user is asking about a campaign
report that has been generated.

REPORT CONTENT:
{report_content}

You can use tools for follow-up lookups:
{tool_descriptions}

Answer in Vietnamese, citing data from the report when possible."""


# ═══════════════════════════════════════════════
# REPORT AGENT
# ═══════════════════════════════════════════════

class ReportAgent:
    """Enterprise-grade ReACT report agent with 2-phase generation."""

    MAX_TOOL_CALLS = 5
    MIN_TOOL_CALLS = 3
    MAX_ITERATIONS = 7
    MAX_CHAT_TOOLS = 2

    TOOL_DEFS = {
        "deep_analysis": "Phân tích chuyên sâu: decompose câu hỏi → multi-query graph search → tổng hợp. Params: {\"query\": \"câu hỏi phân tích\"}",
        "graph_overview": "Tổng quan knowledge graph: toàn bộ entities, edges, phân bố. Params: {}",
        "quick_search": "Tìm kiếm nhanh entity/edge trong graph. Params: {\"keyword\": \"từ khóa\"}",
        "sim_data_query": "Truy vấn dữ liệu mô phỏng: timeline, sentiment, agent activity, content. Params: {\"aspect\": \"overview|actions|agents|content|timeline|impact|sentiment\"}",
        "kpi_check": "So sánh KPI mục tiêu (từ campaign spec) với kết quả mô phỏng thực tế. Trả về bảng đạt/không đạt. Params: {}",
        "influencer_detection": "Xác định top-N influencer dựa trên followers + engagement nhận được + post frequency. Params: {\"top_k\": 5}",
        "topic_cluster": "Cluster nội dung post/comment theo chủ đề (KeyBERT/TF-IDF). Trả về top topics + share of voice. Params: {\"top_k\": 8}",
        "crisis_impact_timeline": "So sánh sentiment + engagement rate + topic shift trước/sau từng crisis. Params: {\"crisis_id\": \"\" (optional, empty = all)}",
        "agent_cohort_analysis": "Phân khúc agents theo tiêu chí + so sánh hành vi giữa cohorts. Params: {\"segment_by\": \"mbti|followers|gender|age|domain\"}",
        "narrative_quotes": "Trích 3-5 post/comment tiêu biểu theo theme + kèm post_id/author/round để citation. Params: {\"theme\": \"từ khóa\", \"k\": 5}",
        "sentiment_result": "Đọc cached sentiment analysis (analysis_results.json): aggregate distribution, NSS, per-round timeline, top positive/negative comments. KHÔNG tốn LLM call. Params: {}",
        "survey_result": "Đọc kết quả survey hậu mô phỏng (default: latest): distribution per closed question + answers grouped by report_section. Params: {\"survey_id\": \"\" (optional, empty = latest)}",
        "interview_agents": "Phỏng vấn REAL-TIME một % agents (mỗi agent 1 LLM call in-character). Dùng khi cần voice-of-agent qualitative. Tốn LLM calls — max 10 agents. Params: {\"question\": \"câu hỏi\", \"sample_pct\": 20, \"stratify_by\": \"random|mbti\", \"max_agents\": 10}",
    }

    def __init__(self, llm_client: LLMClient = None, graph_name: str = ""):
        """Args:
            graph_name: FalkorDB graph name cho sim này (`sim_<sim_id>` sau
                master+fork architecture). Bắt buộc để query KG đúng — không
                truyền sẽ bị warn ở `_get_graph_query`. Có thể được derive
                tự động từ sim_data lúc `_load_sim_data` (nếu để rỗng ở init).
        """
        self.llm = llm_client or LLMClient()
        self.graph_name = graph_name
        self._graph_query = None
        self._sim_data = None
        self._campaign_spec = None
        self._report_logger = None
        self._evidence: EvidenceStore = EvidenceStore()

    # ── Graph Query helper ──

    def _get_graph_query(self):
        if self._graph_query is None:
            from .graph_query import GraphQuery
            # Derive graph_name từ sim config nếu chưa set ở init
            gn = self.graph_name
            if not gn and self._sim_data:
                cfg = self._sim_data.get("config", {})
                gn = cfg.get("kg_graph_name") or (
                    f"sim_{cfg['sim_id']}" if "sim_id" in cfg and not cfg["sim_id"].startswith("sim_")
                    else cfg.get("sim_id", "")
                )
            self._graph_query = GraphQuery(graph_name=gn)
        return self._graph_query

    # ── Data Loading (reuse from v2) ──

    def _load_sim_data(self, sim_dir: str) -> Dict[str, Any]:
        data = {"sim_dir": sim_dir, "actions": [], "config": {}, "profiles": [], "crisis": []}

        actions_path = os.path.join(sim_dir, "actions.jsonl")
        if os.path.exists(actions_path):
            with open(actions_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            action = json.loads(line)
                            if not action.get("content"):
                                action["content"] = self._extract_content(action)
                            data["actions"].append(action)
                        except json.JSONDecodeError:
                            pass

        for config_name in ("sim_config.json", "simulation_config.json"):
            config_path = os.path.join(sim_dir, config_name)
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data["config"] = json.load(f)
                break

        # Simulation service ghi profiles.json (Tier B có thêm persona_evolved + reflection_insights).
        # profiles.csv là legacy path; thử cả hai để tương thích ngược.
        profiles_path_json = os.path.join(sim_dir, "profiles.json")
        profiles_path_csv = os.path.join(sim_dir, "profiles.csv")
        if os.path.exists(profiles_path_json):
            with open(profiles_path_json, "r", encoding="utf-8") as f:
                data["profiles"] = json.load(f)
        elif os.path.exists(profiles_path_csv):
            import csv
            with open(profiles_path_csv, "r", encoding="utf-8") as f:
                data["profiles"] = list(csv.DictReader(f))

        crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")
        if os.path.exists(crisis_path):
            with open(crisis_path, "r", encoding="utf-8") as f:
                data["crisis"] = json.load(f)

        # memory_stats.json (Tier B C6) — optional, dùng cho insights về depth of memory
        memstats_path = os.path.join(sim_dir, "memory_stats.json")
        if os.path.exists(memstats_path):
            try:
                with open(memstats_path, "r", encoding="utf-8") as f:
                    data["memory_stats"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        logger.info(f"Loaded: {len(data['actions'])} actions, {len(data['profiles'])} profiles")
        return data

    def _load_campaign_spec(self, campaign_id: str) -> Dict[str, Any]:
        spec_path = os.path.join(Config.UPLOAD_DIR, f"{campaign_id}_spec.json")
        if os.path.exists(spec_path):
            with open(spec_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"name": "Unknown Campaign", "campaign_type": "unknown"}

    @staticmethod
    def _extract_content(action: dict) -> str:
        content = action.get("content", "")
        if content:
            return content
        info = action.get("info")
        if info:
            if isinstance(info, str):
                try:
                    info = json.loads(info)
                except (json.JSONDecodeError, TypeError):
                    return info
            if isinstance(info, dict):
                return (info.get("content", "") or info.get("text", "")
                        or info.get("post_content", "") or info.get("comment_content", ""))
        return ""

    @staticmethod
    def _get_profile_name(p: dict) -> str:
        """Normalize profile name access — JSON dùng `realname`, CSV legacy dùng `name`."""
        return (
            p.get("realname")
            or p.get("name")
            or p.get("username")
            or f"Agent_{p.get('agent_id', '?')}"
        )

    @staticmethod
    def _get_profile_persona(p: dict) -> str:
        """Prefer evolved persona (Tier B H4) nếu có, fallback base persona."""
        return (
            p.get("persona_evolved")
            or p.get("persona", "")
            or p.get("bio", "")
        )

    @staticmethod
    def _get_action_round(action: dict) -> int:
        r = action.get("round")
        if r is not None:
            try:
                return int(r)
            except (ValueError, TypeError):
                pass
        ca = action.get("created_at")
        if ca is not None:
            try:
                ca_int = int(ca)
                if 0 < ca_int < 1000:
                    return ca_int
            except (ValueError, TypeError):
                pass
        return 0

    # ── Tool Implementations ──

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        """Route tool calls to actual implementations."""
        try:
            if tool_name == "deep_analysis":
                return self._tool_deep_analysis(params.get("query", ""))
            elif tool_name == "graph_overview":
                return self._tool_graph_overview()
            elif tool_name == "quick_search":
                return self._tool_quick_search(params.get("keyword", ""))
            elif tool_name == "sim_data_query":
                return self._tool_sim_data_query(params.get("aspect", "overview"))
            elif tool_name == "kpi_check":
                return self._tool_kpi_check()
            elif tool_name == "influencer_detection":
                return self._tool_influencer_detection(int(params.get("top_k", 5) or 5))
            elif tool_name == "topic_cluster":
                return self._tool_topic_cluster(int(params.get("top_k", 8) or 8))
            elif tool_name == "crisis_impact_timeline":
                return self._tool_crisis_impact_timeline(str(params.get("crisis_id", "") or ""))
            elif tool_name == "agent_cohort_analysis":
                return self._tool_agent_cohort_analysis(str(params.get("segment_by", "mbti") or "mbti"))
            elif tool_name == "narrative_quotes":
                return self._tool_narrative_quotes(
                    str(params.get("theme", "") or ""),
                    int(params.get("k", 5) or 5),
                )
            elif tool_name == "sentiment_result":
                return self._tool_sentiment_result()
            elif tool_name == "survey_result":
                return self._tool_survey_result(str(params.get("survey_id", "") or ""))
            elif tool_name == "interview_agents":
                return self._tool_interview_agents(
                    str(params.get("question", "") or ""),
                    int(params.get("sample_pct", 20) or 20),
                    str(params.get("stratify_by", "random") or "random"),
                    int(params.get("max_agents", 10) or 10),
                )
            else:
                return f"[Error] Unknown tool: {tool_name}"
        except Exception as e:
            logger.warning(f"Tool {tool_name} failed: {e}")
            return f"[Error] Tool {tool_name} failed: {e}"

    def _tool_deep_analysis(self, query: str) -> str:
        """Deep analysis: sub-query → multi-query graph → synthesis."""
        gq = self._get_graph_query()

        # Search entities matching query
        entities = gq.search_entities(query, limit=10)

        # Get neighbors for top entities
        deep_data = {"query": query, "entities": entities[:5], "relationships": []}
        for ent in entities[:3]:
            neighbors = gq.get_neighbors(ent["name"], limit=5)
            deep_data["relationships"].extend(neighbors.get("outgoing", [])[:3])
            deep_data["relationships"].extend(neighbors.get("incoming", [])[:3])

        # Add relevant simulation data
        if self._sim_data:
            actions = self._sim_data.get("actions", [])
            relevant = [a for a in actions
                        if query.lower() in (a.get("content", "") or "").lower()][:5]
            deep_data["relevant_sim_actions"] = [{
                "agent": a.get("agent_name", f"Agent_{a.get('agent_id', '?')}"),
                "type": a.get("action_type", ""), "content": (a.get("content", ""))[:200],
                "round": self._get_action_round(a),
            } for a in relevant]

        return json.dumps(deep_data, ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_graph_overview(self) -> str:
        """Full graph scan: entities, edges, type distributions."""
        gq = self._get_graph_query()
        stats = gq.get_graph_stats()
        entities = gq.get_all_entities(limit=30)
        edges = gq.get_all_edges(limit=30)

        overview = {
            "graph_stats": stats,
            "entities": [{"name": e["name"], "type": e["type"],
                          "desc": e.get("description", "")[:100]} for e in entities],
            "relationships": [{"src": e["source"], "rel": e["rel_type"],
                               "tgt": e["target"]} for e in edges],
        }
        return json.dumps(overview, ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_quick_search(self, keyword: str) -> str:
        """Fast keyword search on graph."""
        gq = self._get_graph_query()
        entities = gq.search_entities(keyword, limit=10)
        return json.dumps({"keyword": keyword, "results": entities},
                          ensure_ascii=False, indent=1, default=str)[:2000]

    def _tool_sim_data_query(self, aspect: str) -> str:
        """Query simulation data by aspect."""
        if not self._sim_data:
            return json.dumps({"error": "No simulation data loaded"})

        actions = self._sim_data.get("actions", [])
        profiles = self._sim_data.get("profiles", [])
        config = self._sim_data.get("config", {})

        meaningful = [a for a in actions
                      if a.get("action_type", "").lower() not in ("trace", "sign_up", "do_nothing")]

        if aspect == "overview":
            total_rounds = (config.get("time_config", {}).get("total_rounds", 0)
                            or config.get("num_rounds", 0)
                            or config.get("total_rounds", 0))
            result = {
                "total_actions": len(meaningful), "total_agents": len(profiles),
                "total_rounds": total_rounds,
                "agent_names": [self._get_profile_name(p) for p in profiles[:20]],
                "mbti_distribution": dict(Counter(p.get("mbti", "?") for p in profiles)),
            }
        elif aspect == "actions":
            action_types = Counter(a.get("action_type", "unknown") for a in meaningful)
            result = {"distribution": dict(action_types), "total": len(meaningful),
                      "most_common": action_types.most_common(5)}
        elif aspect == "agents":
            agent_actions = Counter()
            for a in meaningful:
                aid = str(a.get("agent_id", a.get("user_id", "?")))
                agent_actions[aid] += 1
            name_map = {str(i): self._get_profile_name(p) for i, p in enumerate(profiles)}
            top = [{"id": aid, "name": name_map.get(aid, f"Agent_{aid}"), "actions": cnt}
                   for aid, cnt in agent_actions.most_common(10)]
            result = {"unique_agents": len(agent_actions), "top_agents": top}
        elif aspect == "content":
            posts, comments = [], []
            for a in meaningful:
                content = self._extract_content(a)
                if not content:
                    continue
                atype = (a.get("action_type") or "").lower()
                entry = {"agent": a.get("agent_name", "?"), "content": content[:300],
                         "round": self._get_action_round(a)}
                if "post" in atype:
                    posts.append(entry)
                elif "comment" in atype:
                    comments.append(entry)
            result = {"posts": len(posts), "comments": len(comments),
                      "sample_posts": posts[:8], "sample_comments": comments[:5]}
            # Tier B C1 fix: nếu content quá thưa (post prob thấp hơn vì fix /168),
            # gợi ý LLM retry với aspect rộng hơn thay vì force final_answer yếu.
            if len(posts) + len(comments) < 5:
                result["_hint"] = (
                    "Content thưa. Nên gọi thêm: narrative_quotes (trích quotes diverse), "
                    "sim_data_query(aspect=timeline) để xem phân bố rounds, "
                    "hoặc topic_cluster để cluster nội dung."
                )
        elif aspect == "timeline":
            rounds = {}
            for a in meaningful:
                r = self._get_action_round(a)
                rounds.setdefault(r, Counter())[a.get("action_type", "")] += 1
            timeline = [{"round": r, "actions": dict(rounds[r]), "total": sum(rounds[r].values())}
                        for r in sorted(rounds.keys())]
            result = {"timeline": timeline}
        elif aspect == "impact":
            result = self._compute_crisis_impact(meaningful)
        elif aspect == "sentiment":
            result = self._compute_sentiment(meaningful)
        else:
            result = {"error": f"Unknown aspect: {aspect}"}

        return json.dumps(result, ensure_ascii=False, indent=1, default=str)[:3000]

    def _compute_crisis_impact(self, meaningful: List[Dict]) -> Dict:
        crisis_scenarios = self._sim_data.get("crisis", [])
        crisis_round, crisis_name = None, "No crisis"
        for sc in crisis_scenarios:
            if isinstance(sc, dict):
                for ev in sc.get("events", []):
                    if ev.get("trigger_round"):
                        crisis_round = ev["trigger_round"]
                        crisis_name = ev.get("name", "Unknown")
                        break
        if crisis_round is None:
            return {"crisis": "none"}

        pre = [a for a in meaningful if self._get_action_round(a) < crisis_round]
        post = [a for a in meaningful if self._get_action_round(a) > crisis_round]
        total_rounds = self._sim_data.get("config", {}).get("time_config", {}).get("total_rounds", 72)
        pre_rate = len(pre) / max(crisis_round, 1)
        post_rate = len(post) / max(total_rounds - crisis_round, 1)

        return {
            "crisis_name": crisis_name, "crisis_round": crisis_round,
            "pre_actions": len(pre), "post_actions": len(post),
            "pre_engagement_rate": round(pre_rate, 2),
            "post_engagement_rate": round(post_rate, 2),
            "change_pct": round(((post_rate - pre_rate) / max(pre_rate, 0.01)) * 100, 1),
            "post_crisis_samples": [{
                "agent": a.get("agent_name", "?"), "content": a.get("content", "")[:200],
            } for a in post if a.get("content")][:5],
        }

    # ── New tools: KPI, Influencer, Topic cluster, Crisis timeline, Cohort, Quotes ──

    # Anti-hallucination: pre-classify KPIs that reference metrics sim doesn't trace.
    # Keys là category; values là keyword list (case-insensitive substring match).
    UNMEASURABLE_KEYWORDS: Dict[str, List[str]] = {
        "revenue": ["doanh thu", "revenue", "tiền thu", "thu về", "earning",
                    "vnđ", "vnd", " usd", "triệu đồng", "tỷ đồng", "đồng"],
        "orders": ["đơn hàng", "orders", "đặt hàng", "giao dịch", "transactions",
                   "transaction", "checkout", "cart"],
        "conversion": ["conversion", "ctr", "click-through", "tỷ lệ chuyển đổi",
                        "roi", "roas", "cpa", "cpc", "funnel"],
        "pricing_inventory": ["giá bán", "price ", "inventory", "tồn kho", "stock",
                               "sku"],
        "satisfaction_external": [
            "khách hàng hài lòng", "customer satisfaction", "satisfaction score",
            "nps", "net promoter", "csat", "brand lift", "brand awareness",
        ],
        "market_share": ["market share", "thị phần", "competitor revenue",
                          "competitor share"],
    }

    @classmethod
    def _classify_kpi(cls, kpi_text: str) -> Dict[str, str]:
        """Return dict {measurable: bool, unmeasurable_reason: str}.

        Pre-scan: nếu KPI đề cập metric thuộc `UNMEASURABLE_KEYWORDS` → mark
        unmeasurable + note category. LLM scoring sau đó chỉ chấm measurable
        KPIs, giảm risk bịa số.
        """
        tl = (kpi_text or "").lower()
        for category, keywords in cls.UNMEASURABLE_KEYWORDS.items():
            for kw in keywords:
                if kw in tl:
                    return {"measurable": False, "unmeasurable_reason": category}
        return {"measurable": True, "unmeasurable_reason": ""}

    def _tool_kpi_check(self) -> str:
        """So sánh KPI mục tiêu vs kết quả simulation thực tế.

        Tier B+ anti-hallucination:
        - Pre-classify KPIs thành measurable / unmeasurable theo keyword
        - Chỉ LLM-score measurable KPIs
        - Unmeasurable KPIs auto-verdict='unmeasurable' với note giải thích sim
          không trace category đó — LLM downstream không có cớ bịa số.
        """
        spec = self._campaign_spec or {}
        kpis_raw: List[str] = spec.get("kpis", []) or []
        if not kpis_raw:
            return json.dumps({
                "error": "Campaign spec không có KPI.",
                "kpi_scores": [],
            }, ensure_ascii=False)

        actions = (self._sim_data or {}).get("actions", [])
        meaningful = [a for a in actions
                      if (a.get("action_type") or "").lower() not in ("trace", "sign_up", "do_nothing")]
        profiles = (self._sim_data or {}).get("profiles", [])

        action_types = Counter(a.get("action_type", "") for a in meaningful)
        post_count = sum(v for k, v in action_types.items() if "post" in k.lower())
        comment_count = sum(v for k, v in action_types.items() if "comment" in k.lower())
        like_count = sum(v for k, v in action_types.items() if "like" in k.lower())
        n_agents = max(1, len(profiles))
        engagement_rate = round((comment_count + like_count) / max(post_count, 1), 2)

        observed = {
            "total_posts": post_count,
            "total_comments": comment_count,
            "total_likes": like_count,
            "engagement_rate": engagement_rate,
            "active_agents": len({a.get("user_id") for a in meaningful if a.get("user_id") is not None}),
            "total_agents": len(profiles),
            "participation_pct": round(
                100.0 * len({a.get("user_id") for a in meaningful}) / n_agents, 1
            ),
        }

        # Pre-classify từng KPI
        measurable_list: List[Dict] = []
        unmeasurable_list: List[Dict] = []
        for kpi in kpis_raw:
            cls_info = self._classify_kpi(kpi)
            if cls_info["measurable"]:
                measurable_list.append({"kpi": kpi})
            else:
                unmeasurable_list.append({
                    "kpi": kpi,
                    "observed": "N/A",
                    "verdict": "unmeasurable",
                    "measurable": False,
                    "unmeasurable_reason": cls_info["unmeasurable_reason"],
                    "note": (
                        f"Sim KHÔNG trace '{cls_info['unmeasurable_reason']}' — "
                        f"chỉ đo engagement signals (posts/comments/likes/follows). "
                        f"Cần external data hoặc survey_result để đánh giá."
                    ),
                })

        # LLM score chỉ measurable KPIs (nếu có)
        scored_measurable: List[Dict] = []
        if measurable_list:
            try:
                prompt = (
                    "So sánh từng KPI với observed metrics. ONLY use observed numbers "
                    "provided below — DO NOT invent any data not listed.\n"
                    "Return JSON array:\n"
                    "[{\"kpi\": \"<text>\", \"observed\": \"<observed metric cụ thể>\", "
                    "\"verdict\": \"hit|miss|partial\", \"note\": \"<1 câu giải thích>\"}]\n\n"
                    f"KPIs (đã pre-classify measurable):\n"
                    f"{json.dumps([k['kpi'] for k in measurable_list], ensure_ascii=False)}\n\n"
                    f"Observed metrics (CHỈ dùng số này):\n"
                    f"{json.dumps(observed, ensure_ascii=False)}\n\n"
                    "Chỉ trả JSON array. Không thêm trường nào khác."
                )
                parsed = self.llm.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1, max_tokens=1500,
                )
                rows = parsed if isinstance(parsed, list) else parsed.get("results", [])
                for r in rows:
                    if isinstance(r, dict):
                        r.setdefault("measurable", True)
                        scored_measurable.append(r)
            except Exception as e:
                logger.warning(f"KPI scoring failed: {e}")
                scored_measurable = [{
                    "kpi": item["kpi"], "observed": "N/A", "verdict": "unmeasurable",
                    "measurable": True, "note": "LLM scoring unavailable",
                } for item in measurable_list]

        return json.dumps({
            "observed_metrics": observed,
            "kpi_scores": scored_measurable + unmeasurable_list,
            "n_measurable": len(scored_measurable),
            "n_unmeasurable": len(unmeasurable_list),
            "note": (
                "Unmeasurable KPIs (revenue / orders / conversion / pricing / satisfaction score "
                "without survey) được auto-flagged — DO NOT fabricate numbers for them in report."
            ),
        }, ensure_ascii=False, indent=1, default=str)[:3500]

    def _tool_influencer_detection(self, top_k: int = 5) -> str:
        """Rank agents theo engagement network.

        Score = log(followers+1) × 0.3 + received_likes × 1.0 +
                received_comments × 2.0 + posts_created × 0.5
        """
        actions = (self._sim_data or {}).get("actions", [])
        profiles = (self._sim_data or {}).get("profiles", [])

        posts_by_agent: Counter = Counter()
        likes_received: Counter = Counter()
        comments_received: Counter = Counter()

        # Map post_id → author_id
        post_author: Dict = {}
        for a in actions:
            if (a.get("action_type") or "").lower() == "create_post":
                info = a.get("info") or {}
                if isinstance(info, dict):
                    pid = info.get("post_id")
                    if pid is not None:
                        post_author[pid] = a.get("user_id")
                posts_by_agent[a.get("user_id")] += 1

        for a in actions:
            atype = (a.get("action_type") or "").lower()
            info = a.get("info") or {}
            if not isinstance(info, dict):
                continue
            pid = info.get("post_id")
            author = post_author.get(pid)
            if author is None:
                continue
            if atype == "like_post":
                likes_received[author] += 1
            elif atype == "create_comment":
                comments_received[author] += 1

        import math
        ranked = []
        for idx, p in enumerate(profiles):
            aid = p.get("agent_id", idx)
            followers = int(p.get("followers", 0) or 0)
            score = (
                math.log(followers + 1) * 0.3
                + likes_received.get(aid, 0) * 1.0
                + comments_received.get(aid, 0) * 2.0
                + posts_by_agent.get(aid, 0) * 0.5
            )
            ranked.append({
                "agent_id": aid,
                "name": self._get_profile_name(p),
                "mbti": p.get("mbti", "?"),
                "followers": followers,
                "posts": posts_by_agent.get(aid, 0),
                "likes_received": likes_received.get(aid, 0),
                "comments_received": comments_received.get(aid, 0),
                "influencer_score": round(score, 2),
            })
        ranked.sort(key=lambda x: -x["influencer_score"])
        return json.dumps({"top_influencers": ranked[:top_k], "method": "log-weighted engagement"},
                          ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_topic_cluster(self, top_k: int = 8) -> str:
        """Extract top topics từ post+comment via KeyBERT; fallback N-gram TF.

        Trả về: top topics kèm document count + round distribution (share of voice).
        """
        actions = (self._sim_data or {}).get("actions", [])
        docs: List[tuple] = []  # (content, round)
        for a in actions:
            atype = (a.get("action_type") or "").lower()
            if atype not in ("create_post", "create_comment"):
                continue
            content = self._extract_content(a)
            if content and len(content) > 10:
                docs.append((content, self._get_action_round(a)))

        if not docs:
            return json.dumps({"topics": [], "warning": "Không có content"}, ensure_ascii=False)

        all_text = " ".join(d[0] for d in docs)
        keywords = []
        try:
            # Prefer KeyBERT (nếu cài trong core venv)
            from keybert import KeyBERT  # type: ignore
            kb = KeyBERT()
            raw = kb.extract_keywords(
                all_text, keyphrase_ngram_range=(1, 2),
                stop_words="english", use_mmr=True, diversity=0.5, top_n=top_k,
            )
            keywords = [(kw, float(score)) for kw, score in raw]
        except Exception as _kb_err:
            logger.info(f"KeyBERT unavailable, fallback regex: {_kb_err}")
            # Fallback: simple word frequency
            import re as _re
            words = _re.findall(r"[A-Za-zÀ-ỹ]{4,}", all_text.lower())
            stop = {"the", "and", "that", "this", "với", "của", "những", "được"}
            words = [w for w in words if w not in stop]
            keywords = [(kw, cnt / len(words)) for kw, cnt in Counter(words).most_common(top_k)]

        # Tính share-of-voice theo round cho mỗi topic
        topics = []
        for kw, score in keywords:
            hits = [(c, r) for c, r in docs if kw.lower() in c.lower()]
            round_dist = Counter(r for _c, r in hits)
            topics.append({
                "topic": kw,
                "relevance": round(score, 3),
                "doc_count": len(hits),
                "rounds": sorted(round_dist.keys()),
                "round_distribution": dict(sorted(round_dist.items())),
            })
        return json.dumps({"topics": topics, "total_docs": len(docs)},
                          ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_crisis_impact_timeline(self, crisis_id: str = "") -> str:
        """Đối chiếu sentiment + engagement rate trước/sau mỗi crisis.

        Trả về list per-crisis với pre_rate, post_rate, pre_sentiment, post_sentiment.
        """
        crisis_scenarios = (self._sim_data or {}).get("crisis", [])
        events = []
        for sc in crisis_scenarios:
            if isinstance(sc, dict):
                events.extend(sc.get("events", []) or [])

        if crisis_id:
            events = [e for e in events if str(e.get("crisis_id") or e.get("scenario_id") or "")
                      == crisis_id]
        if not events:
            return json.dumps({"warning": "Không có crisis event nào", "crises": []},
                              ensure_ascii=False)

        actions = (self._sim_data or {}).get("actions", [])
        meaningful = [a for a in actions
                      if (a.get("action_type") or "").lower() not in ("trace", "sign_up", "do_nothing")]
        total_rounds = max(
            (self._get_action_round(a) for a in meaningful), default=0
        )

        results = []
        for ev in events:
            t_round = int(ev.get("trigger_round", 0) or 0)
            if t_round <= 0:
                continue
            pre = [a for a in meaningful if self._get_action_round(a) < t_round]
            post = [a for a in meaningful if self._get_action_round(a) >= t_round]
            pre_rate = round(len(pre) / max(t_round, 1), 2)
            post_rate = round(len(post) / max(total_rounds - t_round + 1, 1), 2)

            results.append({
                "crisis_id": ev.get("crisis_id") or ev.get("scenario_id") or "?",
                "title": ev.get("title") or ev.get("name") or "Unknown crisis",
                "trigger_round": t_round,
                "severity": ev.get("severity", 0.5),
                "affected_domains": ev.get("affected_domains", []),
                "pre_actions": len(pre),
                "post_actions": len(post),
                "pre_engagement_rate": pre_rate,
                "post_engagement_rate": post_rate,
                "engagement_change_pct": round(((post_rate - pre_rate) / max(pre_rate, 0.01)) * 100, 1),
                "post_samples": [
                    {"agent": a.get("agent_name"),
                     "content": (self._extract_content(a) or "")[:160],
                     "round": self._get_action_round(a)}
                    for a in post[:5] if self._extract_content(a)
                ],
            })

        return json.dumps({"crises": results, "total_rounds": total_rounds},
                          ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_agent_cohort_analysis(self, segment_by: str = "mbti") -> str:
        """Phân khúc agents theo tiêu chí + so sánh hành vi.

        segment_by ∈ {mbti, followers, gender, age, domain}. Trả về cohorts + per-cohort stats.
        """
        actions = (self._sim_data or {}).get("actions", [])
        profiles = (self._sim_data or {}).get("profiles", [])

        def _cohort_key(p: dict) -> str:
            if segment_by == "mbti":
                return (p.get("mbti") or "?")
            if segment_by == "followers":
                f = int(p.get("followers", 0) or 0)
                if f < 500:
                    return "micro (<500)"
                if f < 5000:
                    return "medium (500-5k)"
                return "large (5k+)"
            if segment_by == "gender":
                return (p.get("gender") or "?")
            if segment_by == "age":
                age = int(p.get("age", 0) or 0)
                if age < 25:
                    return "18-24"
                if age < 35:
                    return "25-34"
                if age < 50:
                    return "35-49"
                return "50+"
            if segment_by == "domain":
                return (p.get("general_domain") or "general")
            return "?"

        # agent_id → cohort
        cohort_of: Dict = {}
        for idx, p in enumerate(profiles):
            cohort_of[p.get("agent_id", idx)] = _cohort_key(p)
            cohort_of[idx] = _cohort_key(p)  # fallback by index

        cohort_stats: Dict[str, Dict] = {}
        for p in profiles:
            c = _cohort_key(p)
            s = cohort_stats.setdefault(c, {"agents": 0, "posts": 0, "comments": 0, "likes": 0})
            s["agents"] += 1

        for a in actions:
            atype = (a.get("action_type") or "").lower()
            uid = a.get("user_id")
            c = cohort_of.get(uid)
            if c is None:
                continue
            s = cohort_stats.setdefault(c, {"agents": 0, "posts": 0, "comments": 0, "likes": 0})
            if atype == "create_post":
                s["posts"] += 1
            elif atype == "create_comment":
                s["comments"] += 1
            elif atype == "like_post":
                s["likes"] += 1

        cohorts = []
        for c, s in cohort_stats.items():
            agents = max(1, s["agents"])
            cohorts.append({
                "cohort": c,
                "agents": s["agents"],
                "posts": s["posts"],
                "comments": s["comments"],
                "likes": s["likes"],
                "posts_per_agent": round(s["posts"] / agents, 2),
                "comments_per_agent": round(s["comments"] / agents, 2),
                "total_actions": s["posts"] + s["comments"] + s["likes"],
            })
        cohorts.sort(key=lambda x: -x["total_actions"])
        return json.dumps({"segment_by": segment_by, "cohorts": cohorts},
                          ensure_ascii=False, indent=1, default=str)[:3000]

    def _tool_narrative_quotes(self, theme: str = "", k: int = 5) -> str:
        """Trích k post/comment tiêu biểu theo theme, kèm post_id/author/round.

        Mỗi quote là evidence candidate — LLM nên cite bằng [EV-n] trong content.
        """
        actions = (self._sim_data or {}).get("actions", [])
        meaningful = [a for a in actions
                      if (a.get("action_type") or "").lower() in ("create_post", "create_comment")]

        if theme:
            theme_low = theme.lower()
            matched = [a for a in meaningful
                       if theme_low in (self._extract_content(a) or "").lower()]
        else:
            matched = meaningful

        # Diversify: mỗi agent tối đa 1 quote
        seen_agents: set = set()
        quotes = []
        for a in matched:
            uid = a.get("user_id")
            if uid in seen_agents:
                continue
            seen_agents.add(uid)
            content = self._extract_content(a)
            if not content or len(content) < 20:
                continue
            info = a.get("info") or {}
            post_id = info.get("post_id") if isinstance(info, dict) else None
            quotes.append({
                "post_id": post_id,
                "agent": a.get("agent_name", f"Agent_{uid}"),
                "agent_id": uid,
                "action_type": a.get("action_type", ""),
                "round": self._get_action_round(a),
                "content": content[:280],
            })
            if len(quotes) >= k:
                break

        return json.dumps({"theme": theme or "(all)", "quotes": quotes,
                           "total_matched": len(matched)},
                          ensure_ascii=False, indent=1, default=str)[:3000]

    # ── Anti-hallucination: post-gen fabrication scanner ──

    # Patterns hay bị LLM bịa khi sim KHÔNG đo được
    _FABRICATION_PATTERNS: List[str] = [
        # Currency values — "1.2 tỷ VNĐ", "500.000.000 đồng", "50 triệu USD"
        r"\d+[.,]?\d*\s*(VNĐ|VND|USD|triệu|tỷ)\b",
        r"\d{1,3}(?:[.,]\d{3})+\s*(đồng|VNĐ|VND)\b",
        # Orders — "15.000 đơn hàng", "12000 giao dịch"
        r"\d{1,3}(?:[.,]\d{3})+\s*(đơn hàng|đơn|orders|giao dịch|transactions)\b",
        r"\d{3,}\s*(đơn hàng|đơn|orders|giao dịch|transactions)\b",
        # Satisfaction % without EV context
        r"\d+(?:[.,]\d+)?%\s*(khách hàng|customers|users)\s+hài lòng\b",
        # ROI / CTR / conversion
        r"\b(ROI|ROAS|CTR)\s+(?:đạt|reached|là)\s+\d+",
        r"\d+(?:[.,]\d+)?%\s+(conversion|tỷ lệ chuyển đổi)\b",
    ]

    def _scan_fabrication(self, content: str) -> List[str]:
        """Phát hiện patterns có khả năng bịa số.

        Rule: nếu pattern match VÀ trong cùng câu (±80 chars) không có `(EV-N)`
        anchor → warning. Không tự remove content (risk false positive) — chỉ
        log để debug prompt.
        """
        import re as _re
        warnings: List[str] = []
        if not content:
            return warnings
        for pat in self._FABRICATION_PATTERNS:
            try:
                for m in _re.finditer(pat, content, _re.IGNORECASE):
                    start = max(0, m.start() - 80)
                    end = min(len(content), m.end() + 80)
                    context = content[start:end]
                    # Chấp nhận nếu có (EV-N) anchor trong context
                    if _re.search(r"\(EV-\d+\)", context):
                        continue
                    snippet = m.group(0)[:60]
                    warnings.append(
                        f"Possible fabrication '{snippet}' — no (EV-N) anchor nearby"
                    )
            except _re.error:
                continue
        return warnings

    def _finalize_section_content(
        self, section: "ReportSection", content: str, tool_calls_count: int
    ) -> str:
        """Log fabrication warnings + record tool count. Return content unchanged.

        Gọi trước mỗi `return final_answer` trong ReACT loop để đảm bảo scanner
        chạy cho mọi đường thoát (early return, force final, adopt response...).
        """
        section.tool_calls_used = tool_calls_count
        warnings = self._scan_fabrication(content or "")
        if warnings and self._report_logger:
            for w in warnings[:5]:
                self._report_logger.log(
                    "fabrication_warning", section=section.title, warning=w,
                )
            logger.warning(
                "Section '%s' fabrication scan: %d warnings (see agent_log.jsonl)",
                section.title, len(warnings),
            )
        return content or ""

    # ── Sentiment + Survey result consumers (Tier B+ redesign) ──

    def _tool_sentiment_result(self) -> str:
        """Load cached Sentiment Analysis (`analysis_results.json`) để Report consume.

        Không tốn LLM call. Output trả aggregate distribution + NSS + per-round
        timeline + top positive/negative comments.
        """
        sim_dir = (self._sim_data or {}).get("sim_dir") or ""
        analysis_path = os.path.join(sim_dir, "analysis_results.json")
        if not os.path.exists(analysis_path):
            return json.dumps({
                "error": "analysis_results.json không tồn tại",
                "hint": "Chạy GET /api/analysis/summary?sim_id=... trước khi generate report, hoặc set auto_run_sentiment=true",
            }, ensure_ascii=False)

        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                wrapper = json.load(f)
        except Exception as e:
            return json.dumps({"error": f"Failed to read analysis: {e}"}, ensure_ascii=False)

        results = wrapper.get("results", {}) if isinstance(wrapper, dict) else {}
        sentiment = results.get("sentiment", {}) or {}
        per_round = results.get("per_round", []) or []
        campaign_score = results.get("campaign_score", {}) or {}
        engagement = results.get("engagement", {}) or {}

        # Top +/- comments
        details = sentiment.get("details", []) or []
        top_positive = [
            {"comment_id": d.get("comment_id"), "content": (d.get("content") or "")[:200],
             "score": d.get("score")}
            for d in details if d.get("sentiment") == "positive"
        ][:3]
        top_negative = [
            {"comment_id": d.get("comment_id"), "content": (d.get("content") or "")[:200],
             "score": d.get("score")}
            for d in details if d.get("sentiment") == "negative"
        ][:3]

        # Trim per_round timeline
        per_round_summary = [
            {
                "round": r.get("round"),
                "posts": r.get("posts"),
                "comments": r.get("comments"),
                "likes": r.get("likes"),
                "nss": r.get("nss"),
            }
            for r in per_round[:24]
        ]

        result = {
            "timestamp": wrapper.get("timestamp"),
            "distribution": sentiment.get("distribution", {}),
            "nss": sentiment.get("nss"),
            "total_comments": sentiment.get("total_comments"),
            "positive_pct": sentiment.get("positive_pct"),
            "neutral_pct": sentiment.get("neutral_pct"),
            "negative_pct": sentiment.get("negative_pct"),
            "model": sentiment.get("model"),
            "engagement_rate": engagement.get("engagement_rate"),
            "engagement_rating": engagement.get("rating"),
            "campaign_score": campaign_score.get("campaign_score"),
            "campaign_rating": campaign_score.get("rating"),
            "per_round": per_round_summary,
            "top_positive": top_positive,
            "top_negative": top_negative,
        }
        return json.dumps(result, ensure_ascii=False, indent=1, default=str)[:3000]

    @staticmethod
    def _find_latest_survey_file(sim_dir: str) -> Optional[str]:
        """Tìm file survey mới nhất trong sim_dir.

        Ưu tiên: `survey_results.json` (aggregated). Fallback: latest `{sid}.json`
        với `status == completed`.
        """
        import glob as _glob
        agg = os.path.join(sim_dir, "survey_results.json")
        if os.path.exists(agg):
            return agg
        files = sorted(_glob.glob(os.path.join(sim_dir, "survey_*.json")), reverse=True)
        for sf in files:
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == "completed":
                    return sf
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def _tool_survey_result(self, survey_id: str = "") -> str:
        """Load kết quả survey (default: latest) để Report consume.

        Output per question:
        - closed (scale/yes_no/mc): distribution dict + avg (scale only)
        - open_ended: key_themes list + 2 representative answers

        Mỗi question sẽ được `_record_evidence` biến thành 1 EvidenceItem.
        """
        sim_dir = (self._sim_data or {}).get("sim_dir") or ""

        target_path: Optional[str] = None
        if survey_id:
            # Specific survey_id
            candidates = [
                os.path.join(sim_dir, f"{survey_id}.json"),
                os.path.join(sim_dir, f"survey_{survey_id}.json"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    target_path = c
                    break
            if not target_path:
                return json.dumps({
                    "error": f"Survey {survey_id} không tìm thấy trong {sim_dir}",
                }, ensure_ascii=False)
        else:
            target_path = self._find_latest_survey_file(sim_dir)
            if not target_path:
                return json.dumps({
                    "error": "Không có survey nào cho sim này",
                    "hint": "Chạy POST /api/survey/create + /conduct trước, hoặc set auto_run_survey=true",
                }, ensure_ascii=False)

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return json.dumps({"error": f"Failed to read survey: {e}"}, ensure_ascii=False)

        # data có thể là aggregated (survey_results.json) hoặc raw ({sid}.json)
        questions_out: List[Dict] = []

        if "questions" in data and isinstance(data["questions"], list) and data["questions"] and "distribution" in data["questions"][0]:
            # Aggregated format
            for q in data["questions"][:15]:
                item = {
                    "question_id": q.get("question_id"),
                    "text": q.get("question_text", ""),
                    "type": q.get("question_type"),
                    "category": q.get("category", "general"),
                    "report_section": (q.get("report_section") or "").strip(),
                    "distribution": q.get("distribution", {}),
                }
                if q.get("average") is not None:
                    item["average"] = q["average"]
                if q.get("key_themes"):
                    item["key_themes"] = q["key_themes"]
                if q.get("question_type") == "open_ended" and q.get("responses"):
                    item["sample_answers"] = [
                        {"agent": r.get("agent_name"), "answer": (r.get("answer") or "")[:200]}
                        for r in q["responses"][:2]
                    ]
                questions_out.append(item)
        elif "responses" in data:
            # Raw format — compute minimal per-question stats
            questions_meta = data.get("questions", [])
            responses = data.get("responses", [])
            for qdef in questions_meta[:15]:
                q_text = qdef.get("text", "")
                q_type = qdef.get("question_type", "")
                matching = [r for r in responses if r.get("question") == q_text]
                item = {
                    "text": q_text,
                    "type": q_type,
                    "category": qdef.get("category", "general"),
                    "report_section": (qdef.get("report_section") or "").strip(),
                    "response_count": len(matching),
                }
                if q_type in ("scale_1_10", "rating") and matching:
                    import re as _re
                    nums = []
                    for r in matching:
                        m = _re.search(r"\b(\d+(?:\.\d+)?)\b", r.get("answer") or "")
                        if m:
                            v = float(m.group(1))
                            if 1 <= v <= 10:
                                nums.append(v)
                    if nums:
                        item["average"] = round(sum(nums) / len(nums), 1)
                elif matching:
                    item["sample_answers"] = [
                        {"agent": r.get("agent_name"), "answer": (r.get("answer") or "")[:200]}
                        for r in matching[:2]
                    ]
                questions_out.append(item)

        # Tier B++ redesign: group questions by report_section cho Report cite evidence dễ
        by_section: Dict[str, List[Dict]] = {}
        for q in questions_out:
            sec = q.get("report_section") or "general"
            by_section.setdefault(sec, []).append(q)

        result = {
            "survey_id": data.get("survey_id"),
            "sim_id": data.get("sim_id"),
            "total_respondents": data.get("total_respondents", 0),
            "question_count": len(questions_out),
            "by_section": by_section,
            "questions": questions_out,  # giữ backward-compat cho caller cũ
        }
        return json.dumps(result, ensure_ascii=False, indent=1, default=str)[:3500]

    # ── Interview agents (Tier B++ redesign) ──

    def _tool_interview_agents(
        self,
        question: str,
        sample_pct: int = 20,
        stratify_by: str = "random",
        max_agents: int = 10,
    ) -> str:
        """Real-time interview with a sampled cohort using the 2-phase pattern.

        Phase 1 — classify `question` intent once (fast model, JSON).
        Phase 2 — per-agent, selectively load required context blocks.
        Phase 3 — per-agent LLM call with composed in-character prompt (fast model).

        Evidence emitted by `_record_evidence` includes the classified intent.
        """
        profiles = (self._sim_data or {}).get("profiles", []) or []
        actions = (self._sim_data or {}).get("actions", []) or []

        if not profiles:
            return json.dumps({"error": "No profiles loaded"}, ensure_ascii=False)
        if not question or len(question.strip()) < 5:
            return json.dumps({"error": "Question quá ngắn hoặc rỗng"}, ensure_ascii=False)

        # Clamp params
        max_agents = max(1, min(20, int(max_agents)))
        sample_pct = max(1, min(100, int(sample_pct)))

        n_total = len(profiles)
        n_sample = max(1, min(max_agents, int(n_total * sample_pct / 100)))

        import random as _rnd
        if stratify_by == "mbti":
            by_mbti: Dict[str, List[dict]] = {}
            for p in profiles:
                by_mbti.setdefault(p.get("mbti", "?"), []).append(p)
            sampled = [_rnd.choice(lst) for lst in by_mbti.values()]
            if len(sampled) > n_sample:
                sampled = _rnd.sample(sampled, n_sample)
        else:
            sampled = _rnd.sample(profiles, min(n_sample, n_total))

        # ── Phase 1: classify intent once per tool call (fast model) ──
        fast_model_name = EcoSimConfig.llm_fast_model_name()
        fast_llm = LLMClient(model=fast_model_name)
        try:
            raw_intent = fast_llm.chat_json(
                messages=[
                    {"role": "system", "content": "Output STRICT JSON only."},
                    {"role": "user", "content": INTENT_CLASSIFIER_PROMPT.format(
                        question=question[:500],
                    )},
                ],
                temperature=0.1,
                max_tokens=150,
            )
            intent_name = str(raw_intent.get("intent", "general")).strip().lower()
            if intent_name not in INTERVIEW_INTENTS:
                intent_name = "general"
            intent_data = {
                "intent": intent_name,
                "confidence": float(raw_intent.get("confidence", 0.5) or 0.5),
                "language": (raw_intent.get("language") or "vi").strip().lower()[:2],
                "needs_specific_topic": bool(raw_intent.get("needs_specific_topic", False)),
                "topic_hint": str(raw_intent.get("topic_hint", "") or "")[:80],
            }
        except Exception as e:
            logger.warning("interview_agents intent classify failed: %s", e)
            intent_data = {
                "intent": "general", "confidence": 0.0, "language": "vi",
                "needs_specific_topic": False, "topic_hint": "",
            }

        required_blocks = INTENT_INFO_MAP.get(
            intent_data["intent"], INTENT_INFO_MAP["general"]
        )
        topic_hint = intent_data.get("topic_hint", "")

        # Actions-by-agent map (used to synthesize trace_timeline when profile lacks it)
        actions_by_agent: Dict = {}
        for a in actions:
            uid = a.get("user_id")
            if uid is not None:
                actions_by_agent.setdefault(uid, []).append(a)

        responses: List[Dict] = []
        for p in sampled:
            aid = p.get("agent_id")
            if aid is None:
                try:
                    aid = profiles.index(p)
                except ValueError:
                    aid = -1
            name = self._get_profile_name(p)

            # Ensure recent_actions loader has something to show even if profile
            # didn't carry sim_actions.trace_timeline (Report path loads profiles
            # from profiles.json which may predate enrichment).
            if not p.get("sim_actions"):
                trace = []
                for a in actions_by_agent.get(aid, [])[-10:]:
                    trace.append({
                        "round": a.get("round", "?"),
                        "action": a.get("action_type", ""),
                        "detail": (self._extract_content(a) or "")[:120],
                    })
                p = {**p, "sim_actions": {"trace_timeline": trace}}

            # Phase 2: load selective context blocks (topic-filtered)
            context_blocks = load_context_blocks(
                p, required_blocks,
                loaders_registry=BUILTIN_LOADERS,
                topic_hint=topic_hint,
            )

            # Phase 3: compose in-character prompt + fast-model call
            system_prompt = build_response_prompt(p, intent_data, context_blocks)

            try:
                answer = fast_llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    temperature=0.7,
                    max_tokens=220,
                )
                if answer and len(answer.strip()) >= 5:
                    responses.append({
                        "agent_id": aid,
                        "agent_name": name,
                        "mbti": p.get("mbti", "?"),
                        "age": p.get("age"),
                        "gender": p.get("gender"),
                        "answer": answer.strip(),
                    })
            except Exception as e:
                logger.warning("Interview agent %s failed: %s", aid, e)

        # Simple word-freq themes
        import re as _re
        all_words = _re.findall(
            r"[A-Za-zÀ-ỹ]{4,}",
            " ".join(r["answer"] for r in responses).lower(),
        )
        stop = {
            "the", "và", "là", "của", "cho", "các", "này", "đã", "được", "với",
            "những", "không", "rất", "cũng", "mình", "tôi", "that", "this",
            "have", "with", "for",
        }
        themes = [
            w for w, _c in Counter(w for w in all_words if w not in stop).most_common(5)
        ]

        return json.dumps({
            "question": question,
            "sample_size": len(responses),
            "total_agents": n_total,
            "sample_pct": sample_pct,
            "stratify_by": stratify_by,
            "intent": intent_data["intent"],
            "intent_confidence": intent_data["confidence"],
            "language": intent_data["language"],
            "context_blocks_loaded": required_blocks,
            "model_used": fast_model_name,
            "responses": responses,
            "themes": themes,
        }, ensure_ascii=False, indent=1)[:3500]

    # ── Preflight dependency check (Tier B+ redesign) ──

    def _auto_run_sentiment(self, sim_dir: str, num_rounds: int = 1) -> bool:
        """Auto-invoke sentiment_analyzer.CampaignReportGenerator.generate_full_report.

        Chạy trong preflight nếu `analysis_results.json` chưa có và
        `auto_run_sentiment=true`. Dùng local RoBERTa — zero LLM API cost cho
        sentiment scoring.

        Returns True nếu thành công (file đã được ghi), False nếu fail.
        """
        db_candidates = [
            os.path.join(sim_dir, "oasis_simulation.db"),
            os.path.join(sim_dir, "sim.db"),
            os.path.join(sim_dir, "simulation.db"),
        ]
        db_path = next((p for p in db_candidates if os.path.exists(p)), None)
        if not db_path:
            logger.warning("Auto-sentiment skipped: no DB found in %s", sim_dir)
            return False

        actions_path = os.path.join(sim_dir, "actions.jsonl")
        if not os.path.exists(actions_path):
            actions_path = None  # sentiment analyzer handles None

        try:
            # Import sentiment_analyzer từ Sim service path
            # Core venv không có sentiment_analyzer → add vendored path tạm thời
            _sim_path = os.path.join(Config.BASE_DIR, "apps", "simulation") \
                if hasattr(Config, "BASE_DIR") else None
            if _sim_path and _sim_path not in sys.path:
                sys.path.insert(0, _sim_path)

            from sentiment_analyzer import CampaignReportGenerator  # type: ignore
            gen = CampaignReportGenerator(db_path, actions_path)
            result = gen.generate_full_report(num_rounds=num_rounds)

            # Mirror format của Sim's _save_analysis_to_dir
            import time as _time
            from datetime import datetime as _dt
            wrapper = {
                "timestamp": _dt.now().isoformat(),
                "results": result,
            }
            out_path = os.path.join(sim_dir, "analysis_results.json")
            atomic_write_json(out_path, wrapper)
            logger.info("Auto-sentiment succeeded → %s", out_path)
            return True
        except ImportError as e:
            logger.warning("Auto-sentiment skipped: sentiment_analyzer not importable from Core: %s", e)
            return False
        except Exception as e:
            logger.warning("Auto-sentiment failed: %s", e)
            return False

    def _preflight_deps(
        self,
        sim_dir: str,
        auto_run_sentiment: bool = True,
        auto_run_survey: bool = False,
        survey_id: str = "",
    ) -> Dict[str, str]:
        """Check + optionally auto-run Sentiment + Survey trước khi Report chạy ReACT.

        Returns:
            dict status {sentiment, survey}:
                - "cached" — file có sẵn
                - "auto_generated" — vừa auto-run OK
                - "missing" — không có và không auto-run
                - "failed:<reason>" — auto-run fail
        """
        deps: Dict[str, str] = {"sentiment": "missing", "survey": "missing"}

        # Sentiment
        sent_path = os.path.join(sim_dir, "analysis_results.json")
        if os.path.exists(sent_path):
            deps["sentiment"] = "cached"
        elif auto_run_sentiment:
            if self._auto_run_sentiment(sim_dir):
                deps["sentiment"] = "auto_generated"
            else:
                deps["sentiment"] = "failed:auto_run_unavailable"

        # Survey — check by specific id or latest
        if survey_id:
            sfile = os.path.join(sim_dir, f"{survey_id}.json")
            if os.path.exists(sfile):
                deps["survey"] = "cached"
        else:
            if self._find_latest_survey_file(sim_dir):
                deps["survey"] = "cached"
        # auto_run_survey=true không tự chạy trong session này — chỉ log.
        # (Cost cao, user explicit opt-in qua endpoint /api/survey/generate-questions + /create + /conduct)
        if deps["survey"] == "missing" and auto_run_survey:
            deps["survey"] = "skipped:auto_run_survey_not_implemented"

        return deps

    def _compute_sentiment(self, meaningful: List[Dict]) -> Dict:
        content_items = []
        for a in meaningful:
            content = a.get("content", "")
            if not content:
                continue
            content_items.append({
                "agent": a.get("agent_name", "?"), "type": a.get("action_type", ""),
                "content": content[:200], "round": self._get_action_round(a),
            })
        if not content_items:
            return {"error": "No content to analyze"}

        batch = content_items[:20]
        batch_text = "\n".join([
            f'{i+1}. [{it["type"]}] {it["agent"]}: "{it["content"]}"'
            for i, it in enumerate(batch)
        ])
        try:
            result = self.llm.chat_json(messages=[{"role": "user", "content":
                f'Analyze sentiment of each item. Return JSON array: '
                f'[{{"index": 1, "sentiment": "positive|negative|neutral", "reason": "lý do"}}]\n\n'
                f'Items:\n{batch_text}\n\nReturn ONLY the JSON array.'}],
                temperature=0.1, max_tokens=2000)
            sentiments = result if isinstance(result, list) else result.get("results", [])
        except Exception:
            sentiments = []

        counts = Counter(s.get("sentiment", "neutral") for s in sentiments if isinstance(s, dict))
        return {
            "total_analyzed": len(batch), "total_content": len(content_items),
            "aggregate": {"positive": counts.get("positive", 0),
                          "negative": counts.get("negative", 0),
                          "neutral": counts.get("neutral", 0)},
            "details": sentiments[:10],
        }

    # ── Evidence extraction ──

    def _record_evidence(self, tool_name: str, params: Dict, result_str: str) -> List[EvidenceItem]:
        """Extract key facts từ tool output → EvidenceStore. Trả về items added.

        Mỗi tool có chiến lược extract riêng. Tránh ghi evidence mass-produce —
        chỉ các facts đáng cite (post_id, KPI verdict, cohort number...).
        """
        added: List[EvidenceItem] = []
        try:
            data = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            return added
        if not isinstance(data, dict):
            return added

        if tool_name == "kpi_check":
            for row in data.get("kpi_scores", [])[:8]:
                if not isinstance(row, dict):
                    continue
                is_measurable = row.get("measurable", True)
                verdict = row.get("verdict", "?")
                kpi_text = row.get("kpi", "?")
                if not is_measurable:
                    # Highlight rõ để LLM không bịa số cho KPI này
                    reason = row.get("unmeasurable_reason", "unknown")
                    added.append(self._evidence.add(
                        source="SPEC",
                        summary=(
                            f"KPI UNMEASURABLE '{kpi_text}' — sim không trace "
                            f"[{reason}]. Không bịa số; chỉ ghi 'cần external data'."
                        ),
                        ref=f"unmeasurable=true, reason={reason}",
                        raw=row,
                    ))
                else:
                    added.append(self._evidence.add(
                        source="SPEC",
                        summary=f"KPI '{kpi_text}' → {verdict}: {row.get('note', '')}",
                        ref=f"observed={row.get('observed', 'N/A')}, measurable=true",
                        raw=row,
                    ))
            obs = data.get("observed_metrics", {})
            if obs:
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Engagement metrics: {obs.get('total_posts', 0)} posts, "
                             f"{obs.get('total_comments', 0)} comments, "
                             f"{obs.get('total_likes', 0)} likes, "
                             f"participation {obs.get('participation_pct', 0)}%"),
                    ref=f"active_agents={obs.get('active_agents', 0)}/{obs.get('total_agents', 0)}",
                    raw=obs,
                ))

        elif tool_name == "influencer_detection":
            for it in data.get("top_influencers", [])[:3]:
                if not isinstance(it, dict):
                    continue
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Influencer: {it.get('name')} ({it.get('mbti')}), "
                             f"score={it.get('influencer_score')}, "
                             f"followers={it.get('followers')}, "
                             f"posts={it.get('posts')}, likes received={it.get('likes_received')}"),
                    ref=f"agent_id={it.get('agent_id')}",
                    raw=it,
                ))

        elif tool_name == "topic_cluster":
            for t in data.get("topics", [])[:5]:
                if not isinstance(t, dict):
                    continue
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Topic '{t.get('topic')}': {t.get('doc_count')} docs, "
                             f"relevance={t.get('relevance')}, rounds={t.get('rounds')}"),
                    ref=f"round_distribution={t.get('round_distribution')}",
                    raw=t,
                ))

        elif tool_name == "crisis_impact_timeline":
            for c in data.get("crises", [])[:3]:
                if not isinstance(c, dict):
                    continue
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Crisis '{c.get('title')}' @ round {c.get('trigger_round')}: "
                             f"engagement {c.get('pre_engagement_rate')} → {c.get('post_engagement_rate')} "
                             f"({c.get('engagement_change_pct')}%)"),
                    ref=f"crisis_id={c.get('crisis_id')}, severity={c.get('severity')}",
                    raw=c,
                ))

        elif tool_name == "agent_cohort_analysis":
            for c in data.get("cohorts", [])[:5]:
                if not isinstance(c, dict):
                    continue
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Cohort '{c.get('cohort')}' ({c.get('agents')} agents): "
                             f"{c.get('posts_per_agent')} posts/agent, "
                             f"{c.get('comments_per_agent')} comments/agent"),
                    ref=f"segment_by={data.get('segment_by')}, total_actions={c.get('total_actions')}",
                    raw=c,
                ))

        elif tool_name == "narrative_quotes":
            for q in data.get("quotes", [])[:5]:
                if not isinstance(q, dict):
                    continue
                added.append(self._evidence.add(
                    source="SIM",
                    summary=f"Quote [{q.get('action_type')}] by {q.get('agent')} @ round {q.get('round')}",
                    quote=q.get("content", ""),
                    ref=f"post_id={q.get('post_id')}, agent_id={q.get('agent_id')}",
                    raw=q,
                ))

        elif tool_name == "sim_data_query":
            aspect = params.get("aspect", "overview")
            if aspect == "overview" and isinstance(data, dict):
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(f"Simulation overview: {data.get('total_actions')} actions, "
                             f"{data.get('total_agents')} agents, {data.get('total_rounds')} rounds. "
                             f"MBTI: {data.get('mbti_distribution')}"),
                    ref="aspect=overview",
                    raw=data,
                ))
            elif aspect == "sentiment":
                agg = data.get("aggregate", {})
                if agg:
                    added.append(self._evidence.add(
                        source="SIM",
                        summary=(f"Sentiment aggregate: +{agg.get('positive', 0)}, "
                                 f"-{agg.get('negative', 0)}, ={agg.get('neutral', 0)} "
                                 f"(n={data.get('total_analyzed', 0)})"),
                        ref="aspect=sentiment",
                        raw=agg,
                    ))
            elif aspect == "timeline":
                tl = data.get("timeline", [])
                if tl:
                    peak = max(tl, key=lambda r: r.get("total", 0))
                    added.append(self._evidence.add(
                        source="SIM",
                        summary=(f"Timeline peak: round {peak.get('round')} "
                                 f"với {peak.get('total')} actions ({peak.get('actions')})"),
                        ref=f"total_rounds={len(tl)}",
                        raw={"peak": peak, "length": len(tl)},
                    ))

        elif tool_name == "graph_overview":
            stats = data.get("graph_stats", {})
            if stats:
                added.append(self._evidence.add(
                    source="KG",
                    summary=f"Knowledge Graph stats: {stats}",
                    ref=f"entities_sampled={len(data.get('entities', []))}, "
                        f"edges_sampled={len(data.get('relationships', []))}",
                    raw=stats,
                ))

        elif tool_name == "sentiment_result":
            if "error" not in data:
                dist = data.get("distribution", {}) or {}
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(
                        f"Sentiment aggregate: +{dist.get('positive', 0)} / "
                        f"={dist.get('neutral', 0)} / -{dist.get('negative', 0)} "
                        f"(NSS={data.get('nss')}, n={data.get('total_comments')} comments). "
                        f"Engagement rating: {data.get('engagement_rating', 'N/A')}. "
                        f"Campaign score: {data.get('campaign_score')} ({data.get('campaign_rating', 'N/A')})."
                    ),
                    ref=f"sentiment=aggregate, model={data.get('model', 'local-roberta')}",
                    raw={"distribution": dist, "nss": data.get("nss")},
                ))
                # Timeline peak nếu có
                pr = data.get("per_round") or []
                if pr:
                    peak = max(pr, key=lambda r: (r.get("nss") or 0))
                    added.append(self._evidence.add(
                        source="SIM",
                        summary=(
                            f"Sentiment peak: round {peak.get('round')} với NSS={peak.get('nss')}, "
                            f"{peak.get('posts')} posts / {peak.get('comments')} comments"
                        ),
                        ref=f"sentiment=per_round_peak, rounds_tracked={len(pr)}",
                        raw=peak,
                    ))
                # Top positive/negative samples
                for sign, items in [("positive", data.get("top_positive") or []),
                                     ("negative", data.get("top_negative") or [])]:
                    for item in items[:2]:
                        content = (item.get("content") or "")[:180]
                        if content:
                            added.append(self._evidence.add(
                                source="SIM",
                                summary=f"Top {sign} comment (score={item.get('score')})",
                                quote=content,
                                ref=f"sentiment={sign}, comment_id={item.get('comment_id')}",
                                raw=item,
                            ))

        elif tool_name == "interview_agents":
            if "error" not in data:
                q = data.get("question", "")
                sample = data.get("sample_size", 0)
                total = data.get("total_agents", 0)
                intent_tag = data.get("intent", "general")
                added.append(self._evidence.add(
                    source="MEM",
                    summary=(
                        f"Interview {sample}/{total} agents (sample_pct={data.get('sample_pct', '?')}%, "
                        f"stratify={data.get('stratify_by', '?')}, intent={intent_tag}): '{q[:100]}'. "
                        f"Themes: {', '.join((data.get('themes') or [])[:5]) or '(none)'}"
                    ),
                    ref=(
                        f"interview_question='{q[:80]}', intent={intent_tag}, "
                        f"model={data.get('model_used', '?')}"
                    ),
                    raw={
                        "themes": data.get("themes"),
                        "sample_size": sample,
                        "intent": intent_tag,
                        "context_blocks_loaded": data.get("context_blocks_loaded"),
                    },
                ))
                for r in (data.get("responses") or [])[:3]:
                    answer = r.get("answer", "")
                    if not answer:
                        continue
                    added.append(self._evidence.add(
                        source="MEM",
                        summary=(
                            f"Interview reply by {r.get('agent_name')} "
                            f"({r.get('mbti', '?')}) — intent={intent_tag}"
                        ),
                        quote=answer,
                        ref=(
                            f"agent_id={r.get('agent_id')}, "
                            f"question='{q[:60]}', intent={intent_tag}"
                        ),
                        raw=r,
                    ))

        elif tool_name == "survey_result":
            if "error" not in data:
                sid = data.get("survey_id", "?")
                n_resp = data.get("total_respondents", 0)
                added.append(self._evidence.add(
                    source="SIM",
                    summary=(
                        f"Survey '{sid}' — {n_resp} respondents, "
                        f"{data.get('question_count', 0)} questions"
                    ),
                    ref=f"survey={sid}, sim_id={data.get('sim_id', '?')}",
                    raw={"survey_id": sid, "respondents": n_resp},
                ))
                # 1 evidence per notable question (up to 5)
                for q in (data.get("questions") or [])[:5]:
                    q_text = (q.get("text") or "")[:120]
                    if not q_text:
                        continue
                    q_type = q.get("type", "")
                    q_section = q.get("report_section") or "general"
                    if q_type in ("scale_1_10", "rating") and q.get("average") is not None:
                        summary = f"Q '{q_text}' — average {q['average']}/10 [section={q_section}]"
                    elif q.get("distribution"):
                        top = max(q["distribution"].items(), key=lambda kv: kv[1]) if q["distribution"] else ("N/A", 0)
                        summary = f"Q '{q_text}' — top response: '{top[0]}' ({top[1]}) [section={q_section}]"
                    elif q.get("key_themes"):
                        summary = f"Q '{q_text}' — themes: {', '.join(q['key_themes'][:3])} [section={q_section}]"
                    else:
                        summary = f"Q '{q_text}' — {q.get('response_count', 0)} responses [section={q_section}]"
                    added.append(self._evidence.add(
                        source="SIM",
                        summary=summary,
                        ref=(
                            f"survey={sid}, category={q.get('category', 'general')}, "
                            f"type={q_type}, report_section={q_section}"
                        ),
                        raw=q,
                    ))

        return added

    # ── Tool Call Parsing ──

    def _parse_tool_calls(self, response: str) -> List[Dict]:
        """Parse tool calls from LLM response. Priority: XML tags → bare JSON."""
        import re
        calls = []

        # Priority 1: XML tags
        xml_matches = re.findall(r'<tool_call>(.*?)</tool_call>', response, re.DOTALL)
        for match in xml_matches:
            try:
                tc = json.loads(match.strip())
                if self._is_valid_tool_call(tc):
                    calls.append(tc)
            except json.JSONDecodeError:
                pass
        if calls:
            return calls

        # Priority 2: Bare JSON with name+parameters
        json_pattern = r'\{[^{}]*"name"\s*:\s*"[^"]+"\s*,\s*"parameters"\s*:\s*\{[^{}]*\}[^{}]*\}'
        for match in re.finditer(json_pattern, response):
            try:
                tc = json.loads(match.group())
                if self._is_valid_tool_call(tc):
                    calls.append(tc)
            except json.JSONDecodeError:
                pass

        return calls

    def _is_valid_tool_call(self, tc: Dict) -> bool:
        name = tc.get("name", tc.get("tool", ""))
        if name not in self.TOOL_DEFS:
            return False
        if "tool" in tc and "name" not in tc:
            tc["name"] = tc.pop("tool")
        if "params" in tc and "parameters" not in tc:
            tc["parameters"] = tc.pop("params")
        tc.setdefault("parameters", {})
        return True

    def _parse_final_answer(self, response: str) -> Optional[str]:
        """Extract content from <final_answer>...</final_answer>."""
        import re
        match = re.search(r'<final_answer>(.*?)</final_answer>', response, re.DOTALL)
        return match.group(1).strip() if match else None

    # ── Planning Phase ──

    def plan_outline(self, progress_cb: Optional[Callable] = None) -> ReportOutline:
        """LLM plans 3-5 section outline."""
        gq = self._get_graph_query()
        graph_stats = gq.get_graph_stats()

        sim_overview = {}
        if self._sim_data:
            actions = self._sim_data.get("actions", [])
            meaningful = [a for a in actions
                          if a.get("action_type", "").lower() not in ("trace", "sign_up", "do_nothing")]
            sim_overview = {
                "total_actions": len(meaningful),
                "total_agents": len(self._sim_data.get("profiles", [])),
                "action_types": dict(Counter(a.get("action_type", "") for a in meaningful)),
            }

        spec = self._campaign_spec or {}
        prompt = PLAN_USER_PROMPT.format(
            campaign_name=spec.get("name", "Unknown Campaign"),
            campaign_type=spec.get("campaign_type", "other"),
            market=spec.get("market", "N/A"),
            kpis=json.dumps(spec.get("kpis", []), ensure_ascii=False),
            risks=json.dumps(spec.get("identified_risks", []), ensure_ascii=False),
            graph_stats=json.dumps(graph_stats, ensure_ascii=False, default=str),
            sim_overview=json.dumps(sim_overview, ensure_ascii=False, default=str),
        )

        if self._report_logger:
            self._report_logger.log("planning_start", graph_stats=graph_stats)

        try:
            result = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3, max_tokens=2000,
            )
            sections = [ReportSection(title=s["title"], description=s.get("description", ""))
                        for s in result.get("sections", [])]
            outline = ReportOutline(
                title=result.get("title", "Báo Cáo Phân Tích Chiến Dịch"),
                summary=result.get("summary", ""), sections=sections,
            )
        except Exception as e:
            logger.warning(f"Planning failed, using default outline: {e}")
            outline = self._default_outline()

        if len(outline.sections) < 2:
            outline = self._default_outline()

        if self._report_logger:
            self._report_logger.log("planning_complete", outline=outline.to_dict())
        if progress_cb:
            progress_cb("planning_complete", outline.to_dict())

        return outline

    def _default_outline(self) -> ReportOutline:
        spec = self._campaign_spec or {}
        campaign_name = spec.get("name", "Chiến Dịch")
        return ReportOutline(
            title=f"Báo Cáo Phân Tích: {campaign_name}",
            summary="Báo cáo dự báo dựa trên mô phỏng đa tác tử — executive summary + diễn biến + KPI + biến cố + khuyến nghị",
            sections=[
                ReportSection(
                    "Executive Summary",
                    "3-5 findings quan trọng nhất: verdict tổng thể, KPI chính, rủi ro nổi bật, hành động ưu tiên",
                ),
                ReportSection(
                    "Bối Cảnh & Đối Tượng Tham Gia",
                    "Campaign context, stakeholders, phân bố cohorts (MBTI / follower tier / domain), "
                    "profile agents điển hình. Dùng tool: graph_overview, sim_data_query(aspect=overview), agent_cohort_analysis",
                ),
                ReportSection(
                    "Diễn Biến & Nội Dung Chính",
                    "Timeline action volume, topic cluster (share of voice), 5-10 quotes tiêu biểu có post_id. "
                    "Cân nhắc dùng interview_agents(question=\"Điều gì khiến bạn post về X?\", sample_pct=20) "
                    "để lấy voice-of-agent giải thích động lực content. "
                    "Dùng tool: sim_data_query(aspect=timeline), topic_cluster, narrative_quotes, interview_agents",
                ),
                ReportSection(
                    "Đánh Giá KPI & Engagement",
                    "So sánh từng KPI target vs observed, influencer detection top-5, engagement funnel. "
                    "Dùng tool: kpi_check, influencer_detection, sim_data_query(aspect=actions)",
                ),
                ReportSection(
                    "Khảo Sát & Phản Hồi Thị Trường",
                    "Kết quả survey grouped by report_section + phân bố sentiment toàn sim + "
                    "per-round timeline + tác động biến cố pre/post. Bổ sung interview_agents "
                    "(sample_pct=20, stratify_by=\"mbti\") để lấy voice-of-agent cho crisis reaction hoặc attribution. "
                    "Dùng tool: sentiment_result, survey_result, interview_agents, crisis_impact_timeline",
                ),
                ReportSection(
                    "Khuyến Nghị Chiến Lược",
                    "Action items cụ thể theo priority (cao/trung/thấp), rủi ro residual, đề xuất tuning config sim. "
                    "Tổng hợp từ các section trước, không cần tool mới",
                ),
            ],
        )

    # ── ReACT Loop (per section) ──

    def _generate_section_react(
        self, section: ReportSection, outline: ReportOutline,
        previous_sections: List[ReportSection], section_idx: int,
        progress_cb: Optional[Callable] = None,
    ) -> str:
        """ReACT loop: Thought → Tool → Observation → ... → FinalAnswer."""
        tool_desc = "\n".join([f"- {name}: {desc}" for name, desc in self.TOOL_DEFS.items()])
        prev_text = "\n---\n".join([
            f"**{s.title}**: {s.content[:2000]}" for s in previous_sections
        ]) or "(Chưa có section nào)"

        messages = [
            {"role": "system", "content": SECTION_SYSTEM_PROMPT.format(
                sim_capabilities=SIM_DATA_CAPABILITIES,
                tool_count=len(self.TOOL_DEFS),
                tool_descriptions=tool_desc,
            )},
            {"role": "user", "content": SECTION_USER_PROMPT.format(
                section_title=section.title, section_description=section.description,
                previous_sections=prev_text)},
        ]

        tool_calls_count = 0
        used_tools = set()
        conflict_retries = 0

        for iteration in range(self.MAX_ITERATIONS):
            if self._report_logger:
                self._report_logger.log("react_iteration", section=section.title,
                                        iteration=iteration, tools_used=tool_calls_count)

            response = self.llm.chat(messages, temperature=0.4, max_tokens=3000)
            if not response:
                continue

            tool_calls = self._parse_tool_calls(response)
            final_answer = self._parse_final_answer(response)

            # Case 1: Both tool call AND final answer (conflict)
            if tool_calls and final_answer:
                conflict_retries += 1
                if conflict_retries >= 3:
                    # Accept final answer after 3 conflicts
                    if tool_calls_count >= self.MIN_TOOL_CALLS:
                        return self._finalize_section_content(
                            section, final_answer, tool_calls_count
                        )
                    # Execute tool instead
                    final_answer = None
                else:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content":
                        "Bạn đang gửi cả tool_call lẫn final_answer. Chọn MỘT: "
                        "gọi tool HOẶC viết final_answer."})
                    continue

            # Case 2: Final answer only
            if final_answer and not tool_calls:
                if tool_calls_count < self.MIN_TOOL_CALLS:
                    messages.append({"role": "assistant", "content": response})
                    available = ", ".join(self.TOOL_DEFS.keys() - used_tools)
                    messages.append({"role": "user", "content":
                        REACT_INSUFFICIENT_TOOLS.format(
                            used=tool_calls_count, min_required=self.MIN_TOOL_CALLS,
                            available_tools=available)})
                    continue
                return self._finalize_section_content(
                    section, final_answer, tool_calls_count
                )

            # Case 3: Tool call
            if tool_calls:
                tc = tool_calls[0]  # Execute one at a time
                tool_name = tc["name"]

                if tool_calls_count >= self.MAX_TOOL_CALLS:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content":
                        REACT_TOOL_LIMIT.format(max=self.MAX_TOOL_CALLS)})
                    continue

                # Execute tool
                if self._report_logger:
                    self._report_logger.log("tool_call", tool=tool_name, params=tc.get("parameters", {}))

                params = tc.get("parameters", {})
                result = self._execute_tool(tool_name, params)
                tool_calls_count += 1
                used_tools.add(tool_name)

                # Extract evidence + record → anchors để LLM cite
                new_ev = self._record_evidence(tool_name, params, result)
                anchors = self._evidence.render_anchors(new_ev) if new_ev else "(none)"
                for it in new_ev:
                    section.evidence_refs.append(it.evidence_id)

                if self._report_logger:
                    self._report_logger.log(
                        "tool_result", tool=tool_name,
                        result_len=len(result), evidence_added=[it.evidence_id for it in new_ev],
                    )
                if progress_cb:
                    progress_cb("tool_call", {"section": section.title, "tool": tool_name,
                                              "count": tool_calls_count})

                unused = list(self.TOOL_DEFS.keys() - used_tools)
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content":
                    REACT_OBSERVATION.format(
                        tool_name=tool_name, used=tool_calls_count,
                        max=self.MAX_TOOL_CALLS, result=result[:2500],
                        evidence_anchors=anchors,
                        unused_tools=", ".join(unused) if unused else "Không còn")})
                continue

            # Case 4: Neither tool call nor final answer
            if tool_calls_count >= self.MIN_TOOL_CALLS:
                # Adopt response as content
                return self._finalize_section_content(
                    section, response, tool_calls_count
                )
            else:
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content":
                    REACT_INSUFFICIENT_TOOLS.format(
                        used=tool_calls_count, min_required=self.MIN_TOOL_CALLS,
                        available_tools=", ".join(self.TOOL_DEFS.keys()))})

        # Max iterations reached — force
        messages.append({"role": "user", "content": REACT_FORCE_FINAL})
        response = self.llm.chat(messages, temperature=0.3, max_tokens=3000)
        final = self._parse_final_answer(response) if response else None
        fallback = final or response or f"[Không thể tạo nội dung cho section: {section.title}]"
        return self._finalize_section_content(section, fallback, tool_calls_count)

    # ── Main Orchestrator ──

    def generate(
        self, sim_id: str, campaign_id: str = "",
        auto_run_sentiment: bool = True,
        auto_run_survey: bool = False,
        survey_id: str = "",
        progress_cb: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Main entry: preflight → plan → per-section ReACT → assemble → save.

        Tier B+ redesign:
        - `auto_run_sentiment` (default True): nếu `analysis_results.json` chưa có
          → auto-invoke `CampaignReportGenerator.generate_full_report(num_rounds=1)`.
          Local RoBERTa → no API cost.
        - `auto_run_survey` (default False): explicit opt-in vì cost cao
          (N_agents × N_questions LLM calls). Hiện chưa auto-run — chỉ log warning
          nếu thiếu.
        - `survey_id`: pin specific survey. Empty → Report pick latest.
        """
        report_id = str(uuid.uuid4())[:8]
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        report_dir = os.path.join(sim_dir, "report")
        os.makedirs(report_dir, exist_ok=True)

        # Init logger
        self._report_logger = ReportLogger(
            os.path.join(report_dir, "agent_log.jsonl"), report_id)
        self._report_logger.log("report_start", sim_id=sim_id, campaign_id=campaign_id)

        # Reset EvidenceStore cho report run mới
        self._evidence = EvidenceStore()

        report = Report(report_id=report_id, sim_id=sim_id, status=ReportStatus.PLANNING)

        try:
            # Load data
            self._sim_data = self._load_sim_data(sim_dir)
            self._campaign_spec = self._load_campaign_spec(campaign_id)

            # Phase 0: Preflight dependency check (Tier B+ redesign)
            # Auto-run Sentiment nếu thiếu + auto_run_sentiment=true.
            # Survey chỉ check, không auto-run (cost opt-in qua /api/survey/...)
            deps_status = self._preflight_deps(
                sim_dir,
                auto_run_sentiment=auto_run_sentiment,
                auto_run_survey=auto_run_survey,
                survey_id=survey_id,
            )
            self._report_logger.log("preflight_deps", **deps_status)
            # Add preflight status vào EvidenceStore để bibliography minh bạch
            self._evidence.add(
                source="SIM",
                summary=f"Preflight dependencies: sentiment={deps_status['sentiment']}, survey={deps_status['survey']}",
                ref=f"auto_run_sentiment={auto_run_sentiment}, auto_run_survey={auto_run_survey}, survey_id={survey_id or '(latest)'}",
                raw=deps_status,
            )
            # Lưu survey_id để section evidence extraction có thể dùng
            self._preferred_survey_id = survey_id

            # Save progress
            self._save_progress(report_dir, report, "Đang lên kế hoạch...")
            if progress_cb:
                progress_cb("status", {"status": "planning", "deps": deps_status})

            # Phase 1: Plan
            outline = self.plan_outline(progress_cb)
            report.outline = outline
            report.status = ReportStatus.GENERATING

            # Save outline (atomic)
            atomic_write_json(os.path.join(report_dir, "outline.json"), outline.to_dict())

            # Phase 2: Generate each section
            completed_sections = []
            for idx, section in enumerate(outline.sections):
                self._report_logger.log("section_start", index=idx, title=section.title)
                self._save_progress(report_dir, report,
                    f"Đang viết section {idx+1}/{len(outline.sections)}: {section.title}")
                if progress_cb:
                    progress_cb("section_start", {"index": idx, "title": section.title})

                content = self._generate_section_react(
                    section, outline, completed_sections, idx, progress_cb)
                section.content = content
                completed_sections.append(section)

                # Save section file
                section_path = os.path.join(report_dir, f"section_{idx+1:02d}.md")
                with open(section_path, "w", encoding="utf-8") as f:
                    f.write(f"## {section.title}\n\n{content}")

                self._report_logger.log("section_complete", index=idx, title=section.title,
                                        content_len=len(content), tools_used=section.tool_calls_used)

            # Assemble full report
            report.sections = completed_sections
            report.markdown_content = self._assemble_report(outline, completed_sections)
            report.status = ReportStatus.COMPLETED
            report.completed_at = time.time()

            # Save files
            full_path = os.path.join(report_dir, "full_report.md")
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(report.markdown_content)

            # Also save to legacy path for backward compat
            legacy_path = os.path.join(sim_dir, "report.md")
            with open(legacy_path, "w", encoding="utf-8") as f:
                f.write(report.markdown_content)

            # Save evidence artifact (Tier B report redesign)
            atomic_write_json(
                os.path.join(report_dir, "evidence.json"),
                {"items": [e.to_dict() for e in self._evidence.items()]},
            )

            # Save meta
            meta = {
                "report_id": report_id, "sim_id": sim_id, "campaign_id": campaign_id,
                "status": report.status.value,
                "sections_count": len(completed_sections),
                "total_tool_calls": sum(s.tool_calls_used for s in completed_sections),
                "total_evidence": len(self._evidence.items()),
                "evidence_refs_per_section": {
                    s.title: len(s.evidence_refs) for s in completed_sections
                },
                "created_at": report.created_at, "completed_at": report.completed_at,
                "duration_s": round(report.completed_at - report.created_at, 1),
            }
            atomic_write_json(os.path.join(report_dir, "meta.json"), meta)

            self._save_progress(report_dir, report, "Hoàn thành!")
            self._report_logger.log("report_complete", duration_s=meta["duration_s"])

            logger.info(f"Report completed: {report_id} ({meta['duration_s']}s, "
                        f"{meta['total_tool_calls']} tool calls)")

            return {
                "sim_id": sim_id, "campaign_id": campaign_id,
                "report_id": report_id,
                "report_path": full_path,
                "report_length": len(report.markdown_content),
                "sections_count": len(completed_sections),
                "total_tool_calls": meta["total_tool_calls"],
                "total_evidence": meta.get("total_evidence", 0),
                "duration_s": meta["duration_s"],
                "report_md": report.markdown_content,
                "tool_results_summary": {
                    s.title: s.tool_calls_used for s in completed_sections
                },
            }

        except Exception as e:
            report.status = ReportStatus.FAILED
            self._report_logger.log("error", error=str(e))
            self._save_progress(report_dir, report, f"Lỗi: {e}")
            logger.error(f"Report generation failed: {e}", exc_info=True)
            raise
        finally:
            self._report_logger.close()

    def _assemble_report(self, outline: ReportOutline, sections: List[ReportSection]) -> str:
        """Assemble full markdown report from sections, kèm bibliography."""
        spec = self._campaign_spec or {}
        campaign_name = spec.get("name", "Unknown")
        campaign_type = spec.get("campaign_type", "other")
        market = spec.get("market", "N/A")
        timeline = spec.get("timeline", "")

        parts = [f"# Báo Cáo Phân Tích Chiến Dịch: {campaign_name}\n"]
        # Metadata block
        meta_rows = [
            f"- **Loại chiến dịch**: {campaign_type}",
            f"- **Thị trường**: {market}",
        ]
        if timeline:
            meta_rows.append(f"- **Thời gian**: {timeline}")
        if spec.get("kpis"):
            meta_rows.append(f"- **KPI mục tiêu**: {', '.join(spec.get('kpis', [])[:5])}")
        parts.append("\n".join(meta_rows))
        parts.append("")

        if outline.summary:
            parts.append(f"> *{outline.summary}*\n")
        parts.append("---\n")

        for idx, section in enumerate(sections):
            parts.append(f"## {idx+1}. {section.title}\n")
            parts.append(section.content)
            if section.evidence_refs:
                refs = ", ".join(f"EV-{i}" for i in section.evidence_refs)
                parts.append(f"\n<sub>_Evidence references: {refs}_</sub>")
            parts.append("\n\n---\n")

        # Bibliography (Tier B report redesign)
        biblio = self._evidence.bibliography_md()
        if biblio:
            parts.append(biblio)
            parts.append("\n---\n")

        parts.append(
            f"\n*Báo cáo được tạo tự động bởi EcoSim ReACT Agent — "
            f"{sum(s.tool_calls_used for s in sections)} tool calls, "
            f"{len(self._evidence.items())} evidence items*"
        )
        return "\n".join(parts)

    def _save_progress(self, report_dir: str, report: Report, message: str):
        progress = {
            "status": report.status.value, "message": message,
            "sections_total": len(report.outline.sections) if report.outline else 0,
            "sections_completed": len([s for s in (report.outline.sections if report.outline else []) if s.content]),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        atomic_write_json(os.path.join(report_dir, "progress.json"), progress)

    # ── Post-Report Chat ──

    def chat(self, sim_id: str, message: str, chat_history: List[Dict] = None) -> Dict:
        """Post-report interactive Q&A with tool access."""
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        report_path = os.path.join(sim_dir, "report", "full_report.md")
        if not os.path.exists(report_path):
            report_path = os.path.join(sim_dir, "report.md")

        report_content = ""
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()[:15000]

        # Load sim data for tools
        self._sim_data = self._load_sim_data(sim_dir)

        tool_desc = "\n".join([f"- {n}: {d}" for n, d in self.TOOL_DEFS.items()])
        system = CHAT_SYSTEM_PROMPT.format(
            report_content=report_content, tool_descriptions=tool_desc)

        messages = [{"role": "system", "content": system}]
        if chat_history:
            messages.extend(chat_history[-10:])
        messages.append({"role": "user", "content": message})

        # Simple ReACT-lite (max 2 tool calls)
        tool_calls_made = []
        for _ in range(self.MAX_CHAT_TOOLS + 1):
            response = self.llm.chat(messages, temperature=0.3, max_tokens=2000)
            if not response:
                break

            tool_calls = self._parse_tool_calls(response)
            final = self._parse_final_answer(response)

            if final:
                return {"response": final, "tool_calls": tool_calls_made}

            if tool_calls and len(tool_calls_made) < self.MAX_CHAT_TOOLS:
                tc = tool_calls[0]
                result = self._execute_tool(tc["name"], tc.get("parameters", {}))
                tool_calls_made.append(tc["name"])
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"[Tool result]: {result[:2000]}"})
                continue

            return {"response": response, "tool_calls": tool_calls_made}

        return {"response": "Không thể trả lời. Vui lòng thử lại.", "tool_calls": []}

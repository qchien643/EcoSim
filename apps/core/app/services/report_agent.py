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
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ecosim_common.atomic_io import atomic_write_json

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
class ReportSection:
    title: str
    description: str
    content: str = ""
    tool_calls_used: int = 0

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
# PROMPT TEMPLATES (Vietnamese enterprise-grade)
# ═══════════════════════════════════════════════

PLAN_SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích kinh tế với tầm nhìn toàn diện (God's-eye view) về kết quả mô phỏng.
Bạn sẽ lên kế hoạch cho một báo cáo phân tích chiến dịch dựa trên DỮ LIỆU MÔ PHỎNG THỰC TẾ.
Báo cáo này là DỰ BÁO TƯƠNG LAI dựa trên kết quả mô phỏng — KHÔNG phải phân tích tình trạng hiện tại.
"""

PLAN_USER_PROMPT = """\
Dựa trên dữ liệu mô phỏng sau, hãy lên kế hoạch outline cho báo cáo phân tích chiến dịch.

THỐNG KÊ KNOWLEDGE GRAPH:
{graph_stats}

TỔNG QUAN MÔ PHỎNG:
{sim_overview}

YÊU CẦU:
- Tạo outline gồm 3-5 section
- Mỗi section phải có title và description rõ ràng
- Section phải cover: tổng quan, phân tích stakeholders, diễn biến mô phỏng, tác động biến cố, kết luận

Trả về JSON:
{{"title": "...", "summary": "...", "sections": [{{"title": "...", "description": "..."}}]}}
"""

SECTION_SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích kinh tế đang viết MỘT SECTION của báo cáo chiến dịch.

BẠN CÓ 4 CÔNG CỤ THU THẬP DỮ LIỆU:
{tool_descriptions}

QUY TẮC BẮT BUỘC:
1. BẮT BUỘC gọi ít nhất 3 tool trước khi viết nội dung. Nếu viết mà chưa dùng đủ tool, bài sẽ bị TỪ CHỐI.
2. Mọi con số PHẢI có source tag: [SIM] = dữ liệu mô phỏng, [KG] = knowledge graph, [SPEC] = mục tiêu chiến dịch, [CALC] = tính toán.
3. KHÔNG được bịa số liệu. Nếu không có dữ liệu, ghi rõ "Không có dữ liệu".
4. Trích dẫn nguyên văn bài viết của agent khi phân tích nội dung.
5. Phân biệt rõ MỤC TIÊU (từ campaign spec) vs KẾT QUẢ (từ simulation).
6. Viết toàn bộ bằng tiếng Việt.
7. KHÔNG dùng markdown headers (##, ###) — chỉ dùng bold, italic, bullet points.

CÁCH GỌI TOOL:
<tool_call>{{"name": "tool_name", "parameters": {{"key": "value"}}}}</tool_call>

KHI HOÀN THÀNH, ghi:
<final_answer>
[Nội dung section ở đây]
</final_answer>
"""

SECTION_USER_PROMPT = """\
SECTION HIỆN TẠI: {section_title}
MÔ TẢ: {section_description}

CÁC SECTION TRƯỚC ĐÃ VIẾT:
{previous_sections}

Hãy thu thập dữ liệu bằng các tool, sau đó viết nội dung cho section này.
"""

REACT_OBSERVATION = """\
[Observation] Kết quả từ tool "{tool_name}" (tool {used}/{max}):
{result}

Tool chưa dùng: {unused_tools}
Nếu đã thu thập đủ dữ liệu (≥3 tool), hãy viết <final_answer>. Nếu chưa, gọi thêm tool."""

REACT_INSUFFICIENT_TOOLS = """\
[System] Bạn mới chỉ gọi {used}/{min_required} tool. BẮT BUỘC gọi thêm tool để thu thập dữ liệu trước khi viết nội dung.
Tool có sẵn: {available_tools}"""

REACT_TOOL_LIMIT = """\
[System] Đã đạt giới hạn {max}/{max} tool calls. BẮT BUỘC viết <final_answer> ngay bây giờ với dữ liệu đã thu thập."""

REACT_FORCE_FINAL = """\
[System] Đã hết số lần iteration. Viết <final_answer> ngay với dữ liệu hiện có."""

CHAT_SYSTEM_PROMPT = """\
Bạn là trợ lý phân tích kinh tế. Người dùng đang hỏi về báo cáo chiến dịch đã tạo.

NỘI DUNG BÁO CÁO:
{report_content}

Bạn có thể dùng tool để tra cứu thêm:
{tool_descriptions}

Trả lời bằng tiếng Việt, trích dẫn dữ liệu từ báo cáo khi có thể."""


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
    }

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()
        self._graph_query = None
        self._sim_data = None
        self._campaign_spec = None
        self._report_logger = None

    # ── Graph Query helper ──

    def _get_graph_query(self):
        if self._graph_query is None:
            from .graph_query import GraphQuery
            self._graph_query = GraphQuery()
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

        profiles_path = os.path.join(sim_dir, "profiles.csv")
        if os.path.exists(profiles_path):
            import csv
            with open(profiles_path, "r", encoding="utf-8") as f:
                data["profiles"] = list(csv.DictReader(f))

        crisis_path = os.path.join(sim_dir, "crisis_scenarios.json")
        if os.path.exists(crisis_path):
            with open(crisis_path, "r", encoding="utf-8") as f:
                data["crisis"] = json.load(f)

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
                            or config.get("total_rounds", 0))
            result = {
                "total_actions": len(meaningful), "total_agents": len(profiles),
                "total_rounds": total_rounds,
                "agent_names": [p.get("name", "") for p in profiles[:20]],
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
            name_map = {str(i): p.get("name", f"Agent_{i}") for i, p in enumerate(profiles)}
            top = [{"id": aid, "name": name_map.get(aid, f"Agent_{aid}"), "actions": cnt}
                   for aid, cnt in agent_actions.most_common(10)]
            result = {"unique_agents": len(agent_actions), "top_agents": top}
        elif aspect == "content":
            posts, comments = [], []
            for a in meaningful:
                content = a.get("content", "")
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

        prompt = PLAN_USER_PROMPT.format(
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
        return ReportOutline(
            title="Báo Cáo Phân Tích Chiến Dịch",
            summary="Báo cáo phân tích toàn diện dựa trên kết quả mô phỏng",
            sections=[
                ReportSection("Tổng Quan Chiến Dịch & Stakeholders",
                              "Mô tả chiến dịch, KPI mục tiêu, các bên liên quan từ Knowledge Graph"),
                ReportSection("Diễn Biến Mô Phỏng & Phân Tích Nội Dung",
                              "Timeline hoạt động, phân bổ hành vi, nội dung bài viết tiêu biểu"),
                ReportSection("Tác Động Biến Cố & Phân Tích Sentiment",
                              "So sánh trước/sau biến cố, phân tích tâm lý thị trường"),
                ReportSection("Đánh Giá Hiệu Quả & Khuyến Nghị",
                              "So sánh kết quả vs mục tiêu, rủi ro, đề xuất cải thiện"),
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
            {"role": "system", "content": SECTION_SYSTEM_PROMPT.format(tool_descriptions=tool_desc)},
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
                        section.tool_calls_used = tool_calls_count
                        return final_answer
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
                section.tool_calls_used = tool_calls_count
                return final_answer

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

                result = self._execute_tool(tool_name, tc.get("parameters", {}))
                tool_calls_count += 1
                used_tools.add(tool_name)

                if self._report_logger:
                    self._report_logger.log("tool_result", tool=tool_name, result_len=len(result))
                if progress_cb:
                    progress_cb("tool_call", {"section": section.title, "tool": tool_name,
                                              "count": tool_calls_count})

                unused = list(self.TOOL_DEFS.keys() - used_tools)
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content":
                    REACT_OBSERVATION.format(
                        tool_name=tool_name, used=tool_calls_count,
                        max=self.MAX_TOOL_CALLS, result=result[:2500],
                        unused_tools=", ".join(unused) if unused else "Không còn")})
                continue

            # Case 4: Neither tool call nor final answer
            if tool_calls_count >= self.MIN_TOOL_CALLS:
                # Adopt response as content
                section.tool_calls_used = tool_calls_count
                return response
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
        section.tool_calls_used = tool_calls_count
        return final or response or f"[Không thể tạo nội dung cho section: {section.title}]"

    # ── Main Orchestrator ──

    def generate(
        self, sim_id: str, campaign_id: str = "",
        progress_cb: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Main entry: plan → per-section ReACT → assemble → save."""
        report_id = str(uuid.uuid4())[:8]
        sim_dir = os.path.join(Config.SIM_DIR, sim_id)
        report_dir = os.path.join(sim_dir, "report")
        os.makedirs(report_dir, exist_ok=True)

        # Init logger
        self._report_logger = ReportLogger(
            os.path.join(report_dir, "agent_log.jsonl"), report_id)
        self._report_logger.log("report_start", sim_id=sim_id, campaign_id=campaign_id)

        report = Report(report_id=report_id, sim_id=sim_id, status=ReportStatus.PLANNING)

        try:
            # Load data
            self._sim_data = self._load_sim_data(sim_dir)
            self._campaign_spec = self._load_campaign_spec(campaign_id)

            # Save progress
            self._save_progress(report_dir, report, "Đang lên kế hoạch...")
            if progress_cb:
                progress_cb("status", {"status": "planning"})

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

            # Save meta
            meta = {
                "report_id": report_id, "sim_id": sim_id, "campaign_id": campaign_id,
                "status": report.status.value,
                "sections_count": len(completed_sections),
                "total_tool_calls": sum(s.tool_calls_used for s in completed_sections),
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
        """Assemble full markdown report from sections."""
        campaign_name = self._campaign_spec.get("name", "Unknown") if self._campaign_spec else "Unknown"
        parts = [f"# Báo Cáo Phân Tích Chiến Dịch: {campaign_name}\n"]
        if outline.summary:
            parts.append(f"*{outline.summary}*\n")
        parts.append("---\n")
        for idx, section in enumerate(sections):
            parts.append(f"## {idx+1}. {section.title}\n")
            parts.append(section.content)
            parts.append("\n\n---\n")
        parts.append(f"\n*Báo cáo được tạo tự động bởi EcoSim ReACT Agent*\n"
                     f"*Tổng tool calls: {sum(s.tool_calls_used for s in sections)}*")
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

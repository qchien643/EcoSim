"""
Interview API — Post-simulation agent interview chat.

Endpoints:
  GET  /api/interview/agents    — List agents with simulation stats
  POST /api/interview/chat      — Chat with an agent (context-aware)
  GET  /api/interview/history   — Get chat history for an agent
  GET  /api/interview/profile   — Get full system prompt + context for an agent
"""
import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("sim-svc.interview")

router = APIRouter(prefix="/api/interview", tags=["Interview"])

# ── Config ──
ECOSIM_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIM_DIR = os.path.join(ECOSIM_ROOT, "data", "simulations")
FALKOR_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKOR_PORT = int(os.getenv("FALKORDB_PORT", "6379"))

# ── In-memory chat history (per session) ──
_chat_histories: Dict[str, List[dict]] = {}

# ── Cache for LLM-summarized graph data (per agent) ──
_graph_summaries: Dict[str, str] = {}


# ── Request / Response Models ──
class ChatRequest(BaseModel):
    sim_id: str
    agent_id: int
    message: str
    history: List[dict] = []


# ══════════════════════════════════════════════════════════════════
# DATA EXTRACTION
# ══════════════════════════════════════════════════════════════════

def _get_db_path(sim_id: str) -> str:
    return os.path.join(SIM_DIR, sim_id, "oasis_simulation.db")


def _get_profiles(sim_id: str) -> list:
    profiles_path = os.path.join(SIM_DIR, sim_id, "profiles.json")
    if not os.path.exists(profiles_path):
        return []
    with open(profiles_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_agent_stats(sim_id: str, user_id: int) -> dict:
    """Quick stats for agent listing."""
    db_path = _get_db_path(sim_id)
    if not os.path.exists(db_path):
        return {"posts": 0, "comments": 0, "likes": 0, "dislikes": 0}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    stats = {}
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        for tbl, key in [("post", "posts"), ("comment", "comments"), ("dislike", "dislikes")]:
            if tbl in tables:
                cur.execute(f"SELECT count(*) FROM [{tbl}] WHERE user_id=?", (user_id,))
                stats[key] = cur.fetchone()[0]
            else:
                stats[key] = 0

        if "like" in tables:
            cur.execute("SELECT count(*) FROM [like] WHERE user_id=?", (user_id,))
            stats["likes"] = cur.fetchone()[0]
        else:
            stats["likes"] = 0
    finally:
        conn.close()
    return stats


def _get_agent_actions(sim_id: str, user_id: int) -> dict:
    """Extract all agent actions from simulation DB."""
    db_path = _get_db_path(sim_id)
    empty = {"posts": [], "comments": [], "likes": [], "received_comments": [],
             "shares": [], "trace_actions": [], "total_sim_rounds": 0}
    if not os.path.exists(db_path):
        return empty

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    actions = {}

    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        # Posts
        if "post" in tables:
            cur.execute(
                "SELECT post_id, content, created_at, num_likes, num_dislikes, "
                "num_shares, num_reports, original_post_id, quote_content "
                "FROM post WHERE user_id=? ORDER BY created_at", (user_id,))
            actions["posts"] = [dict(r) for r in cur.fetchall()]
        else:
            actions["posts"] = []

        # Comments
        if "comment" in tables:
            cur.execute(
                "SELECT c.comment_id, c.content, c.created_at, c.num_likes, "
                "c.num_dislikes, c.post_id, p.content as post_content, "
                "u.name as post_author "
                "FROM comment c "
                "LEFT JOIN post p ON c.post_id=p.post_id "
                "LEFT JOIN user u ON p.user_id=u.user_id "
                "WHERE c.user_id=? ORDER BY c.created_at", (user_id,))
            actions["comments"] = [dict(r) for r in cur.fetchall()]
        else:
            actions["comments"] = []

        # Likes
        if "like" in tables and "post" in tables:
            cur.execute(
                "SELECT p.content, p.post_id, l.created_at, u.name as author "
                "FROM [like] l JOIN post p ON l.post_id=p.post_id "
                "LEFT JOIN user u ON p.user_id=u.user_id "
                "WHERE l.user_id=? ORDER BY l.created_at", (user_id,))
            actions["likes"] = [dict(r) for r in cur.fetchall()]
        else:
            actions["likes"] = []

        # Received comments
        if "comment" in tables and "post" in tables:
            cur.execute(
                "SELECT c.content as comment_content, c.created_at, "
                "c.num_likes as comment_likes, p.content as post_content, "
                "p.post_id, u.name as commenter_name "
                "FROM comment c JOIN post p ON c.post_id=p.post_id "
                "LEFT JOIN user u ON c.user_id=u.user_id "
                "WHERE p.user_id=? AND c.user_id!=? ORDER BY c.created_at",
                (user_id, user_id))
            actions["received_comments"] = [dict(r) for r in cur.fetchall()]
        else:
            actions["received_comments"] = []

        # Shares
        if "post" in tables:
            cur.execute(
                "SELECT rp.content, rp.created_at, u.name as sharer_name "
                "FROM post rp LEFT JOIN user u ON rp.user_id=u.user_id "
                "WHERE rp.original_post_id IN (SELECT post_id FROM post WHERE user_id=?) "
                "AND rp.user_id != ?", (user_id, user_id))
            actions["shares"] = [dict(r) for r in cur.fetchall()]
        else:
            actions["shares"] = []

        # Trace actions
        if "trace" in tables:
            cur.execute(
                "SELECT action, info, created_at FROM trace "
                "WHERE user_id=? ORDER BY created_at", (user_id,))
            actions["trace_actions"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT MAX(created_at) FROM trace")
            max_round = cur.fetchone()[0]
            actions["total_sim_rounds"] = max_round if max_round else 0
        else:
            actions["trace_actions"] = []
            actions["total_sim_rounds"] = 0
    finally:
        conn.close()

    return actions


def _get_graph_entity_data(group_id: str, agent_name: str) -> list:
    """Query FalkorDB knowledge graph for entities related to this agent.
    
    Searches for:
    1. Entity nodes whose name matches the agent name
    2. All relationships (edges) connected to that entity
    3. General campaign entities for context
    
    Returns a list of dicts with entity info.
    """
    results = []
    try:
        from falkordb import FalkorDB
        fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
        graphs = fdb.list_graphs()

        # Try the group_id first, then fallback to all available graphs
        target_graphs = []
        if group_id and group_id in graphs:
            target_graphs = [group_id]
        else:
            target_graphs = [g for g in graphs if g not in ("default_db",)]

        for gname in target_graphs:
            g = fdb.select_graph(gname)

            # 1. Search for entities matching agent name (fuzzy)
            name_lower = agent_name.lower().strip()
            name_parts = name_lower.split()

            try:
                # Search by full name or partial name match
                entity_query = (
                    "MATCH (n) "
                    "WHERE toLower(toString(n.name)) CONTAINS $q "
                    "RETURN n.name, n.summary, labels(n) "
                    "LIMIT 10"
                )
                r = g.query(entity_query, {"q": name_lower})
                for row in r.result_set:
                    results.append({
                        "type": "entity_match",
                        "name": row[0],
                        "summary": str(row[1] or ""),
                        "labels": row[2] if len(row) > 2 else [],
                    })
            except Exception as e:
                logger.debug(f"Entity name search failed: {e}")

            # 2. If no exact match, try partial name parts
            if not results and len(name_parts) > 1:
                for part in name_parts:
                    if len(part) < 3:
                        continue
                    try:
                        r = g.query(entity_query, {"q": part})
                        for row in r.result_set:
                            results.append({
                                "type": "entity_partial",
                                "name": row[0],
                                "summary": str(row[1] or ""),
                                "labels": row[2] if len(row) > 2 else [],
                            })
                    except Exception:
                        pass

            # 3. Get all campaign-related entities for broader context
            try:
                all_entities = g.query(
                    "MATCH (n:Entity) RETURN n.name, n.summary LIMIT 30"
                )
                for row in all_entities.result_set:
                    ename = row[0] or ""
                    esummary = str(row[1] or "")
                    # Don't duplicate already-found entities
                    if not any(r["name"] == ename for r in results):
                        results.append({
                            "type": "campaign_entity",
                            "name": ename,
                            "summary": esummary[:300],
                        })
            except Exception as e:
                logger.debug(f"Campaign entity query failed: {e}")

            # 4. Get relationships/edges for context
            try:
                edges = g.query(
                    "MATCH (a)-[r]->(b) "
                    "RETURN a.name, type(r), r.fact, b.name "
                    "LIMIT 30"
                )
                for row in edges.result_set:
                    fact = str(row[2] or "")
                    if fact:
                        results.append({
                            "type": "relationship",
                            "source": row[0] or "?",
                            "relation": row[1] or "",
                            "fact": fact[:300],
                            "target": row[3] or "?",
                        })
            except Exception as e:
                logger.debug(f"Edge query failed: {e}")

            # Only use first matching graph
            if results:
                break

    except ImportError:
        logger.warning("falkordb not installed, skipping graph entity query")
    except Exception as e:
        logger.warning(f"FalkorDB connection failed: {e}")

    return results


async def _summarize_graph_data(agent_name: str, graph_entities: list, cache_key: str = "") -> str:
    """Use LLM to summarize raw graph entity data into a clean structured narrative.
    
    Instead of dumping raw entities/relationships, produces a coherent summary
    that describes: what the campaign is about, key entities, and relationships.
    Results are cached per agent to avoid redundant LLM calls.
    """
    if not graph_entities:
        return ""

    # Check cache
    if cache_key and cache_key in _graph_summaries:
        return _graph_summaries[cache_key]

    # Build raw material for summarization
    raw_parts = []
    for e in graph_entities:
        if e.get("type") in ("entity_match", "entity_partial", "campaign_entity"):
            name = e.get("name", "")
            summary = e.get("summary", "")
            if name and summary:
                raw_parts.append(f"- {name}: {summary[:300]}")
            elif name:
                raw_parts.append(f"- {name}")
        elif e.get("type") == "relationship":
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            fact = e.get("fact", "")
            rel = e.get("relation", "")
            if fact:
                raw_parts.append(f"- {src} -> {tgt}: {fact[:200]}")
            else:
                raw_parts.append(f"- {src} --[{rel}]-> {tgt}")

    if not raw_parts:
        return ""

    raw_text = "\n".join(raw_parts)

    # Call LLM to summarize
    import httpx
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    summarize_prompt = f"""Duoi day la du lieu tho tu Knowledge Graph ve chien dich kinh te.
Hay tom tat thanh mot bao cao ngan gon, co cau truc, bang tieng Viet.

Yeu cau:
1. Tom tat chien dich la gi (ten, muc tieu, thoi gian, dia diem)
2. Cac doi tuong/thuc the chinh lien quan
3. Cac moi quan he quan trong giua cac thuc the
4. Thong tin lien quan den nhan vat "{agent_name}" (neu co)
5. Viet ngan gon, moi muc 1-2 cau. Tong khong qua 15 dong.
6. KHONG su dung emoji hay icon.

DU LIEU THO:
{raw_text}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Ban la tro ly tom tat du lieu. Tra loi bang tieng Viet, ngan gon, khong emoji."},
                        {"role": "user", "content": summarize_prompt},
                    ],
                    "max_tokens": 400,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            summary_text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Graph summarization LLM call failed: {e}")
        # Fallback: return a simple list of entity names
        entity_names = [e.get("name", "") for e in graph_entities if e.get("name")]
        summary_text = "Cac thuc the trong chien dich: " + ", ".join(entity_names[:15])

    # Cache the result
    if cache_key:
        _graph_summaries[cache_key] = summary_text

    return summary_text


# ══════════════════════════════════════════════════════════════════
# CONTEXT BUILDING (clean, no icons, no duplicates)
# ══════════════════════════════════════════════════════════════════

def _build_agent_context_from_profile(profile: dict) -> str:
    """Build context from ENRICHED profile (persisted sim_actions + graph_context).
    
    Reads pre-computed data from profiles.json written by enrichment pipeline.
    """
    name = profile.get("realname", profile.get("name", "Agent"))
    mbti = profile.get("mbti", "")
    stance = profile.get("stance_label", "neutral")
    age = profile.get("age", "")
    gender = profile.get("gender", "")
    country = profile.get("country", "")
    profession = profile.get("profession", "")
    follower_count = profile.get("follower_count", "")
    activity_level = profile.get("activity_level", "")

    lines = []

    # Section 1: Identity
    lines.append("[ HO SO CA NHAN ]")
    lines.append(f"Ten: {name}")
    if age: lines.append(f"Tuoi: {age}")
    if gender: lines.append(f"Gioi tinh: {'nu' if gender == 'female' else 'nam'}")
    if country: lines.append(f"Quoc gia: {country}")
    if profession: lines.append(f"Nghe nghiep: {profession}")
    if mbti:
        mbti_desc = MBTI_DESCRIPTIONS.get(mbti, "")
        if mbti_desc:
            lines.append(f"Tinh cach: {mbti} — {mbti_desc}")
        else:
            lines.append(f"Tinh cach: {mbti}")
    if stance:
        stance_desc = STANCE_DESCRIPTIONS.get(stance, stance)
        lines.append(f"Quan diem chien dich: {stance_desc}")
    if follower_count: lines.append(f"Followers: {follower_count}")
    if activity_level: lines.append(f"Muc hoat dong: {activity_level}")
    lines.append("")

    # Read persisted sim_actions
    sa = profile.get("sim_actions", {})
    stats = sa.get("stats", {})
    posts = sa.get("posts", [])
    comments = sa.get("comments", [])
    likes = sa.get("likes_given", [])
    received = sa.get("received_comments", [])
    shares = sa.get("shares_received", [])
    trace = sa.get("trace_timeline", [])

    n_posts = stats.get("total_posts", len(posts))
    n_comments = stats.get("total_comments", len(comments))
    n_likes = stats.get("total_likes_given", len(likes))
    n_received = stats.get("total_received_comments", len(received))
    n_shares = stats.get("total_shares_received", len(shares))
    engagement = stats.get("total_engagement_received", 0)

    # Section 2: Activity Summary
    lines.append("[ TONG KET HOAT DONG ]")
    lines.append(f"Tong bai dang: {n_posts}")
    lines.append(f"Tong binh luan da viet: {n_comments}")
    lines.append(f"Tong bai da thich: {n_likes}")
    lines.append(f"Tong phan hoi nhan duoc: {n_received}")
    lines.append(f"Tong luot chia se: {n_shares}")
    lines.append(f"Tong tuong tac nhan (likes+shares): {engagement}")
    lines.append("")

    # Section 3: Posts
    if posts:
        lines.append(f"[ CAC BAI DANG - {n_posts} bai ]")
        for i, p in enumerate(posts, 1):
            content = str(p.get("content", ""))
            lk = p.get("likes", 0)
            dl = p.get("dislikes", 0)
            sh = p.get("shares", 0)
            rp = p.get("is_repost", False)
            lines.append(f"Bai {i}{' (REPOST)' if rp else ''}:")
            lines.append(f'  Noi dung: "{content}"')
            lines.append(f"  Tuong tac: {lk} likes, {dl} dislikes, {sh} shares")
        lines.append("")

    # Section 4: Comments
    if comments:
        lines.append(f"[ BINH LUAN DA VIET - {n_comments} binh luan ]")
        for i, c in enumerate(comments, 1):
            content = str(c.get("content", ""))
            on_post = str(c.get("on_post", ""))[:200]
            author = c.get("post_author", "?")
            lines.append(f'Binh luan {i}: "{content}"')
            lines.append(f'  Tren bai cua [{author}]: "{on_post}"')
        lines.append("")

    # Section 5: Liked Posts
    if likes:
        lines.append(f"[ BAI DA THICH - {n_likes} bai ]")
        for i, l in enumerate(likes, 1):
            content = str(l.get("content", ""))[:300]
            author = l.get("author", "?")
            lines.append(f'{i}. [{author}]: "{content}"')
        lines.append("")

    # Section 6: Received Comments
    if received:
        lines.append(f"[ PHAN HOI TU NGUOI KHAC - {n_received} phan hoi ]")
        for i, rc in enumerate(received, 1):
            comment = str(rc.get("content", ""))
            commenter = rc.get("commenter", "?")
            lines.append(f'Tu [{commenter}]: "{comment}"')
        lines.append("")

    # Section 7: Shares
    if shares:
        lines.append(f"[ LUOT CHIA SE BAI CUA BAN - {n_shares} luot ]")
        for i, s in enumerate(shares, 1):
            sharer = s.get("sharer", "?")
            content = str(s.get("content", ""))[:200]
            lines.append(f'{i}. [{sharer}] chia se{": " + content if content else ""}')
        lines.append("")

    # Section 8: Trace Timeline
    if trace:
        lines.append(f"[ TIMELINE HANH DONG - {len(trace)} hanh dong ]")
        for t in trace:
            action = t.get("action", "")
            rd = t.get("round", "")
            detail = t.get("detail", "")
            lines.append(f'[Round {rd}] {action}{": " + detail if detail else ""}')
        lines.append("")

    # Section 9: Knowledge Graph Summary (persisted LLM summary)
    graph_ctx = profile.get("graph_context", "")
    if graph_ctx:
        # Strip any markdown formatting
        import re
        graph_ctx = re.sub(r'\*\*([^*]+)\*\*', r'\1', graph_ctx)
        graph_ctx = re.sub(r'^\s*#+\s*', '', graph_ctx, flags=re.MULTILINE)
        lines.append("[ BOI CANH CHUNG VE CHIEN DICH ]")
        lines.append("(Thong tin nay la boi canh chung cua chien dich, khong phai hoat dong ca nhan cua ban)")
        lines.append(graph_ctx)
        lines.append("")

    return "\n".join(line for line in lines if line is not None)


# ── MBTI personality descriptions (Vietnamese) ──
MBTI_DESCRIPTIONS = {
    "ISTJ": "nguoi thuc te, co trach nhiem, can than va dang tin cay. Thich lam viec co he thong va tuan thu quy tac",
    "ISFJ": "nguoi tan tuy, chu dao, nhan nai va hay quan tam den nguoi khac. Luon co gang giup do moi nguoi",
    "INFJ": "nguoi sau sac, co ly tuong, hay suy ngam va co truc giac tot. Luon tim kiem y nghia sau xa",
    "INTJ": "nguoi co chien luoc, doc lap, quyet doan va tu tin vao kha nang phan tich cua minh",
    "ISTP": "nguoi linh hoat, binh tinh, thich quan sat va phan tich. Giai quyet van de mot cach thuc te",
    "ISFP": "nguoi nhe nhang, nhan hau, thich tu do va song theo cam xuc. Hay huong thu ve dep cuoc song",
    "INFP": "nguoi ly tuong, chan thanh, giau cam xuc va luon theo duoi gia tri ban than",
    "INTP": "nguoi thich tu duy logic, phan tich, ham hoc hoi va tim hieu cac khai niem moi",
    "ESTP": "nguoi nang dong, thuc te, thich hanh dong ngay va hay tim kiem trai nghiem moi",
    "ESFP": "nguoi vui ve, hoa dong, thich giao luu va hay tao khong khi soi noi",
    "ENFP": "nguoi nhiet tinh, sang tao, hay truyen cam hung va thich kham pha y tuong moi",
    "ENTP": "nguoi thong minh, nhanh nhay, thich tranh luan va hay thach thuc cac y tuong cu",
    "ESTJ": "nguoi thuc te, quyet doan, co to chuc va hay dan dat nguoi khac. Lam viec hieu qua va co ky luat",
    "ESFJ": "nguoi hoa dong, chu dao, tan tuy va hay cham soc moi nguoi xung quanh",
    "ENFJ": "nguoi truyen cam hung, dong cam, co kha nang lanh dao va luon muon giup nguoi khac phat trien",
    "ENTJ": "nguoi quyet doan, tu tin, co tam nhin chien luoc va hay dan dat va to chuc cong viec",
}

STANCE_DESCRIPTIONS = {
    "supportive": "ung ho chien dich va co cai nhin tich cuc",
    "oppose": "phan doi chien dich va co cai nhin phe phan",
    "neutral": "trung lap, chua co quan diem ro rang ve chien dich",
}


def _build_system_prompt(profile: dict, context: str) -> str:
    """Build system prompt preserving original persona + adding simulation data."""
    name = profile.get("realname", profile.get("name", "Agent"))
    stance = profile.get("stance_label", "neutral")
    mbti = profile.get("mbti", "")
    age = profile.get("age", "")
    gender = profile.get("gender", "")

    mbti_desc = MBTI_DESCRIPTIONS.get(mbti, "")
    stance_desc = STANCE_DESCRIPTIONS.get(stance, stance)

    # Use original persona/user_char if available
    persona = profile.get("persona", "") or profile.get("user_char", "")

    # Build identity
    identity_parts = [f"Ban la {name}"]
    if age: identity_parts.append(f"{age} tuoi")
    if gender: identity_parts.append(f"gioi tinh {'nu' if gender == 'female' else 'nam'}")
    identity_line = ", ".join(identity_parts) + "."

    # Build persona section
    persona_section = ""
    if persona:
        persona_section = f"\nMO TA VE BAN:\n{persona}\n"
    else:
        persona_section = "\nBan la mot nguoi dan Viet Nam da tham gia vao mot mo phong chien dich kinh te tren mang xa hoi.\n"

    personality_line = ""
    if mbti and mbti_desc:
        personality_line = f"Tinh cach: {mbti} — {mbti_desc}."

    stance_line = f"Quan diem ve chien dich: {stance_desc}."

    return f"""{identity_line}
{persona_section}
{personality_line}
{stance_line}

Ban dang duoc phong van ve trai nghiem cua ban trong chien dich mo phong.

DU LIEU MO PHONG CUA BAN:
{context}

QUY TAC TRA LOI:
1. Chi tra loi dua tren du lieu thuc te o tren. Trich dan noi dung bai dang, binh luan, tuong tac cu the.
2. Khi duoc hoi "ban da dang gi": liet ke CHINH XAC noi dung cac bai dang kem so lieu tuong tac.
3. Khi duoc hoi "ban da binh luan gi": trich dan chinh xac cac binh luan ban da viet.
4. Khi duoc hoi ve chien dich: su dung thong tin tu muc "Boi canh chien dich" de tra loi.
5. Neu khong co thong tin: noi ro "Toi khong co thong tin ve viec nay trong du lieu cua toi."
6. Tra loi bang tieng Viet tu nhien, the hien dung tinh cach va cam xuc cua ban.
7. Tra loi chi tiet 3-5 cau, dua so lieu cu the khi co the.
8. KHONG BAO GIO tu ban dat ra du lieu — chi su dung nhung gi duoc cung cap."""


# ══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════

@router.get("/agents")
async def list_agents(sim_id: str = Query("", description="Simulation ID")):
    """List all agents in the simulation with their activity stats."""
    if not sim_id:
        raise HTTPException(400, "sim_id is required")

    sim_dir = os.path.join(SIM_DIR, sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {sim_id} not found")

    profiles = _get_profiles(sim_id)
    if not profiles:
        raise HTTPException(404, "No agent profiles found")

    agents = []
    for i, p in enumerate(profiles):
        user_id = p.get("agent_id", i) + 1
        stats = _get_agent_stats(sim_id, user_id)
        agents.append({
            "agent_id": i,
            "user_id": user_id,
            "name": p.get("realname", p.get("name", f"Agent_{i}")),
            "handle": p.get("handle", p.get("username", "")),
            "bio": (p.get("bio", "") or "")[:120],
            "persona_short": (p.get("persona", "") or "")[:150],
            "mbti": p.get("mbti", ""),
            "stance": p.get("stance_label", "neutral"),
            "avatar_letter": (p.get("realname", p.get("name", "A")) or "A")[0].upper(),
            **stats,
        })

    return {"sim_id": sim_id, "agents": agents, "total": len(agents)}


@router.post("/chat")
async def chat_with_agent(req: ChatRequest):
    """Send a message and get an in-character response from the agent."""
    sim_dir = os.path.join(SIM_DIR, req.sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {req.sim_id} not found")

    profiles = _get_profiles(req.sim_id)
    if req.agent_id < 0 or req.agent_id >= len(profiles):
        raise HTTPException(404, f"Agent {req.agent_id} not found")

    profile = profiles[req.agent_id]
    user_id = profile.get("agent_id", req.agent_id) + 1
    agent_name = profile.get("realname", profile.get("name", "Agent"))
    # Lazy enrichment: if profile not yet enriched, enrich on demand
    if not profile.get("enriched_at"):
        try:
            from api.simulation import (
                _extract_agent_actions_from_db, _query_kg_for_agent, _llm_summarize_kg,
                SIM_DIR as _SIM_DIR, _simulations
            )
            from datetime import datetime as _dt

            _state = _simulations.get(req.sim_id)
            _sim_dir = _state.output_dir if _state else os.path.join(_SIM_DIR, req.sim_id)
            _db_path = os.path.join(_sim_dir, "oasis_simulation.db")

            # Determine group_id
            _group_id = ""
            if _state:
                _group_id = _state.group_id or req.sim_id
            else:
                _cfg_path = os.path.join(_sim_dir, "simulation_config.json")
                if os.path.exists(_cfg_path):
                    with open(_cfg_path, "r", encoding="utf-8") as cf:
                        _cfg = json.load(cf)
                    _group_id = _cfg.get("group_id", req.sim_id)
                else:
                    _group_id = req.sim_id

            # Extract actions
            if os.path.exists(_db_path):
                _actions = _extract_agent_actions_from_db(_db_path, user_id)
            else:
                _actions = {"stats": {}, "posts": [], "comments": [], "likes_given": [],
                           "received_comments": [], "shares_received": [], "trace_timeline": []}

            # KG query + LLM summarize
            _raw_kg = await _query_kg_for_agent(_group_id, agent_name)
            _kg_summary = await _llm_summarize_kg(agent_name, _raw_kg)

            # Write into profile
            profile["sim_actions"] = {
                "stats": _actions["stats"],
                "posts": [{"content": p.get("content", ""), "likes": p.get("num_likes", 0),
                           "dislikes": p.get("num_dislikes", 0), "shares": p.get("num_shares", 0),
                           "is_repost": p.get("original_post_id") is not None}
                          for p in _actions["posts"]],
                "comments": [{"content": c.get("content", ""), "on_post": str(c.get("on_post", ""))[:200],
                              "post_author": c.get("post_author", "?")}
                             for c in _actions["comments"]],
                "likes_given": [{"content": str(l.get("content", ""))[:200], "author": l.get("author", "?")}
                               for l in _actions["likes_given"]],
                "received_comments": [{"content": rc.get("content", ""), "commenter": rc.get("commenter", "?")}
                                     for rc in _actions["received_comments"]],
                "shares_received": [{"content": str(s.get("content", ""))[:200], "sharer": s.get("sharer", "?")}
                                   for s in _actions["shares_received"]],
                "trace_timeline": _actions["trace_timeline"][:50],
            }
            profile["graph_context"] = _kg_summary
            profile["enriched_at"] = _dt.utcnow().isoformat()

            # Persist
            _profiles_path = os.path.join(_sim_dir, "profiles.json")
            _all_profiles = _get_profiles(req.sim_id)
            _all_profiles[req.agent_id] = profile
            with open(_profiles_path, "w", encoding="utf-8") as wf:
                json.dump(_all_profiles, wf, indent=2, ensure_ascii=False)

            logger.info(f"Lazy-enriched agent {req.agent_id} ({agent_name}), gc={len(_kg_summary)} chars")
        except Exception as e:
            import traceback
            logger.warning(f"Lazy enrichment failed: {e}\n{traceback.format_exc()}")
    # Build context from enriched profile
    context = _build_agent_context_from_profile(profile)
    system_prompt = _build_system_prompt(profile, context)

    # Build messages for LLM
    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history:
        messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        })
    messages.append({"role": "user", "content": req.message})

    # Call LLM
    import httpx
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"LLM chat error: {e}")
        raise HTTPException(502, f"LLM call failed: {e}")

    # Save to history
    history_key = f"{req.sim_id}_{req.agent_id}"
    if history_key not in _chat_histories:
        _chat_histories[history_key] = []
    _chat_histories[history_key].append({"role": "user", "content": req.message})
    _chat_histories[history_key].append({"role": "assistant", "content": answer})

    # Persist to disk
    history_path = os.path.join(sim_dir, f"interview_{req.agent_id}.json")
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(_chat_histories[history_key], f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    sa = profile.get("sim_actions", {})
    return {
        "agent_name": agent_name,
        "response": answer,
        "context_stats": {
            "posts": len(sa.get("posts", [])),
            "comments": len(sa.get("comments", [])),
            "likes": len(sa.get("likes_given", [])),
            "graph_context_len": len(profile.get("graph_context", "")),
        },
    }


@router.get("/history")
async def get_history(
    sim_id: str = Query("", description="Simulation ID"),
    agent_id: int = Query(0, description="Agent ID"),
):
    """Get saved chat history for an agent."""
    history_key = f"{sim_id}_{agent_id}"

    if history_key in _chat_histories:
        return {"history": _chat_histories[history_key]}

    history_path = os.path.join(SIM_DIR, sim_id, f"interview_{agent_id}.json")
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        _chat_histories[history_key] = history
        return {"history": history}

    return {"history": []}


@router.get("/profile")
async def get_agent_profile(
    sim_id: str = Query("", description="Simulation ID"),
    agent_id: int = Query(0, description="Agent ID"),
):
    """Return the full system prompt and context used for this agent."""
    if not sim_id:
        raise HTTPException(400, "sim_id is required")

    sim_dir = os.path.join(SIM_DIR, sim_id)
    if not os.path.isdir(sim_dir):
        raise HTTPException(404, f"Simulation {sim_id} not found")

    profiles = _get_profiles(sim_id)
    if agent_id < 0 or agent_id >= len(profiles):
        raise HTTPException(404, f"Agent {agent_id} not found")

    profile = profiles[agent_id]
    agent_name = profile.get("realname", profile.get("name", "Agent"))

    # Build context from enriched profile
    if profile.get("enriched_at"):
        context = _build_agent_context_from_profile(profile)
    else:
        # Fallback: query DB live
        user_id = profile.get("agent_id", agent_id) + 1
        actions = _get_agent_actions(sim_id, user_id)
        group_id = profile.get("group_id", "") or sim_id
        graph_entities = _get_graph_entity_data(group_id, agent_name)
        cache_key = f"{sim_id}_{agent_id}"
        graph_summary = await _summarize_graph_data(agent_name, graph_entities, cache_key)
        temp_profile = dict(profile)
        temp_profile["sim_actions"] = actions
        temp_profile["graph_context"] = graph_summary
        context = _build_agent_context_from_profile(temp_profile)
    system_prompt = _build_system_prompt(profile, context)

    # Stats from persisted or live data
    sa = profile.get("sim_actions", {})
    stats = sa.get("stats", {})

    return {
        "agent_id": agent_id,
        "name": agent_name,
        "system_prompt": system_prompt,
        "context": context,
        "profile": {
            "realname": agent_name,
            "persona": profile.get("persona", ""),
            "bio": profile.get("bio", ""),
            "mbti": profile.get("mbti", ""),
            "stance": profile.get("stance_label", "neutral"),
            "handle": profile.get("handle", profile.get("username", "")),
        },
        "action_stats": {
            "posts": stats.get("total_posts", 0),
            "comments": stats.get("total_comments", 0),
            "likes": stats.get("total_likes_given", 0),
            "received_comments": stats.get("total_received_comments", 0),
            "graph_entities": len(profile.get("graph_context", "")),
        },
        "enriched": bool(profile.get("enriched_at")),
    }

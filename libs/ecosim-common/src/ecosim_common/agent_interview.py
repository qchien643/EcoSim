"""
Shared primitives cho 2-phase agent interview — dùng chung bởi:
  * apps/simulation/api/interview.py  — user-facing interactive chat
  * apps/core/app/services/report_agent.py  — `interview_agents` tool
  * apps/simulation/api/survey.py  — conduct_survey (intent-based context)

Architecture:
  Phase 1 — classify_intent(question)  → {intent, language, topic_hint}
  Phase 2 — load_context_blocks(profile, blocks, loaders_registry)
             → {block_name: formatted_text}  (selective; only needed blocks)
  Phase 3 — build_response_prompt(profile, intent_data, blocks, extra_rules)
             → English system prompt; caller passes it to LLM.

All prompt strings are English. Output language is driven by the user's
question language (auto-detect in classifier) and by RESPONSE RULES.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger("ecosim_common.agent_interview")


# ══════════════════════════════════════════════════════════════════
# Canonical intents
# ══════════════════════════════════════════════════════════════════

INTERVIEW_INTENTS = {
    "identity",           # "Who are you?" / "Bạn là ai?"
    "recall_posts",       # "What did you post?"
    "recall_comments",    # "What did you comment?"
    "recall_specific",    # "Did you post/comment about X?"
    "opinion_campaign",   # "What do you think about this campaign?"
    "opinion_crisis",     # "How did you react to crisis Y?"
    "social_network",     # "Who do you follow?" / relationships
    "motivation",         # "Why did you post/like X?"
    "projection",         # "What would you do next?"
    "general",            # catch-all
}

# Default mapping — caller MAY override per-call via extra INTENT_INFO_MAP arg.
# Block names must exist in the loaders_registry passed into load_context_blocks.
INTENT_INFO_MAP: Dict[str, List[str]] = {
    "identity":          ["profile_basic", "persona", "interests"],
    "recall_posts":      ["profile_basic", "posts"],
    "recall_comments":   ["profile_basic", "comments"],
    "recall_specific":   ["profile_basic", "posts", "comments", "likes"],
    "opinion_campaign":  ["profile_basic", "persona", "campaign", "interests"],
    "opinion_crisis":    ["profile_basic", "persona", "crisis", "recent_actions"],
    "social_network":    ["profile_basic", "graph_context"],
    "motivation":        ["profile_basic", "persona", "interests", "recent_actions"],
    "projection":        ["profile_basic", "persona", "interests", "recent_actions"],
    "general":           ["profile_basic", "persona", "activity_summary"],
}


# ══════════════════════════════════════════════════════════════════
# Phase 1 — Intent classifier
# ══════════════════════════════════════════════════════════════════

INTENT_CLASSIFIER_PROMPT = """\
You are an intent classifier for a social-media simulation interview system.
Given a user question (addressed to an agent in the simulation), classify it
into ONE of these intents:

- identity: asking who the agent is, profile, demographics
- recall_posts: asking what posts the agent created
- recall_comments: asking what comments the agent wrote
- recall_specific: asking about a specific post/comment/like topic
- opinion_campaign: asking the agent's view on the campaign
- opinion_crisis: asking reaction to a crisis event
- social_network: asking about follows, followers, relationships
- motivation: asking WHY the agent did something
- projection: asking what the agent would do next / future intent
- general: anything else / unclear

Return STRICT JSON:
{{"intent": "<one of above>", "confidence": 0.0-1.0, "language": "vi|en",
  "needs_specific_topic": true|false, "topic_hint": "<keyword if needs_specific_topic>"}}

User question:
{question}
"""


_FALLBACK_INTENT: Dict[str, Any] = {
    "intent": "general",
    "confidence": 0.0,
    "language": "vi",
    "needs_specific_topic": False,
    "topic_hint": "",
}


async def classify_intent(
    question: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Phase 1 LLM call: classify user question → intent + metadata.

    Uses OpenAI-compatible HTTP directly (không depend camel-ai). Caller passes
    `model` — conventionally the fast/cheap model (LLM_FAST_MODEL_NAME).

    Returns dict: {intent, confidence, language, needs_specific_topic, topic_hint}.
    Gracefully falls back to {"intent": "general", ...} on any failure.
    """
    if not question or not question.strip():
        return dict(_FALLBACK_INTENT)

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": INTENT_CLASSIFIER_PROMPT.format(
                            question=question[:500],
                        )},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(content)
        if not isinstance(data, dict):
            return dict(_FALLBACK_INTENT)
        intent = str(data.get("intent", "general")).strip().lower()
        if intent not in INTERVIEW_INTENTS:
            intent = "general"
        return {
            "intent": intent,
            "confidence": float(data.get("confidence", 0.5) or 0.5),
            "language": (data.get("language") or "vi").strip().lower()[:2],
            "needs_specific_topic": bool(data.get("needs_specific_topic", False)),
            "topic_hint": str(data.get("topic_hint", "") or "")[:80],
        }
    except Exception as e:
        logger.warning("classify_intent failed: %s — fallback general", e)
        return dict(_FALLBACK_INTENT)


# ══════════════════════════════════════════════════════════════════
# Phase 2 — Generic context block loaders
# ══════════════════════════════════════════════════════════════════
# All loaders accept (profile, topic_hint) — caller's extended loaders may
# accept additional args via closures (e.g. sim_dir for campaign/crisis).

def ctx_profile_basic(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Identity basics: name, age, gender, MBTI, country, stance."""
    name = profile.get("realname", profile.get("name", "Agent"))
    lines = [f"Name: {name}"]
    for key, label in [("age", "Age"), ("gender", "Gender"),
                        ("mbti", "MBTI"), ("country", "Country")]:
        val = profile.get(key, "")
        if val:
            lines.append(f"{label}: {val}")
    stance = profile.get("stance_label", "")
    if stance:
        lines.append(f"Campaign stance: {stance}")
    return "\n".join(lines)


def ctx_persona(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Persona narrative — prefer evolved (after reflection cycles)."""
    persona = (
        profile.get("persona_evolved")
        or profile.get("persona", "")
        or profile.get("user_char", "")
        or profile.get("bio", "")
    )
    return persona.strip() if persona else "(persona not available)"


def ctx_interests(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Top interests (keywords)."""
    interests = profile.get("interests") or []
    if not isinstance(interests, list):
        return "(none)"
    return ", ".join(str(i) for i in interests[:8]) or "(none)"


def ctx_posts(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Agent's posts list with engagement stats + optional topic filter."""
    sa = profile.get("sim_actions", {}) or {}
    posts = sa.get("posts") or []
    if not posts:
        return "(no posts)"
    if topic_hint:
        tl = topic_hint.lower()
        filtered = [p for p in posts if tl in str(p.get("content", "")).lower()]
        if filtered:
            posts = filtered
        else:
            return f"(no posts matching '{topic_hint}')"
    lines = [f"Total posts: {len(posts)}"]
    for i, p in enumerate(posts[:8], 1):
        content = str(p.get("content", ""))[:300]
        lk = p.get("likes", 0)
        sh = p.get("shares", 0)
        tag = " [repost]" if p.get("is_repost") else ""
        lines.append(f"{i}.{tag} \"{content}\" (likes={lk}, shares={sh})")
    return "\n".join(lines)


def ctx_comments(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Agent's comments with optional topic filter."""
    sa = profile.get("sim_actions", {}) or {}
    comments = sa.get("comments") or []
    if not comments:
        return "(no comments)"
    if topic_hint:
        tl = topic_hint.lower()
        filtered = [c for c in comments if tl in str(c.get("content", "")).lower()]
        if filtered:
            comments = filtered
        else:
            return f"(no comments matching '{topic_hint}')"
    lines = [f"Total comments: {len(comments)}"]
    for i, c in enumerate(comments[:8], 1):
        content = str(c.get("content", ""))[:250]
        on_post = str(c.get("on_post", ""))[:120]
        author = c.get("post_author", "?")
        lines.append(f'{i}. "{content}" — on post by {author}: "{on_post}"')
    return "\n".join(lines)


def ctx_likes(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Posts the agent liked (optional topic filter)."""
    sa = profile.get("sim_actions", {}) or {}
    likes = sa.get("likes_given") or []
    if not likes:
        return "(no likes given)"
    if topic_hint:
        tl = topic_hint.lower()
        filtered = [l for l in likes if tl in str(l.get("content", "")).lower()]
        if filtered:
            likes = filtered
        else:
            return f"(no likes matching '{topic_hint}')"
    lines = [f"Total likes given: {len(likes)}"]
    for i, l in enumerate(likes[:6], 1):
        content = str(l.get("content", ""))[:200]
        author = l.get("author", "?")
        lines.append(f"{i}. [{author}]: \"{content}\"")
    return "\n".join(lines)


def ctx_recent_actions(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Timeline of recent actions (last 10)."""
    sa = profile.get("sim_actions", {}) or {}
    trace = sa.get("trace_timeline") or []
    if not trace:
        return "(no trace timeline)"
    lines = [f"Recent actions (last {min(10, len(trace))}):"]
    for t in trace[-10:]:
        action = t.get("action", "")
        rd = t.get("round", "?")
        detail = str(t.get("detail", ""))[:120]
        lines.append(f"  [Round {rd}] {action}" + (f": {detail}" if detail else ""))
    return "\n".join(lines)


def ctx_activity_summary(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Short aggregate counts."""
    sa = profile.get("sim_actions", {}) or {}
    stats = sa.get("stats", {}) or {}
    parts = [
        f"posts={stats.get('total_posts', len(sa.get('posts', [])))}",
        f"comments={stats.get('total_comments', len(sa.get('comments', [])))}",
        f"likes_given={stats.get('total_likes_given', len(sa.get('likes_given', [])))}",
        f"received_comments={stats.get('total_received_comments', 0)}",
        f"engagement_received={stats.get('total_engagement_received', 0)}",
    ]
    return "; ".join(parts)


def ctx_graph_context(profile: Dict[str, Any], topic_hint: str = "") -> str:
    """Pre-summarized KG context (social network) — from profile.graph_context."""
    gc = profile.get("graph_context", "") or ""
    if not gc.strip():
        return "(no social network data available)"
    import re as _re
    gc = _re.sub(r"\*\*([^*]+)\*\*", r"\1", gc)
    gc = _re.sub(r"^\s*#+\s*", "", gc, flags=_re.MULTILINE)
    return gc.strip()[:2000]


# Built-in registry — callers merge their own loaders on top.
BUILTIN_LOADERS: Dict[str, Callable[..., str]] = {
    "profile_basic":    ctx_profile_basic,
    "persona":          ctx_persona,
    "interests":        ctx_interests,
    "posts":            ctx_posts,
    "comments":         ctx_comments,
    "likes":            ctx_likes,
    "recent_actions":   ctx_recent_actions,
    "activity_summary": ctx_activity_summary,
    "graph_context":    ctx_graph_context,
}


def load_context_blocks(
    profile: Dict[str, Any],
    block_names: List[str],
    loaders_registry: Optional[Dict[str, Callable[..., str]]] = None,
    topic_hint: str = "",
) -> Dict[str, str]:
    """Load ONLY the requested blocks. Returns dict block_name → formatted text.

    `loaders_registry` defaults to `BUILTIN_LOADERS`. Callers (e.g. Sim service)
    may merge sim_dir-specific loaders (campaign, crisis) into this dict before
    calling.
    """
    registry = loaders_registry if loaders_registry is not None else BUILTIN_LOADERS
    out: Dict[str, str] = {}
    for block in block_names:
        loader = registry.get(block)
        if loader is None:
            logger.debug("load_context_blocks: no loader for '%s'", block)
            continue
        try:
            out[block] = loader(profile, topic_hint)
        except TypeError:
            # Loader signature might be (profile,) without topic_hint — retry
            try:
                out[block] = loader(profile)
            except Exception as e:
                logger.warning("loader '%s' failed: %s", block, e)
                out[block] = f"(failed to load {block})"
        except Exception as e:
            logger.warning("loader '%s' failed: %s", block, e)
            out[block] = f"(failed to load {block})"
    return out


# ══════════════════════════════════════════════════════════════════
# Phase 3 — Response prompt composer
# ══════════════════════════════════════════════════════════════════

INTERVIEW_RESPONSE_SYSTEM_PROMPT = """\
You are role-playing as {name}, a participant in a social-media campaign
simulation. You are being interviewed / surveyed. Stay strictly in character.

=== YOUR IDENTITY ===
{profile_basic}

=== YOUR PERSONA ===
{persona}

=== DETECTED INTENT ===
Classified intent: {intent}
User question language: {language}

=== RELEVANT CONTEXT (selectively loaded for this intent) ===
{context_blocks}

=== RESPONSE RULES ===
1. Answer ONLY based on the data shown above. Do NOT invent posts, comments,
   interactions, or demographics that are not listed.
2. Match the user's language: if the question is in Vietnamese, respond in
   Vietnamese; if English, respond in English.
3. Speak in first person as {name}. Reflect the MBTI personality and stance
   naturally — do not announce them ("As an ENFP..." is forbidden).
4. Quote your own content verbatim when recalling posts/comments. Do NOT
   paraphrase into different wording.
5. If information is missing from the context above, say so honestly:
   "Tôi không nhớ rõ chi tiết đó" / "I don't have that in my records".
6. Keep response to 2-5 sentences unless the user explicitly asks for a list.
7. Do NOT cite (EV-N) tags — that format is for reports, not conversation.
{extra_rules_block}"""


def build_response_prompt(
    profile: Dict[str, Any],
    intent_data: Dict[str, Any],
    context_blocks: Dict[str, str],
    extra_rules: Optional[List[str]] = None,
) -> str:
    """Compose the Phase-3 system prompt (English scaffold, in-character response).

    `extra_rules` — optional list of extra bullets (e.g. for Survey asking JSON
    output). Appended as numbered rules after the 7 default rules.
    """
    name = profile.get("realname", profile.get("name", "Agent"))

    # Render context blocks with headers — skip profile_basic/persona (dedicated sections)
    rendered_parts = []
    for block_name, block_text in context_blocks.items():
        if not block_text or not str(block_text).strip():
            continue
        if block_name in ("profile_basic", "persona"):
            continue
        header = block_name.replace("_", " ").upper()
        rendered_parts.append(f"[{header}]\n{block_text}")
    context_rendered = (
        "\n\n".join(rendered_parts)
        or "(no additional context needed for this intent)"
    )

    # Render extra rules block (numbered continuing from 8)
    extra_block = ""
    if extra_rules:
        lines = []
        for idx, rule in enumerate(extra_rules, start=8):
            lines.append(f"{idx}. {rule}")
        extra_block = "\n" + "\n".join(lines)

    return INTERVIEW_RESPONSE_SYSTEM_PROMPT.format(
        name=name,
        profile_basic=context_blocks.get("profile_basic", ctx_profile_basic(profile)),
        persona=context_blocks.get("persona", ctx_persona(profile)),
        intent=intent_data.get("intent", "general"),
        language=intent_data.get("language", "vi"),
        context_blocks=context_rendered,
        extra_rules_block=extra_block,
    )

"""
Agent Memory Manager — FalkorDB-based long-term memory for simulation agents.

Pattern inspired by MiroFish's Zep graph memory updater, but using FalkorDB
(already in our stack) instead of Zep Cloud.

Memory lifecycle:
  1. Before round: recall_memories(agent_id) → inject into OASIS prompt
  2. After round:  store_memory(agent_id, action) → LLM extract facts → FalkorDB

Graph schema (separate from KG campaign graph):
  (:Agent {id, name, role, sim_id})
  (:Memory {id, text, round, sentiment, importance, created_at})
  (:Agent)-[:REMEMBERS]->(:Memory)
  (:Memory)-[:ABOUT]->(:Entity)   -- links to existing campaign KG entities
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.llm_client import LLMClient

logger = logging.getLogger("ecosim.agent_memory")

MEMORY_GRAPH_NAME = "ecosim_agent_memory"

EXTRACT_PROMPT = """\
You are analyzing an agent's action in a social simulation. Extract the key facts.

Agent: {agent_name} (Role: {agent_role})
Action: {action_type}
Content: {content}
Round: {round_num}
Context: {context}

Extract the key information as JSON:
{{
    "facts": ["fact 1", "fact 2"],
    "sentiment": "positive|negative|neutral",
    "importance": 1-10,
    "entities_mentioned": ["entity name 1", "entity name 2"],
    "summary": "One sentence summary of what this agent did and why it matters"
}}

Rules:
- facts: 2-4 key takeaways from this action
- sentiment: the emotional tone of the action
- importance: how significant this action is (1=trivial, 10=critical)
- entities_mentioned: companies, products, people referenced
- summary: concise Vietnamese summary
"""


class AgentMemoryManager:
    """FalkorDB-based long-term memory for simulation agents.

    Uses a SEPARATE graph (ecosim_agent_memory) to avoid polluting
    the campaign knowledge graph.
    """

    def __init__(self, sim_id: str = "", llm_client: LLMClient = None):
        self.sim_id = sim_id
        self.llm = llm_client or LLMClient()
        self._graph = None

    def _get_graph(self):
        """Get or create the agent memory graph."""
        if self._graph is None:
            from falkordb import FalkorDB
            client = FalkorDB(
                host=Config.FALKORDB_HOST,
                port=Config.FALKORDB_PORT,
            )
            self._graph = client.select_graph(MEMORY_GRAPH_NAME)
            self._ensure_schema()
        return self._graph

    def _ensure_schema(self):
        """Create indexes for efficient memory retrieval."""
        graph = self._graph
        try:
            graph.query("CREATE INDEX FOR (a:Agent) ON (a.agent_id)")
        except Exception:
            pass  # index may already exist
        try:
            graph.query("CREATE INDEX FOR (m:Memory) ON (m.round)")
        except Exception:
            pass

    # ── Store Memories ──

    def register_agent(self, agent_id: str, name: str, role: str):
        """Register an agent node in the memory graph."""
        graph = self._get_graph()
        graph.query(
            "MERGE (a:Agent {agent_id: $aid, sim_id: $sid}) "
            "SET a.name = $name, a.role = $role",
            params={"aid": agent_id, "sid": self.sim_id, "name": name, "role": role},
        )
        logger.debug(f"Registered agent: {name} ({agent_id})")

    def store_memory(
        self,
        agent_id: str,
        agent_name: str,
        agent_role: str,
        round_num: int,
        action_type: str,
        content: str,
        context: str = "",
    ) -> Dict[str, Any]:
        """Store an action as a memory: LLM extracts facts → FalkorDB.

        Returns extracted memory info.
        """
        if not content or len(content.strip()) < 5:
            return {}

        # LLM extract key facts
        try:
            extracted = self.llm.chat_json(
                messages=[{
                    "role": "user",
                    "content": EXTRACT_PROMPT.format(
                        agent_name=agent_name,
                        agent_role=agent_role,
                        action_type=action_type,
                        content=content[:500],
                        round_num=round_num,
                        context=context[:200],
                    ),
                }],
                temperature=0.1,
                max_tokens=300,
            )
        except Exception as e:
            logger.warning(f"Memory extraction failed for agent {agent_id}: {e}")
            # Fallback: store raw content
            extracted = {
                "facts": [content[:100]],
                "sentiment": "neutral",
                "importance": 3,
                "entities_mentioned": [],
                "summary": content[:100],
            }

        # Generate memory ID
        mem_id = hashlib.md5(
            f"{agent_id}_{round_num}_{action_type}_{content[:50]}".encode()
        ).hexdigest()[:12]

        # Store in FalkorDB
        graph = self._get_graph()

        # Create memory node
        facts_text = "; ".join(extracted.get("facts", []))
        summary = extracted.get("summary", content[:100])
        memory_text = f"[R{round_num}] {summary}" if summary else f"[R{round_num}] {facts_text}"

        graph.query(
            "MERGE (m:Memory {mem_id: $mid}) "
            "SET m.text = $text, m.round = $round, "
            "m.sentiment = $sentiment, m.importance = $importance, "
            "m.action_type = $atype, m.facts = $facts, "
            "m.sim_id = $sid, m.created_at = $ts",
            params={
                "mid": mem_id,
                "text": memory_text,
                "round": round_num,
                "sentiment": extracted.get("sentiment", "neutral"),
                "importance": extracted.get("importance", 3),
                "atype": action_type,
                "facts": facts_text,
                "sid": self.sim_id,
                "ts": datetime.now().isoformat(),
            },
        )

        # Link Agent → Memory
        graph.query(
            "MATCH (a:Agent {agent_id: $aid, sim_id: $sid}), "
            "(m:Memory {mem_id: $mid}) "
            "MERGE (a)-[:REMEMBERS]->(m)",
            params={"aid": agent_id, "sid": self.sim_id, "mid": mem_id},
        )

        # Link Memory → Entity (connect to existing KG entities)
        for entity_name in extracted.get("entities_mentioned", []):
            if entity_name:
                graph.query(
                    "MATCH (m:Memory {mem_id: $mid}) "
                    "MERGE (e:Entity {name: $ename}) "
                    "MERGE (m)-[:ABOUT]->(e)",
                    params={"mid": mem_id, "ename": entity_name},
                )

        logger.debug(
            f"Memory stored: agent={agent_name}, R{round_num}, "
            f"sentiment={extracted.get('sentiment')}, importance={extracted.get('importance')}"
        )

        return extracted

    # ── Recall Memories ──

    def recall_memories(
        self,
        agent_id: str,
        limit: int = 5,
        min_importance: int = 2,
    ) -> List[Dict[str, Any]]:
        """Recall agent's memories, ordered by round (most recent first).

        Returns list of memory dicts.
        """
        graph = self._get_graph()
        try:
            result = graph.query(
                "MATCH (a:Agent {agent_id: $aid, sim_id: $sid})-[:REMEMBERS]->(m:Memory) "
                "WHERE m.importance >= $min_imp "
                "RETURN m.text AS text, m.round AS round, m.sentiment AS sentiment, "
                "m.importance AS importance, m.action_type AS action_type "
                "ORDER BY m.round DESC "
                "LIMIT $limit",
                params={
                    "aid": agent_id,
                    "sid": self.sim_id,
                    "min_imp": min_importance,
                    "limit": limit,
                },
            )
            memories = []
            for record in result.result_set:
                memories.append({
                    "text": record[0],
                    "round": record[1],
                    "sentiment": record[2],
                    "importance": record[3],
                    "action_type": record[4],
                })
            return memories
        except Exception as e:
            logger.warning(f"Memory recall failed for agent {agent_id}: {e}")
            return []

    def get_agent_memory_summary(self, agent_id: str, limit: int = 8) -> str:
        """Format agent memories as a context string for OASIS prompt injection.

        Returns formatted string ready to inject into system prompt.
        """
        memories = self.recall_memories(agent_id, limit=limit, min_importance=1)
        if not memories:
            return ""

        lines = ["Bộ nhớ của bạn từ các round trước:"]
        for mem in reversed(memories):  # chronological order
            sentiment_icon = {"positive": "😊", "negative": "😟", "neutral": "😐"}.get(
                mem.get("sentiment", "neutral"), "😐"
            )
            lines.append(f"  {sentiment_icon} {mem['text']}")

        return "\n".join(lines)

    def get_all_agent_memories(self, agent_id: str) -> List[Dict]:
        """Get ALL memories for an agent (for survey/report use)."""
        return self.recall_memories(agent_id, limit=100, min_importance=0)

    # ── Stats & Cleanup ──

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics for this simulation."""
        graph = self._get_graph()
        try:
            agent_result = graph.query(
                "MATCH (a:Agent {sim_id: $sid}) RETURN count(a)",
                params={"sid": self.sim_id},
            )
            mem_result = graph.query(
                "MATCH (a:Agent {sim_id: $sid})-[:REMEMBERS]->(m:Memory) RETURN count(m)",
                params={"sid": self.sim_id},
            )
            entity_result = graph.query(
                "MATCH (a:Agent {sim_id: $sid})-[:REMEMBERS]->(m:Memory)-[:ABOUT]->(e:Entity) "
                "RETURN count(DISTINCT e)",
                params={"sid": self.sim_id},
            )
            return {
                "agents": agent_result.result_set[0][0] if agent_result.result_set else 0,
                "memories": mem_result.result_set[0][0] if mem_result.result_set else 0,
                "entities_linked": entity_result.result_set[0][0] if entity_result.result_set else 0,
            }
        except Exception as e:
            logger.warning(f"Memory stats failed: {e}")
            return {"agents": 0, "memories": 0, "entities_linked": 0}

    def clear_memories(self):
        """Clear all memories for this simulation."""
        graph = self._get_graph()
        try:
            graph.query(
                "MATCH (a:Agent {sim_id: $sid})-[r:REMEMBERS]->(m:Memory) "
                "DELETE r, m",
                params={"sid": self.sim_id},
            )
            graph.query(
                "MATCH (a:Agent {sim_id: $sid}) DELETE a",
                params={"sid": self.sim_id},
            )
            logger.info(f"Cleared memories for sim {self.sim_id}")
        except Exception as e:
            logger.warning(f"Memory clear failed: {e}")

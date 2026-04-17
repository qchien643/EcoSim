# EcoSim — UML Sequence Diagram: Agent Lifecycle & Simulation Flow

> **Phạm vi:** Từ lúc khởi tạo môi trường (*Phase 3*) → vòng lặp mô phỏng (*Phase 4*) → kết thúc.
> **Kiến trúc trọng tâm:** Hybrid Edge-LLM — Rule-based + Vector Search thay thế LLM cho mọi quyết định hành động; LLM chỉ dùng cho content creation & reflection.

---

## 1. Tổng quan luồng (Overview)

```mermaid
flowchart LR
    A["📄 Campaign Brief\n(Markdown/JSON)"] --> B["Phase 3\nEnvironment Setup"]
    B --> C["Agent Creation\n& Registration"]
    C --> D["Phase 4\nSimulation Loop\n(N rounds)"]
    D --> E["Phase 5\nReport Generation"]

    subgraph B_sub["Phase 3 — Setup"]
        B1[Campaign Knowledge Pipeline] --> B2[Platform Init / DB]
        B2 --> B3[ChromaDB Feed Init]
        B3 --> B4[FalkorDB Graph Init]
    end

    subgraph D_sub["Phase 4 — Per Round"]
        D1[Cognitive Prep] --> D2[Feed Recommendation]
        D2 --> D3[Rule-based Decision]
        D3 --> D4[Action Execution]
        D4 --> D5[Memory Update]
        D5 --> D6["Graph Memory (Background)"]
    end
```

---

## 2. Sơ đồ UML Sequence: Phase 3 — Khởi tạo môi trường & Agent

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 Researcher
    participant RS as run_simulation.py<br/>(Orchestrator)
    participant CKP as CampaignKnowledgePipeline<br/>(campaign_knowledge.py)
    participant LLM_H as LLM (GPT-4o-mini)<br/>High-tier
    participant FDB as FalkorDB<br/>(Knowledge Graph)
    participant PLT as Platform (OASIS)
    participant DB as SQLite<br/>(oasis_simulation.db)
    participant CDB as ChromaDB<br/>(Vector Feed Store)
    participant AG as AgentsGenerator
    participant SA as SocialAgent[0..N]<br/>(agent.py)

    Note over User,SA: ═══ PHASE 3: ENVIRONMENT SETUP ═══

    User->>RS: run_simulation(config, campaign_doc, agent_csv)
    activate RS

    RS->>CKP: pipeline.run(campaign_brief.md)
    activate CKP
    CKP->>CKP: Stage 1 — CampaignDocumentParser.parse()
    Note right of CKP: Split by Markdown headers<br/>Returns List[DocumentSection]

    loop For each DocumentSection
        CKP->>LLM_H: analyze(section) — extract entities & facts
        LLM_H-->>CKP: AnalyzedSection (summary, entities[], facts[])
    end

    CKP->>FDB: connect() then graphiti.build_indices()
    loop For each AnalyzedSection
        CKP->>FDB: add_episode(name, body, group_id)
    end
    CKP-->>RS: stats {episodes_written, entities, facts}
    deactivate CKP

    RS->>PLT: make(env_path) → env
    activate PLT
    PLT->>DB: CREATE TABLE user, post, follow, rec, comment, like
    PLT-->>RS: env (Platform + Channel)
    deactivate PLT

    RS->>CDB: InterestFeedEngine.initialize()
    Note right of CDB: Load all-MiniLM-L6-v2 (384-dim)<br/>Create ChromaDB collection "posts"

    RS->>PLT: Monkey-patch update_rec_table()
    Note right of PLT: Replace default RecSys with<br/>get_personalized_feed()

    RS->>AG: generate_agents(agent_csv, channel, model)
    activate AG

    loop For each row in agents.csv [0..N-1]
        AG->>AG: Build UserInfo(username, bio, persona, mbti, gender, age)
        AG->>SA: SocialAgent(agent_id, user_info, channel, model, available_actions)
        activate SA
        Note right of SA: Inherits ChatAgent (CAMEL)<br/>Builds system prompt from UserInfo<br/>Registers action_tools (FunctionTool)
        SA-->>AG: agent instance
        deactivate SA
        AG->>AG: agent_graph.add_agent(agent)
    end

    AG->>DB: INSERT INTO user batch
    AG->>DB: INSERT INTO follow batch
    AG->>DB: INSERT INTO post batch (previous_tweets)
    AG-->>RS: AgentGraph (social network)
    deactivate AG

    Note over RS,SA: ✅ N agents registered, campaign facts in FalkorDB,<br/>ChromaDB initialized, SQLite schema ready
```

---

## 3. Sơ đồ UML Sequence: Phase 4 — Vòng lặp mô phỏng (1 Agent, 1 Round)

```mermaid
sequenceDiagram
    autonumber
    participant RS as run_simulation.py<br/>(Loop Controller)
    participant COG as AgentCognition<br/>(agent_cognition.py)
    participant MEM as AgentMemory<br/>(FIFO Buffer max=5)
    participant MBTI as MBTIProfiler
    participant DRIFT as InterestVectorTracker
    participant FEED as InterestFeedEngine<br/>(interest_feed.py)
    participant CDB as ChromaDB
    participant GCH as GraphCognitiveHelper
    participant FDB as FalkorDB
    participant SA as SocialAgent[i]
    participant PLT as Platform (OASIS)
    participant DB as SQLite
    participant LLM_L as LLM (GPT-4o-mini)<br/>(CAMEL ChatAgent)
    participant BGW as BackgroundWorker<br/>(async, non-blocking)

    Note over RS,BGW: ═══ PHASE 4 — ROUND r FOR AGENT i ═══

    RS->>COG: prepare_agent_context(agent_i, round=r)
    activate COG

    COG->>MEM: get_recent_rounds(n=5)
    MEM-->>COG: [RoundSummary_r-5 ... RoundSummary_r-1]

    COG->>MBTI: get_modifiers(mbti_type)
    Note right of MBTI: e.g. INTJ: Openness=0.8,<br/>Social=0.3, Deliberation=0.9
    MBTI-->>COG: {boost_scale, decay_rate, reflection_freq}

    COG->>DRIFT: get_interest_vector(agent_id)
    DRIFT-->>COG: interest_embedding [384-dim]

    COG->>GCH: get_social_context(agent_id)
    activate GCH
    GCH->>FDB: MATCH entity graph for agent
    FDB-->>GCH: social_facts[], interest_entities[]
    GCH-->>COG: social_context_str
    deactivate GCH

    COG-->>RS: {memory_ctx, mbti_mods, interest_vec, social_ctx}
    deactivate COG

    RS->>PLT: get_rec_posts(agent_id) — patched call
    activate PLT
    PLT->>FEED: get_personalized_feed(agent_id, interest_vec, k=20)
    activate FEED
    FEED->>CDB: query(interest_vec, n_results=50)
    Note right of CDB: ANN search with all-MiniLM-L6-v2
    CDB-->>FEED: candidates[{post_id, distance, metadata}]
    FEED->>FEED: re_rank: alpha*semantic + beta*popularity + gamma*recency
    FEED-->>PLT: ranked_posts[top-20]
    deactivate FEED
    PLT-->>RS: feed_posts[top-20]
    deactivate PLT

    RS->>FEED: decide_agent_actions(agent_id, feed_posts, interest_vec)
    activate FEED
    loop For each post in feed_posts
        FEED->>CDB: compute_distance(post_vec, interest_vec)
        CDB-->>FEED: semantic_distance d
        FEED->>FEED: apply MBTI probability modifier
        Note right of FEED: d < 0.3 → like + maybe comment<br/>d < 0.5 → probabilistic like<br/>d >= 0.5 → do_nothing
    end
    FEED-->>RS: action_plan[{post_id, action, prob}]
    deactivate FEED

    RS->>SA: execute_actions(action_plan)
    activate SA

    loop For each (post_id, action) in action_plan
        alt action == "like"
            SA->>PLT: env.action.like(post_id)
            PLT->>DB: UPDATE post SET num_likes += 1
        else action == "comment"
            SA->>LLM_L: _generate_comment(model, persona, post_content)
            LLM_L-->>SA: comment_text
            SA->>PLT: env.action.comment(post_id, comment_text)
            PLT->>DB: INSERT INTO comment
        else action == "create_post"
            SA->>LLM_L: _generate_post_content(model, persona, topic)
            LLM_L-->>SA: post_content
            SA->>PLT: env.action.create_post(post_content)
            PLT->>DB: INSERT INTO post
            SA->>CDB: add_post(post_id, embed(post_content))
        else action == "do_nothing"
            Note right of SA: No platform call
        end
    end

    SA-->>RS: executed_actions[]
    deactivate SA

    RS->>MEM: record_actions(round=r, actions=executed_actions)
    Note right of MEM: Buffer latest round, flush oldest if len > 5

    RS->>DRIFT: update_interests(agent_id, executed_actions, mbti_mods)
    activate DRIFT
    loop For each liked or commented post
        DRIFT->>DRIFT: boost(topic_vector, boost_scale × engagement_weight)
    end
    DRIFT->>DRIFT: decay_all(decay_rate)
    DRIFT-->>RS: updated_interest_embedding
    deactivate DRIFT

    opt round mod reflection_freq == 0
        RS->>COG: trigger_reflection(agent_id, memory_history)
        activate COG
        COG->>MEM: get_all_rounds()
        MEM-->>COG: full_history[last 5 rounds]
        COG->>LLM_L: reflection.maybe_reflect(agent_id, round, memory, model, base_persona)
        LLM_L-->>COG: reflection_insight
        COG->>DRIFT: update_from_reflection(insight_embedding)
        COG-->>RS: reflection_done
        deactivate COG
    end

    RS-)BGW: queue_episode(agent_id, round=r, actions)
    Note right of BGW: Fire-and-forget — does NOT block loop

    activate BGW
    BGW->>BGW: build_episode_text(actions)
    BGW->>FDB: graphiti.add_episode(name, body, group_id)
    Note right of FDB: SDK extracts entities and edges<br/>into FalkorDB knowledge graph
    deactivate BGW

    Note over RS,BGW: ✅ Round r complete for Agent i — next agent or next round
```

---

## 4. Sơ đồ UML Sequence: Crisis Injection

```mermaid
sequenceDiagram
    autonumber
    participant EXT as External Config<br/>(crisis_events.json)
    participant RS as run_simulation.py
    participant PLT as Platform (OASIS)
    participant DB as SQLite
    participant CDB as ChromaDB

    Note over EXT,CDB: ═══ CRISIS INJECTION at round R_crisis ═══

    RS->>EXT: load_crisis_event(round=R_crisis)
    EXT-->>RS: {type, content, target_agents, intensity}

    alt type == "viral_post"
        RS->>PLT: inject_post(content, author="system")
        PLT->>DB: INSERT INTO post (boosted=True)
        RS->>CDB: add_post(crisis_post_id, embed(content))
    else type == "trending_topic"
        RS->>CDB: update_topic_weights(topic_vec, boost=3x)
    else type == "platform_event"
        RS->>PLT: broadcast_notification(all_agents, event_msg)
        PLT->>DB: INSERT INTO notification
    end

    Note over RS,CDB: Next round — all agents see crisis<br/>in personalized feed → organic behavioral shift
```

---

## 5. Sơ đồ UML Sequence: Kết thúc → Phase 5 Report

```mermaid
sequenceDiagram
    autonumber
    participant RS as run_simulation.py
    participant BGW as BackgroundWorker
    participant FDB as FalkorDB
    participant DB as SQLite
    participant RPT as ReportEngine<br/>(Phase 5)
    participant LLM_H as LLM (GPT-4o-mini)

    Note over RS,LLM_H: ═══ SIMULATION FINALIZATION ═══

    RS->>RS: All N_rounds complete
    RS->>BGW: flush_all() — wait for pending writes
    activate BGW
    BGW->>FDB: Drain episode queue
    BGW-->>RS: Graph memory fully synced
    deactivate BGW

    RS->>DB: COMMIT final state

    RS->>DB: SELECT traces from post, like, comment, follow
    DB-->>RS: Raw interaction data

    RS->>FDB: MATCH full graph snapshot
    FDB-->>RS: Knowledge graph

    RS->>RPT: generate_report(traces, graph, config)
    activate RPT

    RPT->>LLM_H: ReACT reasoning loop
    Note right of LLM_H: Tool 1: query_db(SQL)<br/>Tool 2: query_graph(Cypher)<br/>Tool 3: sentiment_analysis()<br/>Tool 4: topic_clustering()
    LLM_H-->>RPT: Insights, KPIs, Narrative

    RPT-->>RS: campaign_report.pdf / .json
    deactivate RPT

    Note over RS,LLM_H: ✅ Artifacts: oasis_simulation.db, FalkorDB graph, campaign_report
```

---

## 6. Bản đồ thành phần (Component Map)

| Layer | Component | Vai trò | Công nghệ |
|---|---|---|---|
| **Orchestration** | `run_simulation.py` | Điều phối toàn bộ pipeline | Python asyncio |
| **Agent Runtime** | `SocialAgent` (agent.py) | Thực thể AI nhân vật | CAMEL `ChatAgent` |
| **Cognitive** | `AgentMemory` | Bộ nhớ ngắn hạn (5 rounds) | FIFO Buffer (in-memory) |
| **Cognitive** | `MBTIProfiler` | Điều chỉnh hành vi theo kiểu nhân cách | Lookup Table |
| **Cognitive** | `InterestVectorTracker` | Theo dõi sự thay đổi sở thích | Numpy vector ops |
| **Cognitive** | `AgentReflection` | Phản chiếu định kỳ → tiến hóa nhân cách | LLM (GPT-4o-mini) |
| **Recommendation** | `InterestFeedEngine` | Gợi ý nội dung cá nhân hóa | ChromaDB + all-MiniLM-L6-v2 |
| **Decision** | `decide_agent_actions()` | Quyết định hành động không cần LLM | Rule-based + thresholds |
| **Platform** | `Platform` (OASIS) | Mạng xã hội ảo | SQLite + OASIS framework |
| **Long-term Memory** | `GraphCognitiveHelper` | Truy vấn tri thức xã hội | FalkorDB + Graphiti SDK |
| **Long-term Memory** | `BackgroundWorker` | Ghi log vào graph (async) | asyncio Queue + Graphiti |
| **Knowledge Ingestion** | `CampaignKnowledgePipeline` | Nạp tài liệu chiến dịch vào graph | LLM (GPT-4o-mini) + FalkorDB |
| **LLM** | GPT-4o-mini | Tất cả tác vụ: campaign analysis, post gen, comment gen, reflection, report | OpenAI API (duy nhất) |

---

## 7. Luồng quyết định Rule-based

```mermaid
flowchart TD
    A["Post arrives in feed"] --> B["Compute semantic distance\nd = dist(post_vec, interest_vec)"]
    B --> C{d < STRONG_THRESHOLD = 0.3?}
    C -- Yes --> D["Like (90%) + Comment (40%)\nGPT-4o-mini generates text"]
    C -- No --> E{d < MODERATE_THRESHOLD = 0.5?}
    E -- Yes --> F["Like with P = f(MBTI)"]
    E -- No --> G["do_nothing (scroll past)"]
    D --> H["Boost interest_vec toward topic"]
    F --> H
    G --> I["Decay interest_vec at MBTI rate"]
    H --> J["Queue → BackgroundWorker → FalkorDB"]
    I --> J
```

---

## 8. Ghi chú thiết kế quan trọng

> **Tại sao không dùng LLM cho mọi hành động?**
> 1,000 agents × 10 rounds × 20 posts = 200,000 decisions/run.
> GPT-4o-mini ≈ $0.15/1M token → chi phí không khả thi.
> Giải pháp: Rule-based + ChromaDB → **$0 cost** cho quyết định.
> LLM chỉ dùng khi cần sáng tạo ngôn ngữ (comment, reflection).

> **FalkorDB vs Neo4j:** FalkorDB tương thích Cypher nhưng chạy in-process qua Redis protocol, không cần JVM.
> Graphiti SDK tự động build entity relationship từ natural language episodes.

> **Thứ tự thực thi per-agent per-round:**
> 1. Cognitive Prep (Memory + MBTI + Drift + Graph Context)
> 2. Feed Recommendation (ChromaDB ANN + Re-ranking)
> 3. Rule-based Decision (threshold comparison)
> 4. Action Execution (Platform call ± LLM)
> 5. Memory Update (FIFO buffer)
> 6. Interest Drift Update (vector ops)
> 7. Reflection (every K rounds, via LLM)
> 8. Graph Memory write (background, non-blocking)

# Kiến Trúc EcoSim — Phân Tích Kỹ Thuật Chuyên Sâu

> **Trạng thái**: Được xác minh trực tiếp từ source code — không có thông tin suy diễn.  
> **Phạm vi**: Toàn bộ phần tự thiết kế (`agent_cognition.py`, `interest_feed.py`) **và** nhân OASIS gốc mà chúng tích hợp vào.

---

## 1. Tổng quan — Hai tầng kiến trúc

EcoSim gồm 2 tầng rõ ràng:

| Tầng | Source | Vai trò |
|---|---|---|
| **OASIS Framework** | `oasis/oasis/` — CAMEL-AI gốc, **không sửa đổi** | Platform mạng xã hội (SQLite, ActionDispatch, Channel, AgentGraph) |
| **EcoSim Cognitive Layer** | `oasis/agent_cognition.py`, `oasis/interest_feed.py` — **tự viết** | Nhận thức agent, sở thích, MBTI, bộ nhớ, phản chiếu |
| **Simulation Loop** | `oasis/run_simulation.py` — **tự viết** | Kết nối hai tầng, chạy vòng lặp mô phỏng |

```
┌─────────────────────────────────────────────────────────────┐
│                    run_simulation.py                         │
│                                                              │
│  ┌────────────────────────┐   ┌────────────────────────┐    │
│  │  EcoSim Cognitive Layer│   │   OASIS Framework       │   │
│  │                        │   │                         │   │
│  │  agent_cognition.py    │   │  OasisEnv               │   │
│  │  ├─ AgentMemory        │   │  ├─ Platform (SQLite)   │   │
│  │  ├─ MBTIModifiers      │◄──┤  ├─ Channel (Queue)     │   │
│  │  ├─ InterestVectorTrack│   │  ├─ AgentGraph (igraph) │   │
│  │  ├─ AgentReflection    │   │  └─ agents_generator    │   │
│  │  └─ GraphCognitiveHelp │   │                         │   │
│  │                        │   │  (monkey-patched via    │   │
│  │  interest_feed.py      │───►  update_rec_table)      │   │
│  │  ├─ PostIndexer        │   │                         │   │
│  │  ├─ EngagementTracker  │   └────────────────────────┘   │
│  │  └─ decide_agent_action│                                  │
│  └────────────────────────┘                                  │
│                                                              │
│  FalkorDB (BackgroundWorker)  ChromaDB (in-memory)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Phần tự thiết kế — EcoSim Cognitive Layer

### 2.1 `agent_cognition.py` — 5 Phase nhận thức

#### Phase 1: `AgentMemory` — Bộ nhớ ngắn hạn theo vòng

```python
class AgentMemory:
    MAX_BUFFER = 5  # Giữ last 5 round summaries

    # agent_id → deque of summary strings
    _buffers: Dict[int, deque]
    # agent_id → list of raw actions this round (sensory)
    _current_round: Dict[int, list]
```

**Cơ chế:**

| Phương thức | Chức năng |
|---|---|
| `record_action(agent_id, action_type, content_preview)` | Ghi raw action vào sensory buffer của round hiện tại |
| `end_round(round_num)` | Flush sensory buffer → compact summary string, lưu vào FIFO deque |
| `get_context(agent_id)` | Trả chuỗi "Your recent activity:\nRound X: ..." để inject vào LLM prompt |

**Ví dụ output:**
```
Your recent activity:
Round 3: posted "Excited about deals!"; liked a post
Round 4: commented "Great insight"; shared a post
```

**Tham chiếu**: RecAgent (ACL 2024) — sensory → short-term memory layer.

---

#### Phase 2: MBTI Behavioral Modifiers

```python
_MBTI_DIMENSION_MODIFIERS = {
    "E": {"post_mult": 1.2, "comment_mult": 1.3},  # Extraversion
    "I": {"post_mult": 0.8, "comment_mult": 0.7},   # Introversion
    "F": {"like_mult": 1.2},                         # Feeling
    "T": {"like_mult": 0.9},                         # Thinking
    "P": {"feed_mult": 1.2},                         # Perceiving
    "J": {"feed_mult": 0.9},                         # Judging
    "N": {"reflection_boost": 1.3},                  # iNtuition
    "S": {"reflection_boost": 0.8},                  # Sensing
}
```

`get_behavior_modifiers("ENFJ")` → `{post_mult:1.2, comment_mult:1.3, like_mult:1.2, feed_mult:0.9, reflection_boost:1.3}`

Kết quả được truyền vào `decide_agent_actions()` như `comment_mult`, `like_mult`, `feed_mult`.

---

#### Phase 3a: `CognitiveTraits` — Nhân cách nhận thức

```python
class CognitiveTraits:
    conviction: float        # Độ bảo thủ — giữ sở thích cũ lâu
    forgetfulness: float     # Độ hay quên — sở thích cũ phai nhanh
    curiosity: float         # Độ tò mò — tốc độ sinh sở thích mới
    impressionability: float # Độ dễ bị ảnh hưởng — tốc độ boost sở thích
```

Ánh xạ từ MBTI:

| MBTI | conviction | forgetfulness | curiosity | impressionability |
|---|---|---|---|---|
| J | 0.80 | - | 0.20 | - |
| P | 0.40 | - | 0.45 | - |
| S | - | 0.10 | - | - |
| N | - | 0.20 | - | - |
| F | - | - | - | 0.25 |
| T | - | - | - | 0.10 |
| E | - | - | +0.10 bonus | - |
| I | - | - | -0.05 bonus | - |

---

#### Phase 3b: `InterestVectorTracker` — Tiến hoá sở thích theo thời gian

**Đây là kiến trúc quan trọng nhất** — mỗi agent có một vector sở thích `Dict[str, InterestItem]` thay đổi qua từng round.

```python
class InterestItem:
    keyword: str          # Từ khoá sở thích
    weight: float         # Trọng số [0.0, 1.0]
    source: str           # "profile"|"drift"|"graph"|"campaign"
    first_seen: int       # Round khởi tạo
    last_engaged: int     # Round tương tác gần nhất
    engagement_count: int # Tổng số lần tương tác
```

**Quy tắc cập nhật sau mỗi round** (`update_after_round`):

```
1. BOOST:  interest xuất hiện trong nội dung đã tương tác
           weight += impressionability  (cap 1.0)

2. DECAY:  interest không được kích hoạt
           weight *= (1.0 - forgetfulness)

3. FLOOR:  interest nguồn "profile" có sàn tối thiểu
           weight = max(conviction * 0.3, weight)

4. NEW:    từ khoá mới từ KeyBERT extraction
           weight = curiosity (ban đầu)
           source = "drift"

5. GRAPH:  thực thể từ FalkorDB graph queries
           weight = curiosity * 0.7
           source = "graph"

6. PRUNE:  weight < 0.03 và source != "profile" → xóa
```

**KeyBERT extraction pipeline** (`_extract_keyphrases`):

```python
# 1. Clean social text (URL, @mention, #hashtag, emoji removal)
cleaned = _clean_social_text(content)

# 2. KeyBERT với all-MiniLM-L6-v2 + MMR diversification
keywords = kw_model.extract_keywords(
    cleaned,
    keyphrase_ngram_range=(1, 3),
    stop_words='english',
    use_mmr=True,          # Max Marginal Relevance — chọn đa dạng, không trùng
    diversity=0.5,
    top_n=max_phrases + 2,
)

# 3. Filter: score > 0.05, reject generic single words
# 4. Fallback: N-gram extraction nếu KeyBERT không khả dụng
```

> **Tại sao dùng MMR?** Đảm bảo keyphrases trả về cover nhiều chủ đề đa dạng thay vì nhiều biến thể của cùng một keyword.

**Giao tiếp với `PostIndexer`** qua `get_search_queries()`:

```python
def get_search_queries(self, agent_id, n=5) → List[Tuple[str, float]]
# Ví dụ: [("shopee flash sale", 0.85), ("e-commerce deals", 0.70)]
# → truyền vào PostIndexer.multi_query_search(queries, n_results)
```

---

#### Phase 4: `AgentReflection` — Phản chiếu định kỳ qua LLM

```python
class AgentReflection:
    MAX_INSIGHTS = 3  # Giữ 3 insights gần nhất
    interval: int     # Reflect mỗi N rounds (default 3)

    # agent_id → list of insight strings
    _insights: Dict[int, list]
```

**`maybe_reflect(agent_id, round_num, memory, model, base_persona)`**:

- Chỉ trigger khi `round_num % interval == 0` **và** agent có memory context
- Dùng `camel.agents.ChatAgent` với GPT-4o-mini
- Prompt: `base_persona[:300] + memory.get_context() + graph_context`
- Trả về 1 câu insight về sự thay đổi quan điểm/sở thích của agent
- `get_evolved_persona()` = `base_persona + "\n\nRecent reflections: " + insights`

**Base persona KHÔNG bao giờ bị modify** — insights chỉ được layer thêm.

**Tham chiếu**: Generative Agents (Stanford) — importance-triggered reflection.

---

#### Phase 5: `GraphCognitiveHelper` — Tích hợp KG vào nhận thức

```python
class GraphCognitiveHelper:
    falkor_host: str   # FalkorDB host
    falkor_port: int   # FalkorDB port
    group_id: str      # Graphiti group ID (namespace)
    _searcher: FalkorGraphSearcher  # lazy-init on first query
```

| Phương thức | Chức năng |
|---|---|
| `get_social_context(agent_name, num_results)` | Query graph "What has X done and who did they interact with?" → context string cho LLM prompt |
| `get_interest_entities(agent_name, num_results)` | Lấy entity nodes liên quan → feed vào `InterestVectorTracker` như "graph" source |

---

### 2.2 `interest_feed.py` — Feed cá nhân hoá không dùng LLM

**Triết lý thiết kế**: Thay thế toàn bộ LLM-based action decisions bằng rule-based pipeline để giảm chi phí API call.

#### `PostIndexer` — ChromaDB semantic index

```python
class PostIndexer:
    _client: chromadb.Client()           # in-memory
    _collection: Collection              # hnsw:space=cosine
    _indexed_ids: set                    # dedup tracker
    # Model: all-MiniLM-L6-v2 (ChromaDB default, chạy local)
```

**Các phương thức chính:**

| Phương thức | Chức năng |
|---|---|
| `index_post(post_id, content, author_id, round_num)` | Thêm 1 post vào ChromaDB (idempotent bằng doc_id) |
| `index_from_db(db_path)` | Bulk index tất cả posts từ OASIS SQLite |
| `query_by_interests(interests_text, n_results)` | Single-query semantic search → `List[(post_id, cosine_distance)]` |
| `multi_query_search(interest_queries, n_results)` | **Multi-query với Weighted RRF** — core của feed personalization |
| `query_unified(interests_text, profiles, engagement_tracker, agent_id)` | Unified: semantic + popularity bonus + comment decay → single re-ranked list |

**Multi-query Weighted Reciprocal Rank Fusion (RRF):**

```python
def multi_query_search(self, interest_queries: List[Tuple[str, float]], n_results=10):
    # interest_queries: [("shopee sale", 0.85), ("e-commerce", 0.70)]
    k = 60  # RRF constant
    all_scores = {}

    for query_text, weight in interest_queries:
        results = self.query_by_interests(query_text, n_results * 2)
        for rank, (post_id, distance) in enumerate(results):
            rrf_score = weight / (k + rank)       # weight tỷ lệ với sở thích agent
            all_scores[post_id] += rrf_score      # cộng dồn từ nhiều queries

    return sorted(all_scores.items(), key=lambda x: -x[1])[:n_results]
```

> Sở thích có trọng số cao hơn → đóng góp RRF score cao hơn → post liên quan lên top.

**Unified query với re-ranking:**

```python
def query_unified(self, interests_text, profiles, engagement_tracker, agent_id, n_results):
    # Step 1: Query ChromaDB với N lớn (3x feed_size hoặc tất cả)
    raw_results = self.query_by_interests(interests_text, n_results*3)

    # Step 2: Re-rank theo 3 yếu tố
    for post_id, semantic_dist in raw_results:
        # a. Popularity bonus: tác giả nhiều follower → khoảng cách giảm
        followers = author_followers.get(author_id, 0)
        pop_bonus = min(0.25, followers / 20000.0)

        # b. Comment decay: post đã comment nhiều → khoảng cách tăng
        decay = engagement_tracker.get_decay(agent_id, post_id)

        final_dist = max(0.0, semantic_dist - pop_bonus + decay)

    # Step 3: Sort theo final_dist, return top-K
```

---

#### `EngagementTracker` — Giảm lặp comment

```python
class EngagementTracker:
    DECAY_PER_COMMENT = 0.3   # +0.3 cosine distance mỗi lần comment

    _comments: Dict[int, Dict[int, int]]  # agent_id → {post_id: count}

    def record_comment(agent_id, post_id)
    def get_decay(agent_id, post_id) → comment_count * 0.3
```

---

#### `decide_agent_actions()` — Rule-based action engine

```
Cosine distance thresholds (all-MiniLM-L6-v2):
  < 0.7  = STRONG match
  0.7–1.0= MODERATE match
  1.0–1.3= WEAK match
  > 1.3  = NO match
```

```python
def decide_agent_actions(profile, post_indexer, ...):
    # 1. Build interest text từ profile + drift
    interest_text = build_interest_text(profile, drift_text=drift_text)

    # 2. Get feed size từ daily_hours × feed_mult(MBTI)
    feed_size = get_feed_size(daily_hours, feed_mult)

    # 3. Unified query: semantic + popularity + comment decay
    matches = post_indexer.query_unified(...)

    # 4. Convert distances → actions theo threshold
    for post_id, distance in matches:
        if distance < STRONG_THRESHOLD (0.7):
            like_prob  = 1.0 × activity_mult × like_mult   # MBTI
            comment_prob=0.50 × activity_mult × comment_mult
        elif distance < MODERATE_THRESHOLD (1.0):
            like_prob  = 0.75, comment_prob = 0.15
        elif distance < WEAK_THRESHOLD (1.3):
            like_prob  = 0.30, comment_prob = 0.0
        else:
            like_prob  = 0.10, comment_prob = 0.0

        if random() < like_prob    → {"type":"like_post", "post_id": pid}
        if random() < comment_prob → {"type":"create_comment", "post_id": pid, "needs_llm": True}

    # 5. Guarantee: nếu không có action nào, fallback like post tốt nhất
```

> **`needs_llm: True`** đánh dấu comment cần gửi sang LLM để sinh nội dung thực sự.

---

#### `build_interest_text()` — Xây query string cho ChromaDB

Priority order khi build query:

1. `profile["interests"]` — explicit keyword list
2. `specific_domain` + `general_domain`
3. `drift_text` — keywords từ engagement tracking (Phase 3)
4. `campaign_context[:150]`
5. Fallback: 2 câu đầu `original_persona` hoặc `bio[:200]`

---

#### `update_rec_table_with_interests()` — Monkey-patch target

Đây là hàm được dùng để **thay thế** `Platform.update_rec_table` của OASIS:

```python
def update_rec_table_with_interests(db_path, post_indexer, profiles,
                                    interest_drifts=None, interest_vectors=None):
    # Xóa toàn bộ rec table
    cursor.execute("DELETE FROM rec")

    insert_values = []
    for agent_id, profile in enumerate(profiles):
        feed_size = get_feed_size(profile["daily_hours"])

        if interest_vectors:  # Phase 3: multi-query với weighted RRF
            queries = interest_vectors.get_search_queries(agent_id, n=5)
            results = post_indexer.multi_query_search(queries, n_results=feed_size)
            post_ids = [pid for pid, _ in results]
        else:                 # Fallback: single query
            post_ids = post_indexer.query_post_ids(interest_text, n_results=feed_size)

        insert_values.extend([(agent_id, pid) for pid in post_ids])

    # Batch INSERT — nhanh hơn loop INSERT từng dòng
    cursor.executemany("INSERT INTO rec (user_id, post_id) VALUES (?, ?)", insert_values)
```

---

## 3. Nhân OASIS — Các thành phần framework gốc

### 3.1 `Channel` — Hàng đợi bất đồng bộ

```
Channel
├── receive_queue: asyncio.Queue   # Agent → Platform
└── send_dict: AsyncSafeDict       # Platform → Agent (keyed by message_id UUID)
```

| Phương thức | Hướng | Cơ chế |
|---|---|---|
| `write_to_receive_queue(data)` | Agent → Platform | Enqueue + trả `message_id` (UUID) |
| `receive_from()` | Platform ← Queue | `await queue.get()` |
| `send_to(message)` | Platform → Agent | Lưu vào dict bằng `message_id` |
| `read_from_send_queue(message_id)` | Agent ← Dict | Polling mỗi 0.1s |

---

### 3.2 `Platform` — Mạng xã hội trên SQLite

**File**: `oasis/oasis/social_platform/platform.py`

Action dispatch pattern (dynamic, không có if/elif dài dòng):

```python
# ActionType.value trùng với tên method
# Ví dụ: ActionType.CREATE_POST.value == "create_post"
action_function = getattr(self, action.value, None)
result = await action_function(**params)
```

**Constructor parameters quan trọng:**

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `recsys_type` | `"reddit"` | Thuật toán rec gốc (bị monkey-patch bởi EcoSim) |
| `max_rec_post_len` | `2` | Số posts tối đa trong rec buffer / agent |
| `refresh_rec_post_count` | `1` | Posts trả về mỗi lần `refresh` action |
| `following_post_count` | `3` | Posts từ following hiện |

---

### 3.3 `OasisEnv` — Orchestrator

```python
async def step(self, actions):
    # 1. Update rec table (monkey-patched → ChromaDB)
    await self.platform.update_rec_table()

    # 2. Gather tất cả agent tasks song song
    await asyncio.gather(*[
        self._perform_llm_action(agent)  # hoặc manual
        for agent, action in actions.items()
    ])
```

`asyncio.Semaphore(128)` bọc mỗi LLM call để kiểm soát concurrency.

---

### 3.4 `AgentGraph` — Mạng quan hệ xã hội

- Backend mặc định: `igraph` — directed graph, init từ follow data
- Không cập nhật động khi agent follow/unfollow trong simulation (known limitation)
- FalkorDB (Graphiti) đảm nhiệm memory graph động song song

---

## 4. Database Schema (SQLite)

| Bảng | Mô tả |
|---|---|
| `user` | Profile (user_id, agent_id, user_name, name, bio, num_followers, num_followings) |
| `post` | Bài đăng (post_id, user_id, content, num_likes, num_dislikes, num_shares) |
| `like` / `dislike` | Lịch sử reaction |
| `comment` | Bình luận (comment_id, post_id, user_id, content) |
| `follow` / `mute` | Quan hệ xã hội |
| `rec` | Recommendation buffer (user_id, post_id) — bị xóa và insert lại mỗi step |
| `trace` | Audit log toàn bộ actions (action, info JSON, created_at) |
| `report` / `product` | Báo cáo & e-commerce |

`PRAGMA synchronous = OFF` được bật để tăng tốc write.

---

## 5. So sánh EcoSim vs OASIS gốc

| Tính năng | OASIS gốc | EcoSim (bổ sung) |
|---|---|---|
| Recommendation | Random/Twitter/TWHIN/Reddit | **ChromaDB semantic + Weighted RRF multi-query** |
| Interest model | Không có | **InterestVectorTracker** (CognitiveTraits, 5-rule update) |
| Keyphrase extraction | Không có | **KeyBERT + MMR diversification** (all-MiniLM-L6-v2) |
| MBTI behavior | Không có | **8-dimension modifier** (post/comment/like/feed/reflection) |
| Agent memory | CAMEL ChatAgent in-process | + `AgentMemory` FIFO buffer (5 rounds) |
| Reflection | Không có | **AgentReflection** — GPT-4o-mini, periodic (mỗi N rounds) |
| Graph memory | Không có | **FalkorDB (Graphiti)** — async write qua BackgroundWorker |
| Graph cognition | Không có | **GraphCognitiveHelper** — query graph → inject vào prompt |
| Action decision | LLM every action (đắt) | **Rule-based** với cosine threshold (LLM chỉ khi comment) |
| Feed diversity | Không có | **EngagementTracker** comment decay (DECAY_PER_COMMENT=0.3) |
| Popularity bias | Không có | **Follower-based bonus** (max 0.25 distance reduction) |

---

## 6. Vòng lặp mô phỏng đầy đủ (một round)

```
run_simulation.py
       │
       ▼
[PREP] Trước round:
  - post_indexer.index_from_db(db_path)      → index posts mới vào ChromaDB
  - interest_vectors.get_search_queries()     → lấy weighted interest queries
  - update_rec_table_with_interests()         → fill bảng rec (monkey-patch target)
       │
       ▼
[COGNITION] Chuẩn bị agent context:
  - memory.get_context(agent_id)              → "Your recent activity: ..."
  - mbti_mods = get_behavior_modifiers(mbti)  → multipliers
  - drift_text = interest_vectors.get_drift_text()
  - graph_ctx = GraphCognitiveHelper.get_social_context()  [nếu enabled]
       │
       ▼
[DECISION] Rule-based action selection:
  - decide_agent_actions(profile, post_indexer, ...)
    → matches = post_indexer.query_unified(...)
    → threshold-based like/comment probability
    → result: List[{"type":"like_post"|"create_comment", "needs_llm":bool}]
       │
       ▼
[OASIS STEP] OasisEnv.step():
  - asyncio.gather(all agent coroutines)
  - Agent → Channel → Platform → SQLite
  - Channel → Agent (response)
       │
       ▼
[UPDATE] Sau round:
  - memory.record_action() → memory.end_round()
  - interest_vectors.update_after_round(engaged_contents)
    → KeyBERT extract keyphrases → BOOST/DECAY/NEW/PRUNE
  - engagement_tracker.record_comment()
  - BackgroundWorker → FalkorDB write (async, non-blocking)
       │
       ▼ (mỗi N rounds)
[REFLECT] AgentReflection.maybe_reflect():
  - CAMEL ChatAgent (GPT-4o-mini)
  - base_persona + memory + graph_context → 1 insight sentence
  - persona = base_persona + "Recent reflections: ..."
```

---

## 7. Known Limitations & Technical Debt

| Vấn đề | File | Mức độ |
|---|---|---|
| GPT-4o-mini hard-coded, bỏ qua `LLM_MODEL_NAME` env | `run_simulation.py` | 🔴 High |
| AgentGraph không update dynamic khi follow/unfollow | `agent_graph.py` | 🟡 Medium |
| `PRAGMA synchronous = OFF` — mất data khi crash | `platform.py` | 🟡 Medium |
| `InterestVectorTracker` lưu in-memory, không persist | `agent_cognition.py` | 🟡 Medium |
| Không có UI dashboard | - | 🟡 Medium |
| ChromaDB in-memory — mất sau mỗi session | `interest_feed.py` | 🟡 Medium |

---

*Tài liệu được viết lại ngày 2026-04-12, xác minh trực tiếp từ:*  
- `oasis/agent_cognition.py` (980 dòng)  
- `oasis/interest_feed.py` (561 dòng)  
- `oasis/oasis/social_platform/platform.py`, `channel.py`, `recsys.py`  
- `oasis/oasis/social_agent/agent_graph.py`, `agents_generator.py`  
- `oasis/oasis/environment/env.py`

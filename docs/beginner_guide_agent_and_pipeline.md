# Hướng dẫn cho người mới: Agent Profile & Simulation Pipeline

> **Đối tượng:** Người chưa biết gì về EcoSim, muốn hiểu đầy đủ từ đầu.
> **Phong cách:** Giải thích như dạy học — mỗi khái niệm đều có ví dụ thực tế.

---

## Phần 1: Trước tiên — EcoSim là gì?

Hãy tưởng tượng bạn là một nhà nghiên cứu marketing. Bạn muốn biết: **"Nếu tôi đăng chiến dịch quảng cáo lên mạng xã hội, người dùng sẽ phản ứng thế nào?"**

Thực hiện thật thì cần hàng triệu đồng và hàng tháng trời. EcoSim giải quyết bài toán này bằng cách:

> **Tạo ra hàng ngàn người dùng ảo (agent) với tính cách, sở thích, độ tuổi khác nhau → cho họ "sống" trên một mạng xã hội giả lập → quan sát hành vi của họ.**

Các agent này không phải bot đơn giản — mỗi người có cá tính riêng, nhớ những gì đã xảy ra, thay đổi sở thích theo thời gian, và phản ứng khác nhau với cùng một bài đăng.

---

## Phần 2: Agent Profile — Khai sinh cho một người dùng ảo

Mỗi agent được định nghĩa bởi một **profile** — giống như hồ sơ cá nhân trên mạng xã hội thật. Dưới đây là một profile mẫu thực tế trong EcoSim:

```json
{
  "realname": "Emma Hayes",
  "username": "emma_logistics_guru",
  "bio": "Passionate about transportation and logistics | ENFJ | Always seeking new connections",
  "persona": "Emma Hayes là một cô gái 19 tuổi đam mê logistics với tính cách ENFJ...",
  "age": 19,
  "gender": "female",
  "mbti": "ENFJ",
  "country": "UK",
  "profession": "Transportation, Distribution & Logistics",
  "interested_topics": ["Culture & Society", "Business"]
}
```

### 2.1 Giải thích từng tham số

---

#### `realname` — Tên thật
```json
"realname": "Emma Hayes"
```

**Bài toán giải quyết:** AI cần biết tên agent để tạo ra nội dung tự nhiên. Khi Emma viết comment, nó sẽ được đặt trong ngữ cảnh "Emma, một cô gái logistics 19 tuổi" chứ không phải "Agent #7".

**Dùng ở đâu:**
- Tạo ra prompt cho LLM: *"Bạn là Emma Hayes, 19 tuổi..."*
- Ghi vào FalkorDB Knowledge Graph: *"Emma liked a post about sustainability"*
- Hiển thị trong báo cáo kết quả simulation

---

#### `username` — Tên đăng nhập trên nền tảng
```json
"username": "emma_logistics_guru"
```

**Bài toán giải quyết:** Đây là định danh duy nhất trên "mạng xã hội" giả lập (SQLite database). Giống như handle Twitter `@emma_logistics_guru`.

**Dùng ở đâu:**
- Lưu vào bảng `user` trong SQLite: `INSERT INTO user (user_name, ...) VALUES ('emma_logistics_guru', ...)`
- Hiển thị trong bài đăng và comment của agent

---

#### `bio` — Mô tả ngắn (dòng bio)
```json
"bio": "Passionate about transportation and logistics | ENFJ | Always seeking new connections"
```

**Bài toán giải quyết:** Bio là **bản tóm tắt 1 câu** về agent — giúp LLM nhanh chóng hiểu "người này là ai" mà không cần đọc toàn bộ persona.

**Dùng ở đâu:**
- Header của system prompt khi LLM tạo content: *"Bio: [bio]"*
- Hiển thị trên profile page trong UI

**Phân biệt với `persona`:** Bio ngắn, dành cho AI đọc nhanh. Persona dài, dành cho context sâu hơn.

---

#### `persona` — Tính cách chi tiết
```json
"persona": "Emma Hayes là một cô gái 19 tuổi với tính cách ENFJ, đam mê logistics. 
            Cô thích thảo luận về văn hóa, xã hội và kinh doanh..."
```

**Bài toán giải quyết:** Đây là "linh hồn" của agent. Khi LLM cần viết một post/comment cho Emma, nó đọc persona để hiểu **Emma nói chuyện theo phong cách nào, quan tâm điều gì, phản ứng ra sao**.

**Tại sao cần?** Nếu không có persona, 1000 agent sẽ viết ra những bài đăng giống hệt nhau — nhàm chán và không thực tế. Với persona, mỗi agent có giọng văn riêng.

**Ví dụ thực tế:**
```
Cùng 1 bài về "Shopee Black Friday" nhưng:
Emma (ENFJ, 19t, logistics) → "Amazing deals! Can't wait to connect with sellers during BF 🎉"
Henry (ISFJ, 47t, farmer)   → "Good prices on farming equipment this season. Practical choice."
```

**Dùng ở đâu:**
- System prompt của LLM khi generate post/comment
- Reflection prompts (giúp agent "nhìn lại" hành vi của mình)

---

#### `age` — Tuổi
```json
"age": 19
```

**Bài toán giải quyết:** Tuổi ảnh hưởng đến **phong cách ngôn ngữ** và **loại content** mà agent tạo ra. Một cô gái 19 tuổi và một người đàn ông 58 tuổi sẽ không viết về Shopee Black Friday theo cùng một cách.

**Tại sao cần?** Nếu tất cả agents cùng tuổi, kết quả simulation sẽ bị bias — không phản ánh phân khúc khách hàng thực tế.

**Dùng ở đâu:**
- Đưa vào system prompt: *"Bạn là [realname], [age] tuổi..."*
- Phân tích báo cáo theo nhóm tuổi: "Nhóm 18-25 engage cao nhất"

---

#### `gender` — Giới tính
```json
"gender": "female"
```

**Bài toán giải quyết:** Giúp LLM dùng đúng đại từ và tông giọng khi tạo content. Cũng giúp researcher phân tích **hành vi theo giới tính** (ví dụ: nữ giới engage nhiều hơn với fashion content).

**Dùng ở đâu:**
- System prompt: *"She is a 19-year-old..."*
- Phân tích kết quả: segment by gender

---

#### `mbti` — Kiểu tính cách Myers-Briggs
```json
"mbti": "ENFJ"
```

**Đây là tham số QUAN TRỌNG NHẤT cho hành vi agent.**

**Bài toán giải quyết:** Mỗi người có cách hành xử khác nhau trên mạng xã hội. Người hướng ngoại (E) đăng bài nhiều hơn người hướng nội (I). Người cảm xúc (F) thích (like) nhiều hơn người lý trí (T). MBTI mã hóa những khác biệt này thành số liệu cụ thể.

**4 chiều của MBTI và tác động:**

| Chiều | Ý nghĩa | Tác động trong EcoSim |
|---|---|---|
| **E** (Extraversion) | Hướng ngoại, thích giao tiếp | Đăng bài nhiều hơn 20%, comment nhiều hơn 30% |
| **I** (Introversion) | Hướng nội, ít giao tiếp | Đăng bài ít hơn 20%, comment ít hơn 30% |
| **F** (Feeling) | Quyết định bằng cảm xúc | Like nhiều hơn 20% |
| **T** (Thinking) | Quyết định bằng lý trí | Like ít hơn 10% |
| **P** (Perceiving) | Linh hoạt, thích khám phá | Xem nhiều loại nội dung hơn (feed rộng +20%) |
| **J** (Judging) | Có kế hoạch, ít thay đổi | Feed hẹp hơn (-10%), sở thích bảo thủ hơn |
| **N** (iNtuition) | Suy nghĩ trừu tượng | Reflection sâu hơn (+30%), sở thích thay đổi nhanh hơn |
| **S** (Sensing) | Thực tế, cụ thể | Reflection ít hơn (-20%), sở thích ổn định hơn |

**Ví dụ thực tế với ENFJ:**
```python
# Emma (ENFJ) nhận được modifiers:
{
    "post_mult": 1.2,      # E → đăng bài nhiều hơn 20%
    "comment_mult": 1.3,   # E → comment nhiều hơn 30%
    "like_mult": 1.2,      # F → like nhiều hơn 20%
    "feed_mult": 0.9,      # J → feed hẹp hơn 10%
    "reflection_boost": 1.3  # N → reflection sâu hơn 30%
}
```

**Tại sao không làm random?** Nếu tất cả agents hành xử giống nhau (multiplier = 1.0), kết quả simulation sẽ quá đều, không phản ánh sự đa dạng của con người thật.

---

#### `country` — Quốc gia
```json
"country": "UK"
```

**Bài toán giải quyết:** Người từ các quốc gia khác nhau có **văn hóa tiêu dùng** và **ngữ cảnh xã hội** khác nhau. Người UK và người Việt Nam sẽ phản ứng khác nhau với chiến dịch Shopee Black Friday (người UK có thể không biết Shopee).

**Dùng ở đâu:**
- System prompt: thêm context về văn hóa
- Phân tích kết quả: "User từ nước nào engage nhiều nhất?"

---

#### `profession` — Nghề nghiệp
```json
"profession": "Transportation, Distribution & Logistics"
```

**Bài toán giải quyết:** Nghề nghiệp quyết định loại nội dung agent quan tâm và cách họ diễn đạt. Một kỹ sư IT sẽ comment về tính năng kỹ thuật của sản phẩm, trong khi một người làm marketing sẽ chú ý đến chiến lược thương hiệu.

**Dùng ở đâu:**
- Graph query: *"Emma works in logistics, what related topics are trending?"*
- Tạo initial interest vector dựa trên nghề nghiệp

---

#### `interested_topics` — Danh sách chủ đề quan tâm
```json
"interested_topics": ["Culture & Society", "Business"]
```

**Bài toán giải quyết:** Đây là **điểm khởi đầu** (prior) cho interest vector của agent. Nó cho hệ thống biết Emma ban đầu quan tâm đến gì **trước khi simulation bắt đầu**.

**Tại sao quan trọng?** Không có tham số này, tất cả agents sẽ có cùng điểm xuất phát → feed giống nhau → hành vi giống nhau.

**Cách hoạt động:**
```python
# Khi tạo agent, topics được nhúng thành vector:
interest_text = "Culture & Society, Business, Transportation, Distribution & Logistics"
interest_vector = embedding_model.encode(interest_text)  # 384-chiều số

# Vector này dùng để:
# 1. Xác định feed bài đăng nào phù hợp với Emma
# 2. Quyết định Emma có like/comment bài nào không
```

**Trong quá trình simulation, vector này sẽ thay đổi** (gọi là "interest drift") — nếu Emma liên tục like bài về Black Friday, vector của cô sẽ dịch chuyển về phía "sales & promotions".

---

### 2.2 Tóm tắt: Tham số nào ảnh hưởng đến gì?

```
┌─────────────────────┬────────────────────────────────────────────────────┐
│ Tham số             │ Ảnh hưởng đến                                     │
├─────────────────────┼────────────────────────────────────────────────────┤
│ realname + persona  │ Chất lượng & phong cách ngôn ngữ của post/comment │
│ bio                 │ System prompt ngắn gọn cho LLM                    │
│ mbti                │ Tần suất post/like/comment + tốc độ drift sở thích│
│ age + gender        │ Tone giọng + phân tích nhân khẩu học              │
│ interested_topics   │ Feed ban đầu + interest vector gốc                │
│ country             │ Cultural context trong content                    │
│ profession          │ Domain expertise trong hội thoại                  │
└─────────────────────┴────────────────────────────────────────────────────┘
```

---

## Phần 3: Simulation Pipeline — Từng bước từ đầu đến cuối

Pipeline là **chuỗi các bước** diễn ra khi bạn chạy một simulation. Hãy coi nó như công thức nấu ăn: mỗi bước là một "node" có vai trò cụ thể.

### 3.1 Toàn cảnh pipeline

```
CHUẨN BỊ (chạy 1 lần)
│
├── Node 1: Campaign Knowledge Ingestion
│   └── Đọc chiến dịch → Phân tích → Lưu vào Graph
├── Node 2: Platform & Database Init
│   └── Tạo "mạng xã hội" SQLite
├── Node 3: Vector Store Init
│   └── Tải AI model nhúng văn bản
├── Node 4: RecSys Patch
│   └── Thay thuật toán feed mặc định
└── Node 5: Agent Generation
    └── Tạo N agents từ profiles.json

    ↓

VÒNG LẶP MÔ PHỎNG (chạy R rounds)
│
├── [Đầu vòng] Crisis Check → (nếu có) Inject sự kiện ngoại sinh
│
└── [Cho mỗi agent i trong số N agents]
    ├── Node A: Cognitive Preparation
    │   └── Lấy memory + MBTI + interest vector + graph context
    ├── Node B: Personalized Feed
    │   └── Tìm bài phù hợp với sở thích agent
    ├── Node C: Rule-based Decision
    │   └── Quyết định like/comment/scroll (không dùng LLM)
    ├── Node D: Action Execution
    │   └── Thực hiện hành động + gọi LLM nếu cần tạo text
    ├── Node E: State Update
    │   └── Cập nhật memory + interest drift
    ├── Node F: Reflection (mỗi K rounds)
    │   └── Agent nhìn lại và cập nhật nhận thức
    └── Node G: Graph Memory (async)
        └── Lưu tương tác vào FalkorDB (nền)

    ↓

KẾT THÚC
└── Node 6: Report Generation
    └── Phân tích dữ liệu → Tạo báo cáo
```

---

## Phần 4: Giải thích chi tiết từng Node

### Node 1: Campaign Knowledge Ingestion

**Bài toán cần giải:**

Imagine bạn thuê 1000 diễn viên để đóng vai người dùng mạng xã hội trong kịch bản về "Shopee Black Friday". Bạn cần họ biết về chiến dịch này. Nếu không, họ sẽ nói chuyện chung chung "À, hôm nay tôi thấy có sale trên shop nào đó" — vô nghĩa.

**Tại sao cần:**

> Agents cần biết **chi tiết cụ thể** về chiến dịch để tạo ra content thực tế: "Shopee giảm 90% điện thoại trong 10 ngày, tôi đang để mắt iPhone 15."

Nếu bỏ node này → agents chỉ nói chung chung → kết quả không có giá trị nghiên cứu.

**Cách hoạt động — 3 stage:**

```
campaign_brief.md
     │
     ▼
┌─────────────────────────────────────────┐
│ Stage 1: CampaignDocumentParser         │
│                                         │
│  Đọc file Markdown và tách thành        │
│  từng section theo tiêu đề:             │
│                                         │
│  ## Campaign Overview → Section 1       │
│  ## Target Audience   → Section 2       │
│  ## Key Messages      → Section 3       │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ Stage 2: CampaignSectionAnalyzer        │
│          (dùng GPT-4o-mini)             │
│                                         │
│  Đọc mỗi section và trích xuất:         │
│  - entities: [Shopee, iPhone 15, ...]   │
│  - facts: ["Giảm 90%", "10 ngày"...]   │
│  - summary: "Tóm tắt 1 câu"           │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│ Stage 3: CampaignGraphLoader            │
│          (Graphiti → FalkorDB)          │
│                                         │
│  Lưu thành "episodes" trong FalkorDB:   │
│  (Shopee) -[OFFERS]→ (BlackFriday)     │
│  (BlackFriday) -[HAS_DISCOUNT]→ (90%)  │
└─────────────────────────────────────────┘
```

**Kết quả:** Sau node này, mọi agent đều có thể query FalkorDB để lấy thông tin chiến dịch khi cần tạo content.

**Chi phí:** GPT-4o-mini chỉ chạy **1 lần** ở đây → rẻ. Không chạy lại trong simulation loop.

---

### Node 2: Platform & Database Init

**Bài toán cần giải:**

Agents cần một "sân chơi" để tương tác — một mạng xã hội giả lập. Node này tạo ra nó.

**Tại sao cần:**

Không có database → không có nơi lưu bài đăng, comment, lượt like → không có gì để simulate.

**Cách hoạt động:**

Tạo file SQLite (`oasis_simulation.db`) với đầy đủ bảng quan hệ:

```sql
-- "Người dùng" của mạng xã hội
CREATE TABLE user (
    user_id      INTEGER PRIMARY KEY,
    user_name    TEXT,        -- username của agent
    name         TEXT,        -- realname của agent
    bio          TEXT,        -- bio của agent
    num_followers INTEGER,
    num_followings INTEGER,
    created_at   DATETIME
);

-- Bài đăng
CREATE TABLE post (
    post_id    INTEGER PRIMARY KEY,
    user_id    INTEGER,       -- ai đăng?
    content    TEXT,          -- nội dung bài đăng
    num_likes  INTEGER,
    created_at DATETIME
);

-- Bình luận
CREATE TABLE comment (post_id, user_id, content, created_at);

-- Lượt thích
CREATE TABLE like (post_id, user_id, created_at);

-- Danh sách follow
CREATE TABLE follow (follower_id, followee_id);

-- Cache gợi ý bài (recommendation cache)
CREATE TABLE rec (user_id, post_id, score);
```

**Kết quả:** Một "mạng xã hội trống" sẵn sàng nhận dữ liệu từ agents.

---

### Node 3: Vector Store Init

**Bài toán cần giải:**

Làm thế nào để biết bài đăng nào **phù hợp** với sở thích của Emma? Không thể dùng keyword matching đơn giản (Emma thích "logistics" nhưng bài viết về "supply chain management" thì sao?).

**Tại sao cần:**

> Cần một AI hiểu **nghĩa** của văn bản, không chỉ so từ khóa. Đây là lý do cần Vector Store.

**Cách hoạt động — Khái niệm cơ bản:**

```
"Shopee Black Friday deals"     → [0.2, 0.8, 0.1, ..., 0.5]  (384 số)
                                         ↑
                                    Vector 384 chiều

"Emma thích: Culture & Society, Business" → [0.3, 0.7, 0.2, ..., 0.4]

Khoảng cách giữa 2 vector = 0.3 (gần)
→ Bài này PHÙ HỢP với Emma!

"Quantum physics paper abstract" → [0.9, 0.1, 0.8, ..., 0.1]
Khoảng cách so với Emma = 1.4 (xa)
→ Bài này KHÔNG PHÙ HỢP.
```

**Model được dùng:** `all-MiniLM-L6-v2` từ sentence-transformers. Đặc điểm:
- Chạy **hoàn toàn local** — không gọi API, không tốn tiền
- Kích thước ~90MB — nhỏ gọn
- Vector 384 chiều — đủ chính xác cho bài toán này

**Framework:** ChromaDB — database đặc biệt chuyên lưu và tìm kiếm vectors.

**Kết quả:** Hệ thống có thể nhanh chóng tìm ra "top 20 bài phù hợp nhất với Emma" trong 5ms, dù có 10,000 bài trong database.

---

### Node 4: RecSys Patch (Monkey-patch)

**Bài toán cần giải:**

OASIS (framework gốc) có hàm `update_rec_table()` để gợi ý bài cho agent. Nhưng hàm này dùng **collaborative filtering đơn giản** — tương tự Netflix cũ:
> "Người follow Emma cũng follow ai? → Gợi ý bài của người đó."

Vấn đề: Bỏ qua hoàn toàn sở thích thực sự của Emma.

**Tại sao cần:**

> Muốn feed của Emma phản ánh **đúng sở thích cá nhân** của cô ấy (dựa trên vector), không phải dựa trên ai cô follow.

**Cách hoạt động — Monkey-patch:**

"Monkey-patch" là kỹ thuật **thay thế một hàm tại runtime** mà không cần sửa source code gốc. Giống như thay động cơ xe mà không cần đập mà tháo từng bộ phận.

```python
# Hàm GỐC của OASIS (chúng ta KHÔNG sửa file này)
# oasis/platform.py:
async def update_rec_table(user_id):
    # collaborative filtering...
    pass

# Hàm MỚI của EcoSim
async def interest_based_rec(user_id):
    agent_id = map[user_id]
    interest_vec = drift_tracker.get_vector(agent_id)      # Vector sở thích hiện tại
    top_posts = chromadb.query(interest_vec, top_k=20)     # Tìm bài phù hợp
    write_to_rec_table(user_id, top_posts)                 # Ghi vào rec table

# THAY THẾ tại runtime (không sửa file OASIS)
platform.update_rec_table = interest_based_rec  # ← monkey-patch
```

**Kết quả:** Mỗi lần OASIS muốn cập nhật feed cho agent, nó sẽ tự động gọi hàm mới của chúng ta thay vì hàm cũ.

**Lợi ích quan trọng:** Không fork (copy) OASIS về — khi OASIS cập nhật phiên bản mới, chúng ta vẫn có thể merge updates mà không conflict.

---

### Node 5: Agent Generation

**Bài toán cần giải:**

Cần khởi tạo N agent từ file profiles.json và đưa chúng vào môi trường simulation.

**Cách hoạt động — 4 bước:**

```
profiles.json (danh sách profile)
        │
        ▼
┌──────────────────────────────────┐
│ Bước 1: Đọc profiles             │
│                                  │
│  for each profile in profiles:   │
│    id = profile index (0,1,2...) │
│    validate required fields      │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│ Bước 2: Tạo user trong SQLite    │
│                                  │
│  INSERT INTO user                │
│    (user_name, name, bio, ...)   │
│  → user_id = 0,1,2,...           │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│ Bước 3: Tạo follow network       │
│                                  │
│  Nếu profile có                  │
│  "following_agentid_list": [2,5] │
│  → INSERT INTO follow            │
│     (follower_id=0, followee=2)  │
│     (follower_id=0, followee=5)  │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│ Bước 4: Tạo initial posts        │
│                                  │
│  Nếu profile có                  │
│  "previous_tweets": [...]        │
│  → INSERT INTO post              │
│  → Index vào ChromaDB           │
└──────────────────────────────────┘
```

**Kết quả:** N agents đã sống trong SQLite, có quan hệ follow với nhau, và có bài đăng ban đầu trong ChromaDB.

---

### Node A: Cognitive Preparation

**Bài toán cần giải:**

Trước khi một agent hành động trong một round, nó cần được "nhắc nhở":
- *"Tôi đã làm gì trong các round trước?"* (memory)
- *"Tính cách của tôi là gì?"* (MBTI)
- *"Tôi đang quan tâm đến gì lúc này?"* (interest)
- *"Mối quan hệ xã hội của tôi là gì?"* (graph)

**Tại sao cần:**

Không có node này → mỗi round agent "quên hết", hành xử như người mất trí nhớ → không thực tế.

**Cách hoạt động — 4 nguồn dữ liệu song song:**

```python
# Chạy song song (không phải tuần tự) để nhanh hơn:

memory_ctx = agent_memory.get_context(agent_id)
# → "Round 1: liked a post; Round 2: posted 'Great deals!'"

mbti_mods = get_behavior_modifiers(profile["mbti"])
# → {post_mult: 1.2, like_mult: 1.2, ...}

interest_text = drift_tracker.get_interest_text(agent_id)
# → "Culture & Society, Business, Black Friday deals"

graph_ctx = graph_helper.get_social_context(agent_id)      # nếu bật
# → "Bạn bè của Emma: Ryan (tech), James (educator)..."
```

**Kết quả:** Một "gói context" đầy đủ để truyền vào các node tiếp theo.

---

### Node B: Personalized Feed

**Bài toán cần giải:**

Agent sẽ "đọc" bài nào? Giống như mở app mạng xã hội — bạn không thấy tất cả bài trên đời, chỉ thấy những bài feed gợi ý.

**Tại sao cần:**

Nếu tất cả agents thấy cùng feed → hành vi đồng nhất → kết quả không có ý nghĩa. Feed cá nhân hóa tạo ra sự đa dạng tự nhiên.

**Cách hoạt động — `query_unified` (3 yếu tố):**

```
final_distance(bài) = semantic_distance     (ChromaDB cosine, thấp = phù hợp hơn)
                    - popularity_bonus      (tác giả nhiều follower → -0.25 tối đa)
                    + comment_decay         (đã comment nhiều → +0.3 × count)

→ Sắp xếp theo final_distance tăng dần → lấy top K
```

**Ví dụ với Emma (thích "Culture & Society, Business"):**

| Bài đăng | Semantic dist | Pop bonus | Comment decay | Final dist |
|---|---|---|---|---|
| "Shopee Black Friday 90% off!" | 0.30 | -0.15 | 0.0 | **0.15** ✅ |
| "Business culture in UK" | 0.45 | -0.05 | 0.0 | **0.40** ✅ |
| "Quantum physics abstract" | 1.40 | 0.0 | 0.0 | **1.40** ❌ |

→ Emma nhận feed về Black Friday và Business culture — bài lạ chủ đề bị đẩy xuống.

**MBTI ảnh hưởng:** Emma là J (Judging) → `feed_mult = 0.9` → feed hẹp hơn, tập trung hơn.

---

### Node C: Rule-based Decision Engine

**Bài toán cần giải:**

Đây là **quyết định quan trọng nhất**: agent có like bài này không? Có comment không? Có bỏ qua không?

**Tại sao KHÔNG dùng LLM để quyết định:**

Trong OASIS gốc, mỗi lần agent cần quyết định, nó gọi LLM:
> LLM: *"Emma, bạn muốn làm gì với bài đăng này? A) Like  B) Comment  C) Skip"*

Với 1000 agents × 10 rounds × 20 bài/agent = **200,000 LLM calls** → tốn ~$30, mất nhiều giờ.

**Giải pháp của EcoSim — Khoảng cách ngữ nghĩa cosine:**

```python
STRONG_THRESHOLD   = 0.7   # < 0.7  → STRONG match
MODERATE_THRESHOLD = 1.0   # 0.7–1.0 → MODERATE match
WEAK_THRESHOLD     = 1.3   # 1.0–1.3 → WEAK match
                           # > 1.3  → NO match

def decide(agent_id, post_id, distance, mbti_mods):
    # distance là cosine distance từ ChromaDB (thấp = gần = phù hợp)
    activity_mult = get_activity_mult(profile["daily_hours"])
    
    if distance < STRONG_THRESHOLD:
        # Bài RẤT phù hợp → Like chắc chắn
        like_prob    = 1.0 * activity_mult * mbti_mods["like_mult"]
        comment_prob = 0.50 * activity_mult * mbti_mods["comment_mult"]
    elif distance < MODERATE_THRESHOLD:
        like_prob    = 0.75
        comment_prob = 0.15
    elif distance < WEAK_THRESHOLD:
        like_prob    = 0.30
        comment_prob = 0.0
    else:  # NO match
        like_prob    = 0.10
        comment_prob = 0.0

    if random() < like_prob:    actions.append("like_post")
    if random() < comment_prob: actions.append("create_comment")  # needs_llm=True

# Kết quả: 0 LLM calls cho like/skip!
```

**Ví dụ trực quan:**

```
Emma (thích Business, Culture)
  gặp bài: "Shopee sale 90% điện thoại!"
  distance = 0.35 (< 0.7 STRONG threshold)
  → like_prob = 1.0 × 1.0 × 1.2(F) = 1.0 → Like!
  → comment_prob = 0.50 × 1.0 × 1.3(E) = 0.65 → Comment!

Emma gặp bài: "Mathematics olympiad problem #42"
  distance = 1.5 (> 1.3 NO MATCH threshold)
  → like_prob = 0.10 → (90% khả năng) Scroll past
```

**Kết quả:** Tốc độ tăng 20-40 lần, chi phí gần $0 cho phần decision.

---

### Node D: Action Execution

**Bài toán cần giải:**

Node C chỉ *quyết định* hành động. Node D *thực hiện* hành động đó — gọi API của OASIS Platform để ghi vào SQLite.

**Tại sao tách ra 2 node?**

> Separation of Concerns — Quyết định và Thực hiện là 2 việc khác nhau. Tách ra giúp dễ debug và test.

**Cách hoạt động:**

```python
for (post_id, action_type) in action_plan:
    
    if action_type == "like":
        await platform.like_post(agent, post_id)
        # → INSERT INTO like (post_id=42, user_id=7, ...)
        # → UPDATE post SET num_likes = num_likes+1 WHERE post_id=42
        memory.record_action(agent_id, "like_post", post_content)
    
    elif action_type == "comment":
        # ← ĐÂY mới cần LLM! (tạo văn bản comment)
        comment_text = await _generate_comment(
            model,            # GPT-4o-mini (CAMEL ChatAgent)
            persona,          # persona của agent
            post_content,     # nội dung bài được comment
            memory_context=mem_ctx
        )
        await platform.create_comment(agent, post_id, comment_text)
        memory.record_action(agent_id, "create_comment", comment_text)
    
    elif action_type == "create_post":
        post_text = await _generate_post_content(
            model,            # GPT-4o-mini (CAMEL ChatAgent)
            agent_persona, topic, memory_context=mem_ctx
        )
        post_id = await platform.create_post(agent, post_text)
        post_indexer.index_post(post_id, post_text)  # → ChromaDB
```

**Quy tắc về LLM:**
- **Like/Skip:** 0 LLM calls
- **Comment/Post:** 1 LLM call → **GPT-4o-mini** (qua CAMEL `ChatAgent`, hard-coded trong `run_simulation.py`)

---

### Node E: State Update

**Bài toán cần giải:**

Sau khi Emma like 3 bài về Black Friday, cô ấy nên *quan tâm hơn* đến chủ đề Black Friday trong các round sau. Đây là **"interest drift"** — sở thích trôi dạt. Nhưng quan trọng hơn: nếu Emma đọc bài về một chủ đề **hoàn toàn mới** mà cô chưa từng có trong profile ban đầu, cô vẫn có thể **khám phá sở thích mới** đó.

**Tại sao cần:**

Không có node này → sở thích của Emma không bao giờ thay đổi → simulation nhàm chán, không phản ánh thực tế (người thật thay đổi sở thích khi bị ảnh hưởng bởi content).

**Node E thực hiện 2 nhiệm vụ riêng biệt:**

```
Nhiệm vụ 1: BOOST/DECAY sở thích hiện có
Nhiệm vụ 2: KHÁM PHÁ sở thích mới từ content (dùng KeyBERT)
```

---

#### Nhiệm vụ 1: Boost & Decay sở thích hiện có

```
Emma thích ban đầu: "Culture & Society, Business"

Round 1: Emma like 3 bài về Black Friday
→ "black friday" khớp với "Business" (trong interests cũ)
→ BOOST: weight("Business") += impressionability (0.25)
→ weight("Business") = 0.8 + 0.25 = 1.0 (capped)

Round 2: Emma không engage bài nào về "Culture & Society"
→ DECAY: weight("Culture & Society") *= (1 - forgetfulness)
→ weight("Culture & Society") = 0.8 × 0.8 = 0.64

→ Profile interests có FLOOR (không bị xóa):
  floor = conviction × 0.3 = 0.8 × 0.3 = 0.24
  weight không bao giờ < 0.24 với sở thích từ profile gốc
```

---

#### Nhiệm vụ 2: KeyBERT — Khám phá sở thích HOÀN TOÀN MỚI

**Bài toán con:** Emma ban đầu không hề biết về "flash sale" hay "cashback voucher" — đây là khái niệm hoàn toàn mới. Làm thế nào để cô ấy "học" được sở thích mới này từ các bài đăng cô đã like?

**Giải pháp: KeyBERT keyphrase extraction**

KeyBERT là thư viện dùng AI (cùng model `all-MiniLM-L6-v2` với ChromaDB) để trích xuất các **cụm từ quan trọng nhất** từ văn bản, dựa trên sự tương đồng ngữ nghĩa giữa cụm từ và toàn bộ văn bản.

```python
# Mỗi lần Emma like/comment một bài, EcoSim gọi:
engaged_keywords = _extract_keyphrases(post_content, max_phrases=3)

# Ví dụ: Emma like bài:
post = "Shopee Black Friday đang có flash sale 90%! Voucher cashback 500k!
        Đây là cơ hội không thể bỏ lỡ cho dân mua sắm online!"

keyphrases = _extract_keyphrases(post)
# KeyBERT trả về:
# → ["flash sale shopee", "voucher cashback", "mua sắm online"]
#    (Có score > 0.05, diversity đủ khác nhau — nhờ MMR)
```

**Cách KeyBERT hoạt động bên trong:**

```
Bước 1: Embed toàn bộ post → vector đại diện nội dung

Bước 2: Tạo danh sách candidate N-grams (1, 2, 3 từ):
        ["flash", "sale", "flash sale", "shopee", "flash sale shopee",
         "voucher cashback", "cashback 500k", "mua sắm", ...]

Bước 3: Embed từng candidate → so sánh cosine similarity với post vector

Bước 4: Áp dụng MMR (Maximal Marginal Relevance) để đảm bảo diversity:
        - Không lấy 3 keywords đều về "sale" (quá giống nhau)
        - Lấy 3 keywords từ 3 chủ đề khác nhau của bài

Bước 5: Lọc kết quả:
        - score < 0.05 → bỏ (quá kém liên quan)
        - Từ đơn generic ("sale", "deal", "best") → bỏ
        - Từ đơn < 5 ký tự → bỏ
        → Giữ lại top 3 keyphrases chất lượng
```

**Sau khi có keywords mới, thêm vào interest vector:**

```python
for kw in engaged_keywords:  # ["flash sale shopee", "voucher cashback", ...]
    if kw not in current_interests and len(interests) < MAX_INTERESTS (10):
        # Thêm sở thích MỚI với weight khởi đầu = curiosity
        interests[kw] = InterestItem(
            keyword=kw,
            weight=traits.curiosity,   # MBTI N → curiosity=0.5 | S → 0.2
            source="drift",            # đánh dấu: xuất phát từ drift, không phải profile
            first_seen=round_num,
        )
```

**Ví dụ hành trình khám phá của Emma qua 5 round:**

```
Round 0 (khởi đầu):
  Interests: ["Culture & Society" (0.8), "Business" (0.8)]
  Source: "profile"

Round 1: Emma like bài về "Shopee flash sale cashback"
  KeyBERT trích xuất: ["flash sale shopee", "voucher cashback"]
  → Thêm mới: "flash sale shopee" (weight = curiosity = 0.5)
  → Thêm mới: "voucher cashback" (weight = 0.5)
  Interests: ["Culture & Society" (0.8), "Business" (0.94), 
              "flash sale shopee" (0.5⭐), "voucher cashback" (0.5⭐)]

Round 2: Emma like bài về "beauty deals Black Friday"
  KeyBERT trích xuất: ["beauty deals", "black friday deals"]
  → Thêm: "beauty deals" (weight = 0.5)
  "Business" DECAY (không engage) → 0.94 × 0.8 = 0.75

Round 5: "flash sale shopee" liên tục được boost mỗi round
  → weight = 0.5 + 3×0.25 = 1.0 (capped)
  → Trở thành sở thích MẠNH nhất của Emma!
  → Feed sau này: 80% bài về flash sale, 20% về business
```

**Fallback khi KeyBERT không khả dụng:**

Nếu KeyBERT chưa cài (`pip install keybert`), hệ thống tự động dùng **N-gram extraction đơn giản**:

```python
# Tách văn bản → lấy cụm từ content word liên tiếp
text = "flash sale shopee amazing deals"
→ Lấy cụm 2-3 từ content: ["flash sale", "sale shopee"]
→ Loại stopwords & weak words ("amazing", "deals")
→ Xếp hạng theo tần suất xuất hiện
```

Kết quả kém hơn KeyBERT (không hiểu ngữ nghĩa) nhưng vẫn hoạt động được.

---

**MBTI ảnh hưởng đến tốc độ drift:**

| MBTI Trait | Cognitive Trait | Ý nghĩa |
|---|---|---|
| J (Judging) | conviction = 0.80 | Sở thích rất ổn định, drift chậm; floor cao |
| P (Perceiving) | conviction = 0.40 | Sở thích dễ thay đổi, drift nhanh; floor thấp |
| N (iNtuition) | curiosity = 0.50 | Sở thích mới bắt đầu với weight CAO → khám phá rộng |
| S (Sensing) | curiosity = 0.20 | Sở thích mới bắt đầu yếu → ít khám phá |
| N (iNtuition) | forgetfulness = 0.20 | Quên nhanh sở thích cũ không engage |
| S (Sensing) | forgetfulness = 0.10 | Nhớ lâu sở thích dù không engage |
| F (Feeling) | impressionability = 0.25 | Boost mạnh mỗi lần engage |
| T (Thinking) | impressionability = 0.10 | Boost yếu, sở thích thay đổi chậm |

**Tóm tắt luồng đầy đủ của Node E:**

```
Bài đã engage (liked/commented)
        │
        ▼
┌─────────────────────────────────┐
│ KeyBERT extraction              │
│ ("flash sale shopee" ✓          │
│  "voucher cashback" ✓           │
│  "amazing" ✗ — generic word)   │
└──────────────┬──────────────────┘
               │
     ┌─────────┴──────────┐
     ▼                    ▼
[Keyword đã có        [Keyword HOÀN TOÀN MỚI]
 trong interests]            │
     │                       ▼
     ▼               Thêm InterestItem(
  BOOST weight           weight=curiosity,
  += impressionability   source="drift"
  (capped tại 1.0)    )
     │
     ▼
[Keyword KHÔNG engage] → DECAY × (1-forgetfulness)
[Profile interests]    → FLOOR = conviction × 0.3
[Drift interests < 0.03] → PRUNE (xóa khỏi interests)
```

---

### Node F: Reflection

**Bài toán cần giải:**

Sau vài round, agent nên "nhìn lại" và **nhận ra sự thay đổi trong bản thân**. Giống như cuối ngày bạn tự hỏi: "Hôm nay mình đã làm gì, cảm thấy thế nào?"

**Tại sao cần:**

Không có reflection → agent cứ hành xử theo quán tính, không có sự phát triển tâm lý → thiếu tính người.

**Cách hoạt động:**

```python
# Chạy mỗi K rounds (không phải mỗi round — để tiết kiệm)
if round_num % REFLECTION_INTERVAL == 0:
    
    recent_memory = memory.get_context(agent_id)
    # "Round 1: liked posts about BF sale; Round 2: commented on fashion"
    
    reflection_prompt = f"""
    Bạn là {profile['realname']}.
    {profile['persona']}
    
    Hoạt động gần đây của bạn:
    {recent_memory}
    
    Dựa trên đây, hãy mô tả ngắn gọn:
    1. Xu hướng sở thích của bạn đang thay đổi như thế nào?
    2. Điều gì đang thu hút sự chú ý của bạn?
    """
    
    insight = await reflection.maybe_reflect(
        agent_id, round_num, agent_memory,
        model,           # ← GPT-4o-mini (CAMEL ChatAgent — cùng model với post/comment)
        base_persona, graph_context=_graph_ctx
    )
    # → "I seem to be more interested in promotional events lately..."
    
    # Insight được LAYER THÊM vào persona (không ghi đè base_persona)
    # get_evolved_persona() = base_persona + "\nRecent reflections: " + insights
```

**LLM dùng:** GPT-4o-mini — chạy mỗi `interval=3` rounds, **chỉ khi agent có memory context**. Base persona không bao giờ bị sửa đổi.

**Frequency:** Mỗi K=3 rounds (có thể cấu hình).

---

### Node G: Graph Memory (Async)

**Bài toán cần giải:**

Cần lưu trữ bộ nhớ **dài hạn** của agent — không phải chỉ 5 round gần đây, mà là **toàn bộ lịch sử tương tác** dưới dạng knowledge graph có thể query được.

**Tại sao tách khỏi vòng lặp chính?**

Ghi vào FalkorDB thông qua Graphiti mất ~200-500ms mỗi lần (vì Graphiti dùng LLM để trích xuất entity từ episode text). Nếu block vòng lặp:

```
1000 agents × 200ms = 200 giây chỉ để ghi graph
→ 1 round mất 200 giây thay vì 20 giây
→ 10 rounds = 2000 giây ≈ 33 phút (quá chậm!)
```

**Cách hoạt động — Fire and Forget:**

```python
# Trong vòng lặp chính (KHÔNG BLOCK):
await graph_updater.enqueue({
    "agent_id": 7,
    "action": "like_post",
    "post_content": "Shopee sale 90%!",
    "timestamp": now()
})
# → Hàm này return NGAY LẬP TỨC, tiếp tục agent khác

# Ở background (chạy song song):
async def _worker():
    while True:
        data = await queue.get()
        episode_text = f"{data['agent_id']} liked a post about '{data['topic']}'"
        await graphiti.add_episode(episode_text)  # Chậm nhưng không chặn ai
```

**Kết quả:** Vòng lặp chính chạy nhanh, graph vẫn được cập nhật đầy đủ trong nền.

**Flush khi kết thúc:** Trước khi tạo báo cáo, gọi `await graph_updater.flush()` để đảm bảo tất cả episodes đã được ghi xong.

---

### Crisis Injection (Tùy chọn)

**Bài toán cần giải:**

Researcher muốn thử nghiệm: "Nếu có tin tức xấu về thương hiệu xuất hiện vào ngày thứ 5 của chiến dịch, người dùng sẽ phản ứng thế nào?"

**Cách hoạt động:**

Crisis được cấu hình trước trong `simulation_config.json`:

```json
{
  "crisis_events": [
    {
      "round": 5,
      "type": "viral_post",
      "content": "Shopee bị hack! Data 10 triệu user bị lộ!",
      "intensity": "high"
    }
  ]
}
```

Đầu round 5, hệ thống inject bài này vào SQLite + ChromaDB → nó xuất hiện trong feed của MỌI agent → quan sát phản ứng.

---

### Node 6: Report Generation

**Bài toán cần giải:**

Sau khi simulation xong, cần tổng hợp dữ liệu thành báo cáo có thể đọc được — không phải đống SQL raw.

**Cách hoạt động:**

```python
# Đọc dữ liệu từ SQLite
stats = query_database("""
    SELECT COUNT(*) as total_likes FROM like;
    SELECT COUNT(*) as total_comments FROM comment;
    SELECT content, num_likes FROM post ORDER BY num_likes DESC LIMIT 10;
""")

# Dùng ReACT agent (GPT-4o-mini) để phân tích
report = await react_agent.run(
    tools=[sql_query_tool, graph_query_tool],
    task=f"""
    Phân tích kết quả simulation chiến dịch {campaign_name}.
    
    Số liệu: {stats}
    
    Hãy xác định:
    1. Nội dung nào được engage nhiều nhất và tại sao?
    2. Nhóm tuổi/MBTI nào phản ứng tích cực nhất?
    3. Sentiment của tổng thể có positive không?
    4. Đề xuất điều chỉnh chiến dịch.
    """
)
```

**LLM dùng:** GPT-4o-mini — chất lượng cao nhất cho bước quan trọng nhất. Chạy **1 lần duy nhất** khi kết thúc.

---

## Phần 5: Tất cả các toggle — Bật/tắt tính năng

EcoSim có hệ thống toggle cho phép bật/tắt từng tính năng để test và tiết kiệm tài nguyên:

| Toggle | Default | Khi tắt |
|---|---|---|
| `ENABLE_GRAPH_MEMORY` | `true` | Không dùng FalkorDB |
| `enable_interest_drift` | `true` | Sở thích agent cố định |
| `enable_mbti_modifiers` | `true` | Tất cả agents hành xử giống nhau |
| `enable_reflection` | `true` | Không có reflection |
| `enable_campaign_knowledge` | `true` | Không load campaign brief |

**Cách cấu hình trong `.env`:**
```bash
ENABLE_GRAPH_MEMORY=true
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
OPENAI_API_KEY=sk-...    # GPT-4o-mini — model duy nhất được sử dụng
LLM_BASE_URL=            # Tùy chọn: custom OpenAI-compatible endpoint
LLM_API_KEY=             # Map sang OPENAI_API_KEY
LLM_MODEL_NAME=gpt-4o-mini  # Giá trị mặc định (được đọc nhưng chưa được wire vào ModelFactory)
```

---

## Tổng kết: Mọi thứ kết nối với nhau

```
profiles.json
    ↓ [username, bio, persona]         → SQLite user table (ai là ai?)
    ↓ [mbti]                           → MBTI modifiers (hành xử thế nào?)
    ↓ [interested_topics, profession]  → Interest vector (thích gì?)
    ↓ [age, gender, country]           → LLM prompt context (giọng điệu gì?)

campaign_brief.md
    ↓ [entities, facts]                → FalkorDB graph (biết gì về chiến dịch?)

SIMULATION:
    Interest Vector ──→ ChromaDB Feed ──→ Rule-based Decision ──→ Like/Comment/Post
                ↑                                                        │
                └────────── Interest Drift (Node E) ←───────────────────┘
                            (vector thay đổi dựa trên hành vi)

    MBTI ──→ Multipliers ──→ Tần suất hành động + Tốc độ drift

    Memory (Node A) ──→ LLM Prompt ──→ Chất lượng content (Node D)

    Reflection (Node F) ──→ Insight ──→ Interest Vector update (thêm lần nữa)

    Graph Memory (Node G) ──→ FalkorDB ──→ Social context cho lần sau
```

---

*Đọc thêm:*
- [`simulation_uml_sequence.md`](./simulation_uml_sequence.md) — Sơ đồ UML chi tiết từng bước
- [`simulation_pipeline_analysis.md`](./simulation_pipeline_analysis.md) — So sánh pipeline cũ vs mới
- [`../cognitive_pipeline.md`](../cognitive_pipeline.md) — Chi tiết 5 pha nhận thức

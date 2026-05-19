# 07 — Storage & Path Resolution

Data của EcoSim phân bổ qua **6 backend** khác nhau, mỗi cái cho 1 mục đích cụ thể. File này là cheat sheet — đọc khi cần debug "data ở đâu" hoặc "tại sao path resolver fail".

## Bảng tổng hợp

| Backend | Đường dẫn / Endpoint | Vai trò | Lifetime |
|---------|---------------------|---------|----------|
| Filesystem per-campaign | `data/campaigns/<cid>/` | source, extracted, kg, sims/ | Permanent (gitignore) |
| Filesystem per-sim | `data/campaigns/<cid>/sims/<sid>/` | profiles, oasis.db, actions, report | Permanent |
| **SQLite Meta DB** | `data/meta.db` | Index/lookup AUTHORITATIVE | Permanent |
| FalkorDB (Redis) | `ecosim-falkordb:6379` (Docker volume `falkordb_data`) | 3 graphs: `<cid>` + `sim_<sid>` + `ecosim_agent_memory` | Permanent (volume) |
| ChromaDB | `data/campaigns/<cid>/{kg,sims/<sid>}/chroma{,_delta}/` | Vector store (master + sim delta) | Permanent per campaign/sim |
| Zep Cloud (optional) | `https://api.getzep.com/` | Master KG + sim_<sid> runtime graph | Sim graph deleted khi COMPLETED |

## 1. Filesystem layout (Phase 5)

```text
data/
├── meta.db                                ← SQLite registry (xem §3)
├── samples/                               ← Sample corpora (KHÔNG gitignored)
│   └── dataGenerator/<...>.parquet        ← 20M-row persona pool
├── campaigns/
│   └── <cid>/                             ← Per-campaign (cid = 32-hex)
│       ├── source/
│       │   └── <original_filename>        ← Tài liệu gốc (immutable sau upload)
│       ├── extracted/
│       │   ├── spec.json                  ← Stage 1 output (CampaignSpec)
│       │   ├── sections.json              ← Stage 2.1 (DocumentSection list, _version=1)
│       │   └── analyzed.json              ← Stage 2.3+2.5 (entities + facts, dedup)
│       ├── kg/
│       │   ├── snapshot.json              ← Stage 3 Cypher MERGE record
│       │   ├── chroma/                    ← Master KG ChromaDB (3 collections)
│       │   └── build_meta.json            ← model_id, dim, builder variant, timestamp
│       └── sims/
│           └── sim_<sid>/                 ← Per-sim runtime
│               ├── config.json            ← SimConfig (TimeConfig + EventConfig + AgentBehaviorConfigs)
│               ├── simulation_config.json ← Legacy filename — code đọc cả 2
│               ├── profiles.json          ← AgentProfile[] với persona_evolved + reflection_insights
│               ├── campaign_context.txt   ← Context inject vào prompts
│               ├── crisis_scenarios.json  ← 4 scenarios (3 crisis + 1 smooth)
│               ├── oasis_simulation.db    ← OASIS SQLite (post, comment, like, follow, trace, ...)
│               ├── actions.jsonl          ← 1 action/line, append-only atomic
│               ├── progress.json          ← current_round, status
│               ├── memory_stats.json      ← Per-round buffer stats
│               ├── agent_tracking.txt     ← Legacy cognitive snapshot
│               ├── tracking.jsonl         ← NEW JSONL per-round per tracked agent
│               ├── simulation.log         ← stdout subprocess
│               ├── crisis_log.jsonl       ← Crisis events triggered
│               ├── chroma/                ← Per-sim ChromaDB (`ecosim_{sim_id}` collection)
│               ├── kg/
│               │   ├── snapshot_delta.json
│               │   └── chroma_delta/
│               ├── analysis_results.json  ← Sentiment summary (RoBERTa)
│               ├── analysis/              ← Per-round sentiment detail
│               ├── suggested_questions.json ← LLM-generated survey questions
│               ├── <survey_id>.json       ← Raw survey + responses
│               ├── survey_results.json    ← Aggregated
│               └── report/
│                   ├── outline.json
│                   ├── section_01.md..section_NN.md
│                   ├── full_report.md
│                   ├── evidence.json
│                   ├── meta.json
│                   ├── agent_log.jsonl    ← ReACT trace
│                   └── progress.json
```

### Legacy layout (Phase 4, deprecated)

```text
data/simulations/<sid>/    ← KHÔNG dùng nữa
```

Phase 5 đã move toàn bộ sim artifacts vào `data/campaigns/<cid>/sims/<sid>/`. Code legacy nào còn dùng `Config.SIM_DIR/<sid>/` chỉ là fallback safety net khi sim không có trong meta.db.

## 2. Atomic write contract

Mọi write vào sim artifacts đi qua [`ecosim_common.atomic_io`](../libs/ecosim-common/src/ecosim_common/atomic_io.py):

| Function | Use case | Pattern |
|----------|----------|---------|
| `atomic_write_json(path, obj)` | 1-shot snapshot (config, profiles, meta) | Write tmp → fsync → rename |
| `atomic_write_text(path, str)` | Markdown sections | Same |
| `atomic_append_jsonl(path, dict)` | Incremental log (actions.jsonl, tracking.jsonl) | `O_APPEND` POSIX atomic |
| `safe_read_json(path, default)` | Read with fallback | Returns default nếu file thiếu/JSON rách |

**Reason**: nhiều service ghi vào cùng `sims/<sid>/` (subprocess + Sim service + Core during chat). Atomic guards reader không bao giờ thấy half-written file.

## 3. Meta DB (`data/meta.db`)

SQLite, schema version 5. Initialized lần đầu Core boot qua `metadata_index.init_schema()`. Bootstrap from filesystem qua `bootstrap_from_filesystem()` — quét `data/campaigns/` để rebuild rows nếu DB mất.

### Tables

| Table | Cột chính | Vai trò |
|-------|-----------|---------|
| `campaigns` | `cid, name, campaign_type, market, created_at, kg_graph_name, kg_status, kg_node_count, kg_edge_count, kg_embedding_model, kg_embedding_dim` | Campaign registry |
| `simulations` | `sid, cid, status, created_at, started_at, completed_at, num_agents, num_rounds, current_round, sim_dir, config_path, profiles_path, actions_path, oasis_db_path, ..., kg_graph_name, kg_parent_graph, kg_status, kg_*_count` (40+ cột) | Sim registry + all paths |
| `simulation_agents` | `sid, agent_id, name, mbti, persona_hash, ...` | Per-agent index |
| `sentiment_summaries` | `sid, round_num, positive, negative, neutral` | Per-round sentiment cache (cho Dashboard) |

### Views

| View | Vai trò |
|------|---------|
| `campaign_stats` | Per-campaign rollup cho Dashboard |
| `sim_stats` | Per-sim summary cho list/overview |
| `sentiment_overview` | Per-campaign avg sentiment cho chart |

### Path columns (40+ per sim)

Sim row có **toàn bộ path** được pre-computed tại lúc prepare:

```text
sim_dir, config_path, profiles_path, actions_path, oasis_db_path,
progress_path, memory_stats_path, kg_dir, zep_buffer_path,
posts_chroma_dir, analysis_dir, sentiment_path, tracking_path,
tracking_legacy_path, report_dir, report_log_path,
crisis_log_path, crisis_pending_path, simulation_log_path,
campaign_context_path
```

→ Endpoint resolve path qua `resolve_simulation_paths(sid)` ([libs/ecosim-common/src/ecosim_common/path_resolver.py](../libs/ecosim-common/src/ecosim_common/path_resolver.py)) thay vì hardcode.

### Schema migrations

[`metadata_migrations.py`](../libs/ecosim-common/src/ecosim_common/metadata_migrations.py):

- Idempotent ALTER TABLE + view drops/recreates.
- Registry pattern: thêm migration mới = thêm function `_migrate_vN_to_vN+1()` + bump `SCHEMA_VERSION`.
- Run automatically on `init_schema()` boot.

## 4. FalkorDB (Redis)

Container `ecosim-falkordb` image `falkordb/falkordb`. Docker volume `falkordb_data` mount tại `/var/lib/falkordb/data`. 

Browser UI: [http://localhost:3000](http://localhost:3000) (ship sẵn trong image).

### 3 graphs (databases)

| Graph name | Purpose | Lifecycle |
|------------|---------|-----------|
| `<cid>` (campaign_id) | **Master KG** built từ Stage 3. Multi-label `:Entity:Brand` etc. + edges từ master ontology. | Permanent. Restore từ disk qua `POST /api/graph/restore?campaign_id=X` |
| `sim_<sid>` | **Per-sim runtime hybrid graph**. Cloned từ master + Phase 15 Zep section deltas + `:SimAgent` seeded. | Permanent (in volume). Sim COMPLETED không delete graph (cần cho Report/Interview/Survey ReACT tools) |
| `ecosim_agent_memory` | **Agent memory graph** (chỉ tạo khi `enable_graph_cognition=true`). Reflection edges `[:REFLECTED_AS]`. | Permanent — không cleanup intentionally (post-sim analytics) |

### Persistence

FalkorDB ghi `dump.rdb` vào `/var/lib/falkordb/data` (đường dẫn thực; `/data/data` là symlink). Phải mount volume vào path này — KHÔNG `/data` — nếu không data nằm ở writable layer của container và mất khi recreate.

### Access pattern

Per CLAUDE.md, 16+ write site ở `apps/simulation/` dùng `from falkordb import FalkorDB` trực tiếp:

```python
from falkordb import FalkorDB
fdb = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
graph = fdb.select_graph(graph_name)
result = graph.query(cypher, params)
```

**Graphiti hybrid search broken** — `graphiti_core.driver.falkordb_driver` không tồn tại trên PyPI. Read-side semantic search degrade về raw Cypher pattern matching.

## 5. ChromaDB

Persistent client, embedded (in-process, không network). Lưu data trên filesystem.

### Master KG

`data/campaigns/<cid>/kg/chroma/` — 3 collections:
- `entities_<cid>` — entity name + description embeddings
- `facts_<cid>` — fact text embeddings
- `episodes_<cid>` — episode body embeddings

Embedding qua OpenAI API (1536-dim cho `text-embedding-3-small`, hoặc tùy `LLM_EMBEDDING_MODEL`).

### Per-sim posts

`data/campaigns/<cid>/sims/<sid>/chroma/`, collection `ecosim_{sim_id}` — sống ở `PostIndexer` ([apps/simulation/interest_feed.py](../apps/simulation/interest_feed.py)) cho semantic feed matching round-to-round.

**Gotcha**: đừng init `PostIndexer()` không arg — phải pass `sim_id` + `persist_dir=sim_dir/chroma`.

### Per-sim KG delta

`data/campaigns/<cid>/sims/<sid>/kg/chroma_delta/` — chỉ embeddings cho entities/edges sinh mới trong sim (Phase 15 Zep extract delta), không duplicate master. Cascade restore: master → fork → apply delta.

## 6. Zep Cloud (optional)

External managed service. Gates:
- `ZEP_API_KEY` env var (required).
- `ZEP_SIM_RUNTIME=true` cho Phase 15 sim runtime dispatch.
- `ENABLE_GRAPH_MEMORY=true` (default) gate chung.

### Master KG

Khi `KG_BUILDER=zep_hybrid`: Stage 3 dual-write — sections gửi lên Zep graph_id=`<cid>` → server-side LLM extract → fetch nodes/edges/episodes → re-embed local → Cypher MERGE vào FalkorDB.

### Sim runtime graph

`graph_id="sim_<sid>"` — tạo ở prepare time qua `create_sim_zep_graph()`. Mỗi cuối round Phase 15 batched 10-node pipeline ghi episodes lên Zep + fetch delta → MERGE FalkorDB.

`finalize_sim_post_run()` khi sim COMPLETED → **delete Zep sim graph** để free quota.

### Cost

| Item | Cost |
|------|------|
| Master KG build (1 doc) | ~50-100 credits |
| Sim runtime per round | 5-15 credits |
| Total per sim (5-10 rounds) | 25-150 credits |
| Free tier | 1000 credits/month → ~7-20 sims |

## 7. Path resolution flow

Khi endpoint cần đường dẫn file của 1 sim, không hardcode — dùng helper:

```python
from ecosim_common.path_resolver import resolve_simulation_paths

paths = resolve_simulation_paths(sim_id, fallback=True)
# paths: dict với keys: sid, cid, sim_dir, config_path, profiles_path,
#        actions_path, oasis_db_path, progress_path, memory_stats_path,
#        kg_dir, zep_buffer_path, posts_chroma_dir, analysis_dir,
#        sentiment_path, tracking_path, ..., report_dir, ...
```

`fallback=True` → nếu sim không có trong meta.db, return path computed từ `Config.SIM_DIR/<sid>/` (legacy Phase 4 layout).

### Consumers

| Service | File | Cách dùng |
|---------|------|-----------|
| Core report endpoint | [apps/core/app/api/report.py](../apps/core/app/api/report.py) | `_sim_dir_from_meta(sim_id)` wrapper |
| Core ReportAgent | [apps/core/app/services/report_agent.py:_sim_dir](../apps/core/app/services/report_agent.py) | Wrapper với fallback |
| Core SimManager | [apps/core/app/services/sim_manager.py](../apps/core/app/services/sim_manager.py) | `_load_from_meta(row)` |
| Sim API | [apps/simulation/api/simulation.py](../apps/simulation/api/simulation.py) | `_sim_paths(sid)` |
| Sim interview/survey/graph | Each route file | Direct `resolve_simulation_paths` call |

## 8. Cleanup + deletion

### Per-campaign

`DELETE /api/campaign/<cid>` → cascade:
1. List sims thuộc campaign (meta.db).
2. Each sim: drop FalkorDB graph `sim_<sid>` + delete sim_dir.
3. Drop FalkorDB graph `<cid>` (master).
4. Delete campaign_dir.
5. Delete meta.db row (cascade qua FK `simulation_agents`, `sentiment_summaries`).

Cypher cascade trong [apps/simulation/api/graph.py:delete_campaign](../apps/simulation/api/graph.py).

### Per-sim

`DELETE /api/sim/<sid>` → drop sim graph + delete sim_dir + delete meta.db row.

### Eviction cron (Phase 12+)

`apps/simulation/sim_evict_cron.py` — quét sims COMPLETED quá X ngày cũ → optional drop FalkorDB graph để tiết kiệm memory (giữ filesystem snapshot).

## 9. Backup recipes

### FalkorDB snapshot

```bash
scripts/backup_falkordb.ps1    # Windows
scripts/backup_falkordb.sh     # Linux/macOS
```

Dump Redis RDB từ container vào `data/backups/`.

### Filesystem rsync

```bash
rsync -av data/ <backup-location>/ --exclude='*/chroma/cache'
```

ChromaDB cache có thể skip (sẽ rebuild from snapshot khi restore).

### Meta DB

`data/meta.db` — SQLite single file. Copy là backup. Restore: replace file → `init_schema()` chạy migration nếu version cũ.

## 10. Gotchas tổng hợp

- **Khi mất FalkorDB volume** → KG variants gone. Recover qua:
  - Campaign master: `POST /api/graph/restore?campaign_id=X` (5s từ snapshot.json)
  - Sim graph: cascade restore (master → fork clone → apply sim delta from `snapshot_delta.json`)
- **Khi mất meta.db** → Core boot auto-run `bootstrap_from_filesystem()` quét `data/campaigns/`. Mất một số metadata fields (created_at, status) nhưng paths re-computed OK.
- **2 venv khác Python**: Core `apps/core/.venv` Python 3.14, Sim `apps/simulation/.venv` Python 3.11. Cross-import KHÔNG OK — qua filesystem hợp đồng + meta.db only.
- **Atomic ordering invariant**: snapshot.json present ⇒ chroma đầy đủ. Order: chroma upsert + fsync trước, JSON ghi last.
- **Subprocess env**: `sim_runner` spawn `run_simulation.py` cần `LLM_API_KEY` + `PYTHONPATH` (bao gồm `libs/ecosim-common/src` + `vendored/oasis`). `run_simulation.py` auto-bootstrap walker tìm cả hai khi chạy độc lập.
- **Group isolation**: khi `/api/graph/ingest` thêm tài liệu, luôn pass `group_id=campaign_id` để không lẫn entity giữa campaigns.

## Đọc tiếp

- [02_architecture.md](02_architecture.md) — share state giữa services
- [03_ingestion_kg.md](03_ingestion_kg.md) — KG build pipeline + cache
- [reference.md](reference.md) — env vars + endpoints chi tiết

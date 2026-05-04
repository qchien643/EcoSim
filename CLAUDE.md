# CLAUDE.md — Hướng dẫn cho Claude Code agent

> File này dành cho Claude Code (CLI agent). Đọc trước khi chạm repo.
> Người dùng lần đầu xem [README.md](README.md) để cài đặt.
> Tài liệu kỹ thuật chi tiết: [docs/](docs/) — bắt đầu từ [docs/01_overview.md](docs/01_overview.md).

## 1. Dự án là gì

**EcoSim** — nền tảng mô phỏng động lực học mạng xã hội trong phản ứng với sự kiện xã hội (chiến dịch marketing, khủng hoảng, chính sách). Pipeline 5 bước: ingest tài liệu → build KG → sinh agent MBTI → round loop simulation → phân tích hậu sim.

**Khác biệt so với OASIS**: agent quyết định rule-based (posts_per_week × MBTI × period), semantic matching qua ChromaDB, KeyBERT adaptive interest drift, cross-round memory, write actions về KG. Chi tiết: [docs/01_overview.md](docs/01_overview.md).

## 2. Kiến trúc — microservice

| Service | Framework | Port | Entry | Vai trò |
|---------|-----------|------|-------|---------|
| Gateway | **Caddy 2** | 5000 | [apps/gateway/Caddyfile](apps/gateway/Caddyfile) | Reverse proxy + SSE forwarding |
| Core Service | Flask 3 | 5001 | [apps/core/run.py](apps/core/run.py) | Campaign + Report |
| Simulation Service | FastAPI + uvicorn | 5002 | [apps/simulation/sim_service.py](apps/simulation/sim_service.py) | Graph, Sim, Survey, Interview, Analysis |
| Frontend | **Next.js 16 (App Router) + TS + Tailwind 3** | 5173 | [apps/frontend/](apps/frontend/) | UI (campaign-centric, Linear-style) |
| FalkorDB | Redis fork | 6379 | Docker `falkordb/falkordb` | Graph DB (2 databases: `ecosim` + `ecosim_agent_memory`) |

**Shared library `ecosim_common`** ở [libs/ecosim-common/src/ecosim_common/](libs/ecosim-common/src/ecosim_common/) — dùng chung bởi Core + Simulation:
- `config.EcoSimConfig` — unified env loader + path helpers
- `llm_client.LLMClient` — sync (Flask) + async (FastAPI) OpenAI-compatible
- `file_parser.FileParser` + `CampaignDocumentParser` — document parsing (3-tier chunking + section-based)
- `atomic_io.atomic_write_json` / `atomic_append_jsonl` — tránh race condition khi nhiều service ghi cùng `data/simulations/{sim_id}/`

**Vendored upstream** ở [vendored/oasis/](vendored/oasis/) — camel-oasis (camel-ai) package được tách khỏi app code. `apps/simulation/run_simulation.py` bootstrap `vendored/oasis` vào `sys.path` để `import oasis` hoạt động. `poetry install` chạy từ `vendored/oasis/` — venv vẫn ở `apps/simulation/.venv/` để tách biệt với venv của Core (`venv/` ở root).

Bootstrap: `apps/core/run.py`, `apps/simulation/sim_service.py`, `apps/simulation/run_simulation.py` tự walk up tìm `libs/ecosim-common/src` và inject vào `sys.path`. Docker image set `PYTHONPATH=/app/libs/ecosim-common/src:/app/vendored/oasis`.

Client chỉ nói chuyện qua Gateway :5000. Gateway route theo prefix:
- `/api/campaign/*`, `/api/report/*` → Core
- `/api/sim/*`, `/api/graph/*`, `/api/survey/*`, `/api/interview/*`, `/api/analysis/*` → Simulation

Chi tiết: [docs/02_architecture.md](docs/02_architecture.md).

## 3. Tech stack

| Layer | Công nghệ |
|-------|-----------|
| LLM | `openai` SDK với `base_url` tuỳ biến (**KHÔNG** `anthropic` SDK) |
| Profile pool | Parquet 20M rows scan bằng DuckDB |
| Graph DB | FalkorDB qua `graphiti-core` |
| Vector DB | ChromaDB in-process, `all-MiniLM-L6-v2` |
| Keyword extraction | KeyBERT + sentence-transformers |
| Document parsing | PyMuPDF + LangChain splitters |
| Simulation runner | OASIS (camel-ai) subprocess — dùng `.venv` riêng `apps/simulation/.venv/` |
| Frontend stack | Next.js 16 App Router + React 19 + TypeScript strict + Tailwind 3 + Zustand + @tanstack/react-query v5 + Recharts + react-markdown + lucide-react |

## 4. Bản đồ source

```
EcoSim/
├── CLAUDE.md                          ← file này
├── README.md                          ← human quick-start
├── pyrightconfig.json                 ← IDE typing (points to libs + vendored)
├── docs/                              ← tài liệu kỹ thuật (8 files)
├── .env / .env.example                ← LLM + FalkorDB + port config
├── docker-compose.yml                 ← 5-service stack (Caddy gateway + Core + Sim + Falkor + Frontend)
│
├── scripts/                           ← dev scripts
│   ├── start.ps1 / stop.ps1 / restart.ps1
│
├── libs/                              ← ★ Shared Python libraries
│   └── ecosim-common/
│       ├── pyproject.toml
│       └── src/ecosim_common/
│           ├── atomic_io.py           ← atomic_write_json, atomic_append_jsonl
│           ├── config.py              ← EcoSimConfig (single source of truth)
│           ├── llm_client.py          ← LLMClient sync + async
│           ├── file_parser.py         ← FileParser + CampaignDocumentParser
│           ├── chroma_client.py       ← Phase A: KG ChromaDB factories (master + sim delta)
│           ├── zep_client.py          ← Phase A: AsyncZep singleton
│           ├── zep_label_map.py       ← Phase A: Zep labels → canonical mapper
│           └── sim_zep_ontology.py    ← Phase E.2: 10 entity + 10 edge sim ontology
│
├── vendored/                          ← ★ Upstream third-party (camel-ai)
│   └── oasis/                         ← camel-oasis: pyproject, poetry.lock, oasis/, generator/, visualization/, test/, examples/, assets/, licenses/, docs/, LICENSE, CONTRIBUTING.md, .pre-commit-config.yaml
│
├── apps/                              ← ★ EcoSim services
│   ├── gateway/                       ← Caddy reverse proxy :5000
│   │   ├── Caddyfile                  ← ★ current gateway config
│   │   ├── gateway.py.bak             ← legacy Python proxy (fallback nếu Caddy không có)
│   │   └── Dockerfile + requirements.txt   ← chỉ dùng khi fallback
│   │
│   ├── core/                          ← Core Service :5001 (Flask)
│   │   ├── run.py
│   │   ├── app/
│   │   │   ├── __init__.py            ← blueprint: campaign_bp + report_bp
│   │   │   ├── api/
│   │   │   │   ├── campaign.py        ← REGISTERED
│   │   │   │   ├── report.py          ← REGISTERED
│   │   │   │   ├── graph.py           ← legacy, not registered
│   │   │   │   ├── simulation.py      ← legacy, not registered
│   │   │   │   └── survey.py          ← legacy, not registered
│   │   │   ├── services/              ← 18 services (chi tiết §5)
│   │   │   ├── models/                ← Pydantic (campaign, simulation, ontology, survey)
│   │   │   └── utils/
│   │   │       ├── llm_client.py      ← thin adapter → ecosim_common.llm_client
│   │   │       └── file_parser.py     ← 3-tier chunking (legacy; dùng ecosim_common.file_parser)
│   │   └── tests/
│   │
│   ├── simulation/                    ← Simulation Service :5002 (FastAPI) — chỉ EcoSim code
│   │   ├── sim_service.py             ← uvicorn app
│   │   ├── api/                       ← simulation.py, graph.py, report.py, survey.py, interview.py
│   │   ├── run_simulation.py          ← ★ SUBPROCESS ENTRY (60KB, 1300+ lines)
│   │   ├── agent_cognition.py         ← memory + MBTI + KeyBERT drift
│   │   ├── crisis_engine.py
│   │   ├── interest_feed.py           ← semantic matching + rule-based decisions
│   │   ├── falkor_graph_memory.py     ← ★ Phase E hybrid dispatch (structural Cypher + Zep content)
│   │   ├── campaign_knowledge.py      ← Stage 1+2 LLM extract (sections + entities/facts)
│   │   ├── sentiment_analyzer.py
│   │   ├── kg_direct_writer.py        ← Phase A: direct Cypher master KG build path
│   │   ├── zep_kg_writer.py           ← Phase A: Zep hybrid master KG build path
│   │   ├── zep_ontology.py            ← Phase A: master 10 entity + 10 edge ontology
│   │   ├── kg_fork.py                 ← Master → sim graph cloner + Phase D auto-restore guard
│   │   ├── kg_snapshot.py             ← Phase A-B: master KG persist (write_snapshot, restore_to_falkordb, dump_from_falkordb migration)
│   │   ├── sim_kg_snapshot.py         ← Phase D.4: sim delta persist + cascade_restore_sim
│   │   ├── sim_zep_writer.py          ← Phase 13: ZepContentBuffer + finalize_sim_zep (semantic-only path)
│   │   ├── ingest_campaign.py / deploy.py
│   │   ├── test_crisis.py / test_full_integration.py
│   │   ├── Dockerfile                 ← context = repo root, copy vendored/oasis + apps/simulation
│   │   └── .venv/                     ← ★ Poetry venv (built từ vendored/oasis/pyproject.toml)
│   │
│   └── frontend/                      ← Frontend — Next.js 16 :5173
│       ├── app/                        ← App Router (campaign-centric IA)
│       │   ├── layout.tsx, providers.tsx, globals.css, page.tsx (Dashboard)
│       │   ├── campaigns/page.tsx     ← list
│       │   ├── campaigns/new/page.tsx ← upload
│       │   └── campaigns/[campaignId]/
│       │       ├── layout.tsx          ← workspace tabs (Overview · Spec · Graph · Sims)
│       │       ├── page.tsx, spec/, graph/
│       │       └── sims/page.tsx, sims/[simId]/{layout,page,analysis,report,survey,interview}.tsx
│       ├── components/
│       │   ├── ui/                     ← primitives: button, input, badge, card, tabs, dialog, kbd, separator
│       │   ├── data/                   ← data-table, skeleton, empty-state, error-state, section-stub
│       │   └── shell/                  ← app-shell, sidebar, topbar, command-palette, toast-host
│       ├── lib/
│       │   ├── api/                    ← typed fetch: client, campaign, sim, graph, analysis, report, survey, interview, health
│       │   ├── queries/index.ts        ← @tanstack/react-query hooks + qk key factory
│       │   ├── types/backend.ts        ← TS mirror of Pydantic schemas
│       │   └── utils.ts                ← cn(), formatDate, formatAge, truncate
│       ├── stores/                     ← Zustand: app-store (persist via LS) + ui-store (sidebar, palette, toasts)
│       ├── hooks/                      ← use-hydration, use-sse (EventSource wrapper)
│       ├── tailwind.config.ts          ← Linear-style palette (zinc + brand violet)
│       ├── next.config.ts              ← rewrites /api/* → gateway (env GATEWAY_UPSTREAM)
│       ├── Dockerfile                  ← multi-stage Node, output=standalone
│       └── package.json                ← Next 16 + React 19 + TS strict
│

├── venv/                              ← Core Service Python venv (gitignored)
└── data/                              ← gitignored runtime
    ├── samples/, dataGenerator/       ← parquet profile pool
    ├── uploads/                       ← per-campaign storage (xem §11 "Per-campaign layout")
    │   └── {campaign_id}/
    │       ├── source/{filename}      ← tài liệu gốc (immutable sau upload)
    │       ├── extracted/             ← cache LLM extract stages
    │       │   ├── spec.json           ← CampaignSpec (Stage 1)
    │       │   ├── sections.json       ← parsed sections (Stage 2)
    │       │   └── analyzed.json       ← entities + facts (Stage 3, đắt nhất, cache reuse)
    │       ├── kg/build_meta.json     ← KG build metadata
    │       └── sims.json              ← manifest list sims thuộc campaign
    └── simulations/{sim_id}/          ← profiles.json, simulation_config.json, oasis_simulation.db, actions.jsonl, crisis_scenarios.json, progress.json, memory_stats.json, report/
```

## 5. Services quan trọng (apps/core/app/services/)

| File | Vai trò |
|------|---------|
| `campaign_parser.py` | Parse upload + LLM extract CampaignSpec |
| `ontology_generator.py` | LLM sinh OntologySpec động theo campaign_type |
| `graph_builder.py` | Graphiti-first + raw Cypher fallback |
| `graphiti_service.py` | Singleton Graphiti client (FalkorDriver) |
| `profile_generator.py` | **LEGACY, test-only.** Production path đã chuyển sang `apps/simulation/api/simulation.py:_generate_profiles` (Tier B, xem docs/04) |
| `sim_config_generator.py` | LLM sinh TimeConfig + EventConfig |
| `crisis_injector.py` | LLM sinh 7 loại crisis scenario |
| `sim_manager.py` | State machine CREATED→PREPARING→READY→RUNNING→COMPLETED |
| `sim_runner.py` | Spawn subprocess `run_simulation.py`, SSE |
| `agent_memory.py` | FIFO 5-round + FalkorDB `ecosim_agent_memory` graph |
| `graph_memory_updater.py` | Batch write actions vào FalkorDB memory graph |
| `graph_query.py` | Cypher queries cho KG |
| `kg_retriever.py` | Tool adapter cho report_agent |
| `report_agent.py` | ReACT 2-phase: outline → per-section |
| `survey_engine.py` | Bulk Q&A runner |
| `utils/llm_client.py` | Adapter — re-export `ecosim_common.llm_client.LLMClient`. **Đừng gọi OpenAI() trực tiếp** |

**Shared utilities (libs/ecosim-common/src/ecosim_common/):**

| Module | Vai trò |
|--------|---------|
| `agent_schemas.py` | Pydantic: `AgentProfile`, `EnrichedAgentLLMOutput`, `BatchEnrichmentResponse`, `MBTI_TYPES` |
| `name_pool.py` | `NamePool(seed).pick(gender=...)` — gender-aware dedup (100 họ × 17-20 đệm × ~50 tên/gender) |
| `parquet_reader.py` | `ParquetProfileReader` — DuckDB sample, seed reproducible, allowlist-sanitize domain strings |
| `llm_client.py` | `LLMClient.chat_async / chat_json_async` — retry, strip code fences, dùng cho Sim async pipeline |

## 6. LLM conventions (quan trọng)

- **Provider**: `openai` SDK với `base_url` tuỳ biến. **Không phải** `anthropic` SDK. Hỗ trợ: OpenAI, Groq, Together AI, Ollama, OpenRouter, hoặc bất kỳ endpoint OpenAI-compatible nào.
- **Cấu hình qua `.env`**: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` (mặc định `gpt-4o-mini`).
- **Model tier** (3 layer, cùng provider):
  - `LLM_MODEL_NAME` — main reasoning (default `gpt-4o-mini`): report ReACT, sim profile gen, crisis injection, sim config gen.
  - `LLM_FAST_MODEL_NAME` (optional, default = main) — high-frequency in-character calls: interview/survey reply, intent classifier.
  - `LLM_EXTRACTION_MODEL` (default `gpt-4o`) — STRONGER cho extraction stages của KG build pipeline (CampaignParser Stage 1 + CampaignSectionAnalyzer Stage 3). Đắt hơn ~5× nhưng precision cao cho Vietnamese business docs. Cost mitigated bởi cache `extracted/sections.json` + `analyzed.json`.
- **Mọi call LLM đi qua `LLMClient`** (ở `ecosim_common.llm_client`, re-export qua `app.utils.llm_client`) — đừng gọi `OpenAI()` trực tiếp ở service nào khác:
  - Sync (Core/Flask): `llm.chat(...)`, `llm.chat_json(...)`, `llm.chat_with_prompt(...)`
  - Async (Simulation/FastAPI): `llm.chat_async(...)`, `llm.chat_json_async(...)`
  - Per-call model override: pass `model=EcoSimConfig.llm_extraction_model_name()` (hoặc fast/main) để tier tùy stage.
  - Retry 3 lần + strip code fences tự động cho JSON responses
- **Không** migrate sang `anthropic` SDK hay prompt caching Anthropic. Nếu muốn dùng Claude, set `LLM_BASE_URL` trỏ tới endpoint Claude-compatible và đổi `LLM_MODEL_NAME` — code không cần đổi.

## 7. Chạy dự án

Xem chi tiết: [README.md](README.md).

Quick-start Docker (5 container):
```bash
docker compose up -d
```

Quick-start local dev (Windows):
```powershell
.\scripts\start.ps1   # spawn 5 terminal: falkordb, core, simulation, gateway, frontend
```

Chỉ backend + 1 service (phát triển nhanh):
```bash
docker compose up -d falkordb
cd apps/core && python run.py                                   # :5001
cd apps/simulation && .venv/Scripts/python -m uvicorn sim_service:app --port 5002  # :5002
caddy run --config apps/gateway/Caddyfile                       # :5000
cd apps/frontend && npm run dev                                 # :5173 (Next.js)
```

Nếu cần rebuild venv simulation:
```bash
cd vendored/oasis && poetry install   # tạo .venv ở apps/simulation/.venv — xem Dockerfile để hiểu flow
cd ../../apps/simulation && .venv/Scripts/python -m pip install -r requirements-extra.txt   # EcoSim-only deps (keybert ...)
```
Trên Linux dùng `.venv/bin/python` thay `.venv/Scripts/python.exe`. Bỏ bước thứ hai = `[COGNITION] KeyBERT not installed, using N-gram fallback` (cognitive vẫn chạy nhưng chất lượng kém).

Test:
```bash
cd apps/core && python -m pytest tests/ -v
```

## 8. Runtime flow (high-level)

1. **Upload** → `POST /api/campaign/upload` → save file gốc tại `data/uploads/{id}/source/`, LLM extract (gpt-4o) → `data/uploads/{id}/extracted/spec.json`.
2. **Build KG** → `POST /api/graph/build` → OntologyGenerator → Graphiti ingest → FalkorDB (`ecosim` db, group_id=campaign_id).
3. **Prepare** → `POST /api/sim/prepare` → ProfileGenerator (DuckDB + LLM) → SimConfigGenerator → CrisisInjector → ghi `data/simulations/{sim_id}/`.
4. **Start** → `POST /api/sim/start` → sim_runner spawn subprocess `apps/simulation/run_simulation.py` với `.venv` riêng. Round loop 5 phase: crisis → reflection → posting → re-index → interactions → persistence + memory + drift.
5. **Stream** → `GET /api/sim/{id}/stream` (SSE) — progress qua gateway.
6. **Analyze** → 4 flow độc lập sau `COMPLETED`: Report (ReACT + 4 tools), Interview (per-agent chat), Survey (bulk Q&A), Sentiment Analysis.

## 9. Quy ước code

- **Python**: type hints, Pydantic models ở `apps/core/app/models/`, logger theo prefix `ecosim.*` (Core) / `sim-svc.*` (Simulation).
- **Ngôn ngữ**: domain terms tiếng Việt OK trong prompts + content; identifier/code tiếng Anh.
- **SSE**: dùng cho simulation progress; Caddy gateway có `flush_interval -1` không buffering.
- **Paths**: Windows host nhưng bash env — trong code Python dùng `pathlib.Path` hoặc `/`, đừng hard-code `\\`.

## 10. Đừng động vào

| Path | Lý do |
|------|-------|
| `vendored/oasis/**` | Upstream camel-ai OASIS — patch sẽ lệch upstream. Nếu cần thay đổi hành vi, override ở `apps/simulation/` |
| `apps/simulation/.venv/`, `venv/`, `log/`, `__pycache__/`, `data/`, `uploads/` | Runtime, đã gitignore |
| `apps/core/app/api/{graph,simulation,survey}.py` | Legacy Flask blueprints, đã chuyển sang Simulation Service. Giữ làm tham chiếu; KHÔNG tự ý register lại |

## 11. Known gotchas

- **KG persistence layer — JSON snapshot + ChromaDB primary, FalkorDB ephemeral** (Phase A-D): Source of truth = `uploads/<cid>/kg/snapshot.json` (structure ~300KB) + `chroma/` (3 collections, ~2.4MB). FalkorDB `<cid>` graph là load-on-demand cache cho Graphiti hybrid search. Khi mất FalkorDB volume → `POST /api/graph/restore?campaign_id=X` reload từ disk (~5s, no API calls). Frontend tri-state: `fresh` | `snapshot_only` | `active` qua `GET /api/graph/cache-status?campaign_id=X`. Migration cũ: `POST /api/graph/snapshot?campaign_id=X` dump from FalkorDB (one-time, không re-embed). Sim KG dùng delta-only persistence: `data/simulations/<sid>/kg/snapshot_delta.json` + `chroma_delta/` (chỉ entities/edges sinh mới trong sim, không duplicate master). Cascade restore: master → fork → apply delta. Atomic invariant: snapshot.json present ⇒ chroma đầy đủ (chroma upsert + fsync trước, JSON last). Chi tiết: `apps/simulation/kg_snapshot.py` + `sim_kg_snapshot.py` module headers.
- **Sim runtime — section-per-action via Zep, end-of-round sync** (Phase 15): Mỗi cuối round trong `apps/simulation/run_simulation.py`:
  - **Structural actions** (like, follow, vote, sign_up, repost) → DROP. Sống trong `oasis_simulation.db` SQLite. Frontend social feed `GET /api/sim/<sid>/feed` query SQL.
  - **Content actions** (create_post + create_comment với content >=30 chars) → `apps/simulation/sim_zep_section_writer.write_round_sections_via_zep()` chạy 10 nodes pipeline:
    1. Filter content traces → 2. Enrich agent name + role (KHÔNG dùng MBTI) → 3. Convert mỗi trace → 1 section text natural Vietnamese ("{name} ({role}) đăng bài viết tại Round N: ..." hoặc "{name} ({role}) bình luận tại Round N trên bài viết của {parent}: ...") → 4. Build `EpisodeData(type="text")` list → 5. `zep.graph.add_batch` + poll until processed (timeout 180s) → 6. Fetch nodes/edges/episodes (cumulative state Zep server) → 7. Filter delta (loại entities trùng master campaign graph) → 8. Re-embed local 4 batch (Zep KHÔNG expose embeddings) → 9. Cypher MERGE multi-label `:Entity:Brand`, edges với fact, `:Episodic`, `:MENTIONS` → 10. Reroute extracted Agent → seeded `:SimAgent` (idempotent, mỗi round chạy lại OK).
  - **Round N+1** cognitive query (`GraphCognitiveHelper.get_social_context()`) thấy data round 1..N (real-time cumulative).
  - **Sim COMPLETED**: `finalize_sim_post_run()` chạy 1 lần — Node 11 build Graphiti HNSW + lookup indices, Node 12 delete Zep sim graph (free quota).
  - **Yêu cầu**: `ZEP_API_KEY` + `ZEP_SIM_RUNTIME=true`. Prepare flow: `create_sim_zep_graph` apply sim ontology (10 entity + 10 edge tại `libs/ecosim-common/src/ecosim_common/sim_zep_ontology.py`).
  - **Cost**: 5-15 Zep credits/round × 5-10 rounds = 25-150 credits/sim. Free tier 1000/mo = ~7-20 sims.
  - **Graph chứa**: `:SimAgent` (anchors, seeded prepare), `:Entity` master clone (Layer 1), `:Entity` Zep extract (Layer 3, source='zep_extract'), `:Episodic`. Không còn `:Post`, `:Comment`, `[:POSTED]`, `[:LIKED]`, `[:FOLLOWED]`, `[:VOTED_*]`, `[:REPOSTED]`.
  - **Pattern đối xứng** với master KG `apps/simulation/zep_kg_writer.write_kg_via_zep` — reuse 3 helpers `_normalize_edge_type`, `_safe_attr_value`, `_to_iso` module-level.
- **KG build pipeline — bypass Graphiti extraction**: Stage 3b `apps/simulation/kg_direct_writer.write_kg_direct()` viết trực tiếp Cypher từ Stage 2 entities/facts thay vì gọi `Graphiti.add_episode` (which re-extract LLM 4-5 calls/section = 60+ phút duplicate work). 3 batch embedding API calls + Cypher MERGE → ~10-30s tổng. Zero info loss vì Stage 2 extract bằng `LLM_EXTRACTION_MODEL` (gpt-4o tier). Trade-off acceptable: bỏ Graphiti edge invalidation (master KG static, không có temporal updates) + bỏ smart entity dedup (Stage 2.5 `postprocess_entities` đã dedup). KEEP `CampaignGraphLoader.load()` legacy cho future incremental updates nếu cần. Bypass docstring chi tiết: `kg_direct_writer.py` module header.
- **Per-campaign storage layout**: Mỗi campaign 1 thư mục `<UPLOAD_DIR>/<campaign_id>/` chứa `source/<filename>` (immutable), `extracted/{spec,sections,analyzed}.json` (LLM cache), `kg/build_meta.json`, `sims.json`. Layout cũ flat (`<id>_spec.json`, `<id>_sims.json`) đã deprecated — không support nữa. Helpers ở `EcoSimConfig.campaign_{dir,source_dir,extracted_dir,kg_dir}(campaign_id)`.
- **Build idempotent + cache**: `/api/graph/build` reuse `extracted/sections.json` + `analyzed.json` nếu tồn tại → skip Stage 2+3 LLM (gpt-4o), chỉ chạy Stage 5 (FalkorDB MERGE). User force re-extract bằng `rm -rf <UPLOAD_DIR>/<campaign_id>/extracted/`. Cache version field `_version=1` trong file; bump khi schema `DocumentSection`/`AnalyzedSection` đổi → load fail → re-extract auto.
- **Extraction tier model**: `LLM_EXTRACTION_MODEL` (default `gpt-4o`) đắt hơn ~5× main model nhưng tăng precision cho Vietnamese business docs (ít nhầm "Brand"→"Company", catch implicit relationships). Chỉ chạy ở Stage 1 (CampaignParser._extract_campaign_spec) + Stage 3 (CampaignSectionAnalyzer.analyze). Mọi LLM call khác vẫn dùng `LLM_MODEL_NAME` để tiết kiệm.
- **FalkorDB phải chạy** (`docker compose up -d falkordb`) trước khi Core/Simulation boot — không có fallback.
- **Subprocess env**: `sim_service` spawn `run_simulation.py` cần `LLM_API_KEY` + `PYTHONPATH` (bao gồm `libs/ecosim-common/src` + `vendored/oasis`). `run_simulation.py` auto-bootstrap walker để tìm cả hai khi chạy độc lập.
- **Simulation .venv separate**: `run_simulation.py` chạy bằng `apps/simulation/.venv/Scripts/python.exe`, không phải venv của Core (`venv/` ở root). Nếu miss dependency, `cd vendored/oasis && poetry install` để rebuild venv.
- **FalkorDB 2 databases**: `ecosim` (campaign KG, dùng trong Core/Sim) vs `ecosim_agent_memory` (agent memory, chỉ khi `enable_graph_cognition=true`). Đừng nhầm.
- **Atomic writes**: file state trong `data/simulations/{sim_id}/` dùng `ecosim_common.atomic_io.atomic_write_json` (1-shot) hoặc `atomic_append_jsonl` (incremental). `actions.jsonl` hiện append từng record — đừng rewrite file.
- **Long LLM chains**: `report_agent.py` dùng batch calls. Rate-limit → tăng `max_retries` ở `LLMClient`.
- **OASIS SQLite**: mỗi sim có DB riêng ở `data/simulations/{sim_id}/oasis_simulation.db`. Đừng share giữa sims.
- **Parquet 20M rows**: DuckDB query phải có `LIMIT` hoặc filter — scan full là OOM.
- **ChromaDB per-sim + persistent** (Tier B): `PostIndexer(sim_id, persist_dir=sim_dir/chroma)` — collection `ecosim_{sim_id}` sống trong `data/simulations/{sim_id}/chroma/`, survive subprocess crash. Đừng init `PostIndexer()` không arg.
- **Post probability formula** (Tier B): `get_post_probability(profile, hours_per_round)` chia theo simulation_hours/num_rounds, không phải `/7.0`. `should_post(..., period_mult=...)` áp `period_multipliers` từ TimeConfig.
- **Crisis perturbation relevance** (Tier B): `compute_agent_relevance` scale perturbation theo Jaccard giữa crisis keywords/domains và agent interests. Agent không match vẫn có floor 0.2.
- **Crisis/Seed post author strategy** (Tier B): `simulation_config.crisis_author_strategy` = `"agent_0" | "influencer" | "system"`. Resolve qua `CrisisEngine.resolve_author_id`.
- **Graph memory KHÔNG cleanup**: post-simulation (Report, Interview, Survey) đọc từ `ecosim_agent_memory`. Giữ nodes/edges sau sim là intentional.
- **Evolved persona** (Tier B): sau mỗi reflection cycle, `profiles.json` được append `persona_evolved` + `reflection_insights` (atomic write). Resume logic chưa auto — manual dùng `persona_evolved` nếu có.
- **memory_stats.json** (Tier B): `AgentMemory.dump_stats()` ghi mỗi round. Dùng để debug buffer fullness + LLM injection count.
- **Group isolation**: khi `/api/graph/ingest` thêm tài liệu, luôn pass `group_id=campaign_id` để không lẫn entity giữa campaigns.
- **Docker build context = repo root** cho simulation (cần copy cả `vendored/oasis` và `apps/simulation`). Xem `apps/simulation/Dockerfile` + `docker-compose.yml`.
- **Report không bịa số** (Tier B++): `SIM_DATA_CAPABILITIES` constant trong `report_agent.py` liệt kê rõ sim CÓ/KHÔNG trace gì. `_tool_kpi_check` pre-classify KPI nào `unmeasurable` (revenue/orders/CTR/satisfaction) → LLM không thể bịa. Nếu thấy report chứa "1 tỷ VNĐ", "15000 đơn hàng" → check `agent_log.jsonl` grep `fabrication_warning`.
- **Fast model cho Phase-3 answers**: Interview (`apps/simulation/api/interview.py`), Survey (`apps/simulation/api/survey.py:conduct_survey`), và Report tool `interview_agents` tất cả route per-agent reply qua `LLM_FAST_MODEL_NAME` (fallback `LLM_MODEL_NAME`). Shared primitives ở `ecosim_common.agent_interview` — 10 canonical intents + `INTENT_INFO_MAP` + `load_context_blocks` + `build_response_prompt`. **Report section writer (outline + ReACT loop) vẫn dùng main model** vì cần reason over tools + evidence. Nếu override fast model, set `LLM_FAST_MODEL_NAME` trong `.env` (vd `gpt-4o-mini`, `llama-3.1-8b-instant` cho Groq, `llama3.1:8b` cho Ollama local).
- **Survey `report_section` field** (Tier B++): mỗi câu hỏi tag target Report section (`context/content/kpi/response/recommendation`). Survey generator + `_tool_survey_result` group by section. Thêm manual question nên set `report_section` để Report cite đúng chỗ.
- **`interview_agents` tool** (Tier B++): Report có thể phỏng vấn real-time X% agents (hard cap 20) trong lúc generate — evidence source=MEM. Hữu ích cho Section 3 (motivations) + Section 5 (crisis reaction qualitative).
- **Frontend = Next.js 16 ở `apps/frontend/`** (Vue đã xóa): campaign-centric IA — routes là `/campaigns/[id]/...` chứ không có pipeline stepper. State persistence qua Zustand `persist` middleware → localStorage key `ecosim.app`. Backend không đổi: Next `rewrites` `/api/*` → `${GATEWAY_UPSTREAM || 'http://localhost:5000'}` server-side, browser luôn same-origin. SSE qua `EventSource` wrapped trong `hooks/use-sse.ts`.
- **Docker frontend**: build từ `apps/frontend/Dockerfile` (multi-stage Node 20-alpine → `next.config.ts` `output: 'standalone'` → tiny `.next/standalone/server.js`). Compose service `frontend` set `GATEWAY_UPSTREAM=http://gateway:5000` để Next rewrites hit Caddy container. Port mapping `5173:5173`.
- **Frontend dev port 5173**: production build = `npm run build` (xuất `.next/standalone/`). Standalone needs `.next/static/` + `public/` copied alongside — Dockerfile đã handle.
- **TypeScript strict mode**: `apps/frontend/tsconfig.json` đang `strict: true`. Nếu add view mới, dùng `T extends object` cho generic constraint thay vì `Record<string, unknown>` (CampaignSummary etc. không có index signature).
- **Tailwind theme**: tokens trong `tailwind.config.ts` (zinc + brand violet 600). KHÔNG có Memphis tokens nữa. Nếu cần thêm color, extend ở `theme.extend.colors` rồi dùng utility (`bg-brand-500`, `text-fg-muted`). Tránh inline arbitrary `bg-[#...]`.
- **Tailwind arbitrary value + `theme()`**: Tailwind v3 KHÔNG resolve `theme(spacing.x-y)` bên trong `[]` arbitrary values khi token key có hyphen (như `sidebar-collapsed`). Output CSS rỗng → layout collapse. Always dùng literal: `grid-cols-[256px_1fr]`, `w-[56px]`, `h-12`. Nếu cần token reuse, định nghĩa class trong `globals.css` `@layer components`.
- **CSS colors — dùng FLAT names, không nested DEFAULT**: `tailwind.config.ts` define colors ở dạng flat (`fg: '#09090b'`, `'fg-muted': '#52525b'`), không dùng object với `DEFAULT` + variant keys (`fg: { DEFAULT: '...', muted: '...' }`). Tránh edge case resolution + đảm bảo `bg-fg` / `text-fg-muted` compile 1:1 với hex value.
- **Shell layout — dùng fixed sidebar + `md:ml-[Npx]` thay vì CSS Grid**: `components/shell/app-shell.tsx` dùng pattern `<div flex min-h-screen><Sidebar position:fixed /><div class="md:ml-[var(--sb-w)]"><TopBar /><main>{children}</main></div></div>`. Sidebar fixed-positioned (không chiếm grid space), main content offset qua `margin-left` — đơn giản + tránh grid collapse khi fixed-positioned child đẩy nội dung ra 0 width. CSS var `--sb-w` set inline trên root: `style={{ '--sb-w': collapsed ? '56px' : '256px' }}`.
- **Triệu chứng "content invisible at 100% zoom, visible at 200%"**: thường là main pane có width = 0 (grid/flex item collapse) hoặc fixed-positioned overlay phủ content. Kiểm tra: (1) compiled CSS có `.md\:ml-...` / `.grid-cols-...` rule không (`curl http://localhost:5173/_next/static/chunks/...css | grep`), (2) inline `style` attribute trên shell root có đúng không, (3) HTML `<main>` inner length > 0. Nếu rule trong CSS có nhưng content vẫn ẩn → check layout pattern (prefer fixed sidebar + margin-left offset, không CSS Grid với fixed child).
- **Turbopack cache corruption**: nếu dev server panic `Failed to open SST file ... .next/dev/cache/turbopack/*.sst`, cache đã hỏng (thường do `rm -rf .next` lúc dev đang chạy, hoặc kill -9 mid-write). Fix: `stop.ps1 -Only frontend -KeepDocker` → `Remove-Item -Recurse -Force apps/frontend/.next` → `start.ps1 -Only frontend -SkipDocker`. Đừng xóa `.next/` khi dev đang chạy.
- **Hydration guard cho Zustand persist**: `useAppStore` dùng `persist` middleware đọc từ localStorage. Server render với initial state, client hydrate với LS state — mismatch gây React warning + đôi khi vô hiệu hóa render. Components đọc persisted state phải gate qua `useHydrated()` hook (xem `hooks/use-hydration.ts`) hoặc dùng `_hasHydrated` flag — examples ở `Sidebar.tsx` (`recentIds`, `collapsed`) và `AppShell.tsx` (`collapsed`).

## 12. Debugging tips

- Core logs: `apps/core/log/` hoặc stdout — prefix `ecosim.<module>`.
- Simulation logs: `apps/simulation/log/` hoặc stdout — prefix `sim-svc.<module>` / `run_simulation.<module>`.
- Actions của một sim: `data/simulations/{sim_id}/actions.jsonl` (1 action/line).
- Cognitive snapshot: `data/simulations/{sim_id}/agent_tracking.txt`.
- ReACT trace: `data/simulations/{sim_id}/report/agent_log.jsonl`.
- KG inspection: FalkorDB Browser ở http://localhost:3000 (FalkorDB image ship kèm UI).
- Gateway health: `GET http://localhost:5000/api/health` — probe Core + Sim.

## 13. Tài liệu mở rộng

| Để hiểu | Đọc |
|---------|-----|
| Pipeline 5 bước tổng quan | [docs/01_overview.md](docs/01_overview.md) |
| Kiến trúc microservice chi tiết | [docs/02_architecture.md](docs/02_architecture.md) |
| Upload → KG pipeline | [docs/03_ingestion_kg.md](docs/03_ingestion_kg.md) |
| Sinh agent + sim config | [docs/04_agent_generation.md](docs/04_agent_generation.md) |
| **Round loop + KeyBERT + memory + crisis** | [docs/05_simulation_loop.md](docs/05_simulation_loop.md) |
| Hậu mô phỏng — overview hub | [docs/06_post_simulation.md](docs/06_post_simulation.md) |
| Sentiment Analysis | [docs/06a_sentiment_analysis.md](docs/06a_sentiment_analysis.md) |
| Survey (+ auto-generate questions) | [docs/06b_survey.md](docs/06b_survey.md) |
| Interview (chat với agent) | [docs/06c_interview.md](docs/06c_interview.md) |
| Report ReACT (consume sentiment + survey) | [docs/06d_report.md](docs/06d_report.md) |
| Endpoints + env vars + schemas | [docs/reference.md](docs/reference.md) |

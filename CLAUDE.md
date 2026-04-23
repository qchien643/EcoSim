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
| Frontend | Vue 3 + Vite | 3000 / 5173 | [apps/frontend/](apps/frontend/) | UI |
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
│           └── file_parser.py         ← FileParser + CampaignDocumentParser
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
│   │   ├── falkor_graph_memory.py
│   │   ├── campaign_knowledge.py
│   │   ├── sentiment_analyzer.py
│   │   ├── ingest_campaign.py / deploy.py
│   │   ├── test_crisis.py / test_full_integration.py
│   │   ├── Dockerfile                 ← context = repo root, copy vendored/oasis + apps/simulation
│   │   └── .venv/                     ← ★ Poetry venv (built từ vendored/oasis/pyproject.toml)
│   │
│   └── frontend/                      ← Vue 3 SPA :5173 / :3000
│       └── src/
│           ├── api/client.js          ← axios wrapper (campaignApi, graphApi, simApi, reportApi, surveyApi, interviewApi)
│           ├── router/index.js        ← step-lock guard
│           ├── stores/appStore.js     ← Pinia, NO persistence (fresh state per load)
│           ├── views/                 ← 9 views: Dashboard, Campaign, Graph, Simulation, Analysis, Report, Survey, Interview, Cognitive
│           └── components/            ← AppSidebar, MemphisDeco
│
├── venv/                              ← Core Service Python venv (gitignored)
└── data/                              ← gitignored runtime
    ├── samples/, dataGenerator/       ← parquet profile pool
    ├── uploads/                       ← campaign files + {id}_spec.json
    └── simulations/{sim_id}/          ← profiles.json, simulation_config.json, oasis_simulation.db, actions.jsonl, crisis_scenarios.json, progress.json, memory_stats.json, report/
```

## 5. Services quan trọng (apps/core/app/services/)

| File | Vai trò |
|------|---------|
| `campaign_parser.py` | Parse upload + LLM extract CampaignSpec |
| `ontology_generator.py` | LLM sinh OntologySpec động theo campaign_type |
| `graph_builder.py` | Graphiti-first + raw Cypher fallback |
| `graphiti_service.py` | Singleton Graphiti client (FalkorDriver) |
| `profile_generator.py` | DuckDB sample parquet → LLM batch enrich + MBTI |
| `parquet_reader.py` | 60% domain / 40% diversity sampling |
| `name_pool.py` | Vietnamese name pool |
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

## 6. LLM conventions (quan trọng)

- **Provider**: `openai` SDK với `base_url` tuỳ biến. **Không phải** `anthropic` SDK. Hỗ trợ: OpenAI, Groq, Together AI, Ollama, OpenRouter, hoặc bất kỳ endpoint OpenAI-compatible nào.
- **Cấu hình qua `.env`**: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` (mặc định `gpt-4o-mini`).
- **Mọi call LLM đi qua `LLMClient`** (ở `ecosim_common.llm_client`, re-export qua `app.utils.llm_client`) — đừng gọi `OpenAI()` trực tiếp ở service nào khác:
  - Sync (Core/Flask): `llm.chat(...)`, `llm.chat_json(...)`, `llm.chat_with_prompt(...)`
  - Async (Simulation/FastAPI): `llm.chat_async(...)`, `llm.chat_json_async(...)`
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
cd apps/frontend && npm run dev                                 # :5173
```

Nếu cần rebuild venv simulation:
```bash
cd vendored/oasis && poetry install   # tạo .venv ở apps/simulation/.venv — xem Dockerfile để hiểu flow
```

Test:
```bash
cd apps/core && python -m pytest tests/ -v
```

## 8. Runtime flow (high-level)

1. **Upload** → `POST /api/campaign/upload` → LLM extract CampaignSpec → `data/uploads/{id}_spec.json`.
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

- **FalkorDB phải chạy** (`docker compose up -d falkordb`) trước khi Core/Simulation boot — không có fallback.
- **Subprocess env**: `sim_service` spawn `run_simulation.py` cần `LLM_API_KEY` + `PYTHONPATH` (bao gồm `libs/ecosim-common/src` + `vendored/oasis`). `run_simulation.py` auto-bootstrap walker để tìm cả hai khi chạy độc lập.
- **Simulation .venv separate**: `run_simulation.py` chạy bằng `apps/simulation/.venv/Scripts/python.exe`, không phải venv của Core (`venv/` ở root). Nếu miss dependency, `cd vendored/oasis && poetry install` để rebuild venv.
- **FalkorDB 2 databases**: `ecosim` (campaign KG, dùng trong Core/Sim) vs `ecosim_agent_memory` (agent memory, chỉ khi `enable_graph_cognition=true`). Đừng nhầm.
- **Atomic writes**: file state trong `data/simulations/{sim_id}/` (profiles.json, progress.json, actions.jsonl, crisis_scenarios.json, report/*) dùng `ecosim_common.atomic_io.atomic_write_json`. Đừng dùng `json.dump(open(...))` trực tiếp — gây race condition với reader song song.
- **Long LLM chains**: `report_agent.py` và `profile_generator.py` dùng batch calls. Rate-limit → tăng `max_retries` ở `LLMClient`.
- **OASIS SQLite**: mỗi sim có DB riêng ở `data/simulations/{sim_id}/oasis_simulation.db`. Đừng share giữa sims.
- **Parquet 20M rows**: DuckDB query phải có `LIMIT` hoặc filter — scan full là OOM.
- **ChromaDB in-process**: Collection tồn tại trong subprocess `run_simulation.py`. Sim crash → phải re-index từ SQLite.
- **Group isolation**: khi `/api/graph/ingest` thêm tài liệu, luôn pass `group_id=campaign_id` để không lẫn entity giữa campaigns.
- **Docker build context = repo root** cho simulation (cần copy cả `vendored/oasis` và `apps/simulation`). Xem `apps/simulation/Dockerfile` + `docker-compose.yml`.

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
| Report ReACT + Interview + Survey + Analysis | [docs/06_post_simulation.md](docs/06_post_simulation.md) |
| Endpoints + env vars + schemas | [docs/reference.md](docs/reference.md) |

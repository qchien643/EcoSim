# 01 — Tổng quan EcoSim

> Định vị: nền tảng **mô phỏng động lực mạng xã hội** trong phản ứng với các sự kiện xã hội (chiến dịch marketing, khủng hoảng truyền thông, chính sách công). Đầu vào là 1 tài liệu campaign brief; đầu ra là báo cáo phân tích định tính + định lượng dựa trên hành vi của agents mô phỏng.

## 1. Pipeline 5 bước

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ 1. Upload    │     │ 2. Build KG  │     │ 3. Prepare   │
│ document     │ ──▶ │ entities +   │ ──▶ │ profiles +   │
│ → spec       │     │ edges        │     │ sim config   │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                          ┌───────────────────────┘
                          ▼
                  ┌───────────────┐     ┌───────────────┐
                  │ 4. Run        │     │ 5. Analyze    │
                  │ round loop    │ ──▶ │ sentiment +   │
                  │ (subprocess)  │     │ survey +      │
                  │               │     │ report (ReACT)│
                  └───────────────┘     └───────────────┘
```

| Bước | Trigger | Service | Output chính |
|------|---------|---------|---------------|
| 1. Upload | `POST /api/campaign/upload` | Core | `data/campaigns/<cid>/extracted/spec.json` (CampaignSpec) |
| 2. Build KG | `POST /api/graph/build` | Sim | FalkorDB graph `<cid>` + `data/campaigns/<cid>/kg/snapshot.json` |
| 3. Prepare | `POST /api/sim/prepare` | Sim | `profiles.json`, `config.json`, `crisis_scenarios.json` ở `data/campaigns/<cid>/sims/<sid>/` |
| 4. Run | `POST /api/sim/start` (SSE `…/stream`) | Sim subprocess | `actions.jsonl`, `oasis_simulation.db`, `simulation.log` + KG delta |
| 5. Analyze | 4 flow độc lập | Sim + Core | `analysis_results.json` (sentiment), `<survey_id>.json`, `report/full_report.md` |

Pipeline **không bắt buộc tuần tự cứng** — sau khi sim ở `COMPLETED`, 4 flow Phase 5 (sentiment, survey, interview, report) chạy độc lập, có thể parallel hoặc tuỳ chọn.

## 2. Khác biệt so với OASIS gốc

EcoSim build trên upstream **camel-oasis** (`vendored/oasis/`) nhưng có nhiều extension. Bảng so sánh:

| Khía cạnh | OASIS upstream | EcoSim |
|-----------|----------------|--------|
| Agent action decision | LLM call mỗi vòng | **Rule-based** (`posts_per_week × MBTI × period_multiplier`) — giảm 90% LLM cost |
| Feed recommendation | Random / collaborative filtering | **Semantic matching** qua ChromaDB embeddings (`PostIndexer`) |
| Interest model | Static từ profile | **Adaptive KeyBERT drift** — boost engaged interests + decay unused + curiosity injection |
| Cross-round memory | Không | **FIFO 5-round buffer** + LLM-summarized injection + reflection cycle |
| Knowledge Graph | Không | **FalkorDB master KG** + per-sim fork (Phase 10 KG cache state machine) |
| Crisis scenarios | Không | **LLM-generated 7 types**, perturbation theo Jaccard relevance |
| Sentiment / Report | Không | **RoBERTa local** + **ReACT report agent** 4 tools |
| Action persistence | SQLite chỉ runtime | **Hybrid**: SQLite + JSONL append + Zep extract → FalkorDB delta (Phase 15) |

## 3. Tech stack

| Layer | Lựa chọn | Lý do |
|-------|----------|-------|
| LLM provider | OpenAI-compatible (`openai` SDK + base_url tuỳ biến) | Đổi provider chỉ qua `.env` (OpenAI / Groq / Together / Ollama / OpenRouter) |
| Model tier | 3 lớp: `LLM_MODEL_NAME` (main), `LLM_EXTRACTION_MODEL` (gpt-4o cho KG extract), `LLM_FAST_MODEL_NAME` (in-character replies) | Cân bằng cost vs precision |
| Profile pool | Parquet 20M rows (`data/samples/dataGenerator/`) scan qua **DuckDB** | Không load full vào memory |
| Knowledge Graph | **FalkorDB** (Redis fork) + Graphiti (cho hybrid search) | Cypher trực tiếp + vector embedding tùy chọn |
| Vector DB | **ChromaDB** in-process, per-sim collection (`ecosim_{sim_id}`) | Embedding qua OpenAI API (centralized LLMClient) |
| Sentiment | **RoBERTa** local (`cardiffnlp/twitter-roberta-base-sentiment`) | Không phụ thuộc LLM API; chạy offline |
| Document parsing | PyMuPDF + LangChain text splitters | PDF + Markdown + plaintext |
| Sim runtime | OASIS (camel-ai) subprocess | Cô lập venv riêng (Python 3.11) |
| Frontend | **Next.js 16 (App Router)** + React 19 + TypeScript strict + Tailwind 3 + Zustand + @tanstack/react-query v5 | SSR + same-origin proxy + persist localStorage |
| Gateway | **Caddy 2** (`apps/gateway/Caddyfile`) | SSE flush_interval=-1, 1800s timeout cho long LLM chains, CORS allow dev :5173 |

## 4. Microservice layout (5 service)

| Service | Framework | Port | Vai trò chính |
|---------|-----------|------|---------------|
| **Gateway** | Caddy 2 | 5000 | Reverse proxy + CORS + SSE forwarding |
| **Core** | Flask 3 | 5001 | Campaign upload + Report generation + Dashboard analytics |
| **Simulation** | FastAPI + uvicorn | 5002 | Graph build, Sim CRUD/prepare/start/stream, Survey, Interview, Analysis |
| **FalkorDB** | Redis fork (Docker) | 6379 | Graph DB — 2 databases: `<cid>` (master + per-sim fork) + `ecosim_agent_memory` (optional) |
| **Frontend** | Next.js 16 dev/standalone | 5173 | UI campaign-centric |

Core và Simulation chạy **2 Python venv riêng** với 2 phiên bản Python khác nhau:
- Core ở `apps/core/.venv/` — Python 3.14 (`requires-python>=3.10`)
- Sim ở `apps/simulation/.venv/` — Python 3.11 (`requires-python>=3.10,<3.13` do vendored/oasis)

Bootstrap qua `uv sync` per service (không cần Poetry CLI — `poetry-core` chỉ là build backend PEP 517 mà uv xử lý được).

Chi tiết kiến trúc: [02_architecture.md](02_architecture.md).

## 5. Storage layers

Data được phân bổ qua **5 backend** khác nhau, mỗi cái cho 1 mục đích:

| Backend | Đường dẫn / Endpoint | Nội dung | Vai trò |
|---------|---------------------|----------|---------|
| Filesystem (per-campaign) | `data/campaigns/<cid>/` | source, extracted, kg, sims | Source-of-truth structured data |
| Filesystem (per-sim) | `data/campaigns/<cid>/sims/<sid>/` | profiles.json, oasis_simulation.db, actions.jsonl, analysis_results.json, report/ | Sim runtime artifacts |
| SQLite Meta DB | `data/meta.db` | campaigns + simulations + simulation_agents + sentiment_summaries | **Index/lookup authoritative** — Phase 5 dùng meta.db để resolve sim_dir |
| FalkorDB | Container `ecosim-falkordb:6379` | 3 graphs: `<cid>` (master), `sim_<sid>` (per-sim), `ecosim_agent_memory` (optional) | Cypher queries + vector index |
| ChromaDB | `data/campaigns/<cid>/sims/<sid>/chroma/` | Collection `ecosim_{sim_id}` (post embeddings) | Semantic feed matching per-sim |
| Zep Cloud (optional) | `https://api.getzep.com/` | Master KG graph (campaign_id) + sim_<sid> runtime graph | LLM-driven extraction pipeline |

Chi tiết: [07_storage_and_paths.md](07_storage_and_paths.md).

## 6. Trạng thái tính năng

| Tính năng | Trạng thái | Ghi chú |
|-----------|------------|---------|
| Pipeline 1-5 | ✓ Hoạt động | End-to-end với gpt-4o-mini main + gpt-4o extraction |
| KeyBERT interest drift | ✓ Verified | `_extract_keyphrases` dùng MMR + diversity 0.5; verify ở log: "Interest vectors: N total interests tracked" |
| FIFO memory + reflection | ✓ Hoạt động | Per-round buffer max 5, reflection cycle (interval theo config) |
| Crisis injection | ✓ Hoạt động | 7 types, schedule + real-time; perturbation Jaccard relevance |
| Phase 15 Zep section dispatch | ✓ Hoạt động (khi `ZEP_API_KEY` set) | 10-node pipeline; structural actions vào SQLite, content actions vào KG |
| KG build (direct Cypher) | ✓ Hoạt động | `kg_direct_writer.write_kg_direct()` bypass Graphiti — giảm 60+ phút LLM duplicate |
| Sentiment analysis | ✓ Hoạt động | RoBERTa local + NSS score |
| Survey auto-generate | ✓ Hoạt động | `SurveyQuestionGenerator` tag `report_section` |
| Interview chat | ✓ Hoạt động | Fast model (`LLM_FAST_MODEL_NAME`) cho per-agent reply |
| Report ReACT | ✓ Hoạt động | 2-phase (outline + per-section), 4 tools, evidence store |
| **Graph cognition** | ⛔ **Disabled** | `agent_cognition.py:GraphCognitiveHelper._DISABLED=True` — import `graphiti_core.driver.falkordb_driver` không tồn tại trên PyPI (14 versions probed). Refactor sang direct Cypher pending |

## 7. Đọc tiếp

| Để hiểu | File |
|---------|------|
| Cài đặt + chạy | [../README.md](../README.md) |
| Kiến trúc microservice chi tiết | [02_architecture.md](02_architecture.md) |
| Upload → KG pipeline (Stage 1-3) | [03_ingestion_kg.md](03_ingestion_kg.md) |
| Agent generation (Tier B) | [04_agent_generation.md](04_agent_generation.md) |
| Round loop + cognition + Phase 15 | [05_simulation_loop.md](05_simulation_loop.md) |
| Post-sim flows hub | [06_post_simulation.md](06_post_simulation.md) |
| Sentiment, Survey, Interview, Report | [06a-06d](06a_sentiment_analysis.md) |
| Storage + Paths + Meta DB | [07_storage_and_paths.md](07_storage_and_paths.md) |
| API endpoints + env vars + schemas | [reference.md](reference.md) |
| Claude Code agent guidance | [../CLAUDE.md](../CLAUDE.md) |

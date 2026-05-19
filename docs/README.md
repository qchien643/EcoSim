# Docs — EcoSim

Tài liệu kỹ thuật cho **EcoSim**, nền tảng mô phỏng động lực học mạng xã hội trong phản ứng với các sự kiện xã hội (chiến dịch marketing, khủng hoảng, chính sách).

## Thứ tự đọc đề xuất

| # | File | Mô tả |
|---|------|-------|
| 1 | [01_overview.md](01_overview.md) | Tổng quan pipeline 5 bước + khác biệt OASIS + tech stack + storage layers + trạng thái feature |
| 2 | [02_architecture.md](02_architecture.md) | Kiến trúc microservice (Gateway / Core / Simulation / FalkorDB / Frontend) + share state + uv venvs |
| 3 | [03_ingestion_kg.md](03_ingestion_kg.md) | **Stage 1-3**: Upload → chunking → LLM extract entities/facts → KG (3 variants: direct Cypher / Zep hybrid / Graphiti legacy) |
| 4 | [04_agent_generation.md](04_agent_generation.md) | **Stage Prepare**: Sinh profiles từ parquet 20M → LLM enrich + MBTI balance → sim config + crisis scenarios |
| 5 | [05_simulation_loop.md](05_simulation_loop.md) | **Stage 4**: Round loop runtime — 9 phases, cognition (KeyBERT drift + FIFO memory + reflection), Phase 15 Zep section dispatch |
| 6 | [06_post_simulation.md](06_post_simulation.md) | **Stage 5 hub**: workflow Sentiment → Survey → Report + Interview |
| 6a | [06a_sentiment_analysis.md](06a_sentiment_analysis.md) | Sentiment Analysis pipeline (RoBERTa local + NSS + campaign score) + frontend adapter |
| 6b | [06b_survey.md](06b_survey.md) | Survey + auto-generate questions (SurveyQuestionGenerator) |
| 6c | [06c_interview.md](06c_interview.md) | Interview — chat với từng agent (persona_evolved aware) |
| 6d | [06d_report.md](06d_report.md) | Report ReACT — 2-phase (outline + per-section), 4 tools, evidence store |
| 7 | [07_storage_and_paths.md](07_storage_and_paths.md) | Storage layout Phase 5 + Meta DB schema + path resolver + FalkorDB graphs + ChromaDB + Zep |
| ★ | [reference.md](reference.md) | API endpoints, `.env` vars, file layout, database schemas |

## Cho người mới

- Cài đặt + chạy lần đầu: [../README.md](../README.md)
- Làm việc cùng Claude Code agent trên repo này: [../CLAUDE.md](../CLAUDE.md)

## Trạng thái feature đáng chú ý

| Feature | Status |
|---------|--------|
| Pipeline 1-5 | ✓ Hoạt động end-to-end |
| KeyBERT interest drift | ✓ Verified runtime |
| FIFO memory + reflection | ✓ Hoạt động |
| Phase 15 Zep section dispatch | ✓ Hoạt động (cần `ZEP_API_KEY`) |
| KG direct Cypher build | ✓ Hoạt động (bypass Graphiti) |
| Sentiment / Survey / Interview / Report | ✓ Hoạt động |
| **Graph cognition** | ⛔ Disabled — `GraphCognitiveHelper._DISABLED=True` ([05_simulation_loop.md](05_simulation_loop.md#graph-cognition--current-state)) |
| **Graphiti hybrid search** | ⛔ Broken — module `graphiti_core.driver.falkordb_driver` không tồn tại trên PyPI. Read-side degrade về raw Cypher pattern matching |

## Quy ước tài liệu

- **Sơ đồ** dùng [Mermaid](https://mermaid.js.org/) — render được trên GitHub, VS Code, MkDocs.
- **Cite code** theo định dạng `path/to/file.py:42` để nhảy trực tiếp.
- **Ngôn ngữ**: tài liệu tiếng Việt; identifier/endpoint tiếng Anh.
- Khi phát hiện tài liệu lệch với code, **sửa code path trước**, rồi cập nhật tài liệu — không viết tài liệu cho hành vi không tồn tại.
- **Storage paths**: Phase 5 layout = `data/campaigns/<cid>/sims/<sid>/`. Mọi sim path phải resolve qua meta.db (`resolve_simulation_paths` helper), KHÔNG hardcode `Config.SIM_DIR/<sid>/`.

## Graphify

Repo có knowledge graph được generate qua `/graphify` skill — output ở [../graphify-out/](../graphify-out/):

- `graph.html` — interactive viz (open in browser)
- `GRAPH_REPORT.md` — markdown audit với 189 communities, top god nodes (`Platform`, `LLMClient`, `ReportAgent`, `apiFetch`, `useUiStore`, ...), surprising connections
- `graph.json` — raw GraphRAG-ready data

Dùng để onboarding new developers + verify code structure khớp docs.

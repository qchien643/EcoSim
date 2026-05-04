# Docs — EcoSim

Tài liệu kỹ thuật cho **EcoSim**, nền tảng mô phỏng động lực học mạng xã hội trong phản ứng với các sự kiện xã hội.

## Thứ tự đọc đề xuất

| # | File | Mô tả |
|---|------|-------|
| 1 | [01_overview.md](01_overview.md) | Tổng quan pipeline 5 bước + điểm khác biệt so với OASIS |
| 2 | [02_architecture.md](02_architecture.md) | Kiến trúc microservice (Gateway / Core / Simulation / FalkorDB / Frontend) |
| 3 | [03_ingestion_kg.md](03_ingestion_kg.md) | **Stage 1-2**: Upload tài liệu → chunking → ontology động → Knowledge Graph |
| 4 | [04_agent_generation.md](04_agent_generation.md) | **Stage 3**: Sinh persona từ parquet 20M → LLM enrich + MBTI → sim config |
| 5 | [05_simulation_loop.md](05_simulation_loop.md) | **Stage 4**: Vòng mô phỏng — conditional posting, semantic matching, KeyBERT drift, memory, crisis |
| 6 | [06_post_simulation.md](06_post_simulation.md) | **Stage 5 hub**: workflow Sentiment → Survey → Report + Interview |
| 6a | [06a_sentiment_analysis.md](06a_sentiment_analysis.md) | Sentiment Analysis pipeline (RoBERTa local + NSS + campaign score) |
| 6b | [06b_survey.md](06b_survey.md) | Survey + auto-generate questions (SurveyQuestionGenerator) |
| 6c | [06c_interview.md](06c_interview.md) | Interview — chat với từng agent (persona_evolved aware) |
| 6d | [06d_report.md](06d_report.md) | Report ReACT — consume sentiment + survey + KG, citation anchors |
| 7 | [reference.md](reference.md) | API endpoints, `.env`, file layout, database schemas |

## Cho người mới

- Cài đặt + chạy lần đầu: [../README.md](../README.md)
- Làm việc cùng Claude Code agent trên repo này: [../CLAUDE.md](../CLAUDE.md)

## Quy ước tài liệu

- **Sơ đồ** dùng [Mermaid](https://mermaid.js.org/) — render được trên GitHub, VS Code, MkDocs.
- **Cite code** theo định dạng `path/to/file.py:42` để nhảy trực tiếp.
- **Ngôn ngữ**: tài liệu tiếng Việt; identifier/endpoint tiếng Anh.
- Khi phát hiện tài liệu lệch với code, **sửa code path trước**, rồi cập nhật tài liệu — không viết tài liệu cho hành vi không tồn tại.

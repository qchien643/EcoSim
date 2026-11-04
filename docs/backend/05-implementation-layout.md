# Backend implementation layout

Đây là cấu trúc code đang được dùng cho thiết kế backend mới. Đường chạy
production không dùng database riêng cho từng run và không gọi engine cũ.

```text
ecoSim/
├── backend/
│   ├── store.py                 # SQLite schema, repositories, atomic writes
│   ├── runtime.py               # lifecycle của một run
│   ├── persistence/writer.py    # single-writer connection cho workers
│   └── api/
│       ├── app.py               # HTTP boundary, validation, background dispatch
│       ├── views.py             # public read models, history, report, cursor
│       ├── stream.py            # shared polling/SSE projection
│       └── self_check.py        # HTTP contracts on temporary file-backed SQLite
├── gateways/
│   ├── jev.py                   # JEV/OpenRouter transport + parser
│   ├── openai.py                # structured-output fallback
│   ├── http.py                  # HTTP stdlib transport
│   └── types.py                 # shared GatewayResponse
└── simulation/
    ├── context/                 # context tối thiểu và renderer
    ├── decision/                # policy, output validation, stage call
    ├── execution/               # session barrier, sequential/parallel
    ├── metrics/                 # projector và report reader
    ├── personas/                # MatrAIx, industry, relationship
    ├── setup/                   # scenario loader/materializer/validator
    └── legacy/                  # mã cũ, không được import bởi runtime mới
```

## Luồng ghi dữ liệu

Mỗi stage lấy context đã lưu, gọi gateway ngoài transaction, sau đó commit
`model_call → stage_event → event_tags → agent_stage_state → relationship →
checkpoint → run_update` trong một transaction. Worker không tự ghi SQLite:
`RunWriter` nhận các lệnh ghi theo thứ tự.

`agent_sessions` là cờ hoàn thành thực sự của agent trong từng phiên; không
được suy ra từ số event. Một phiên chỉ công bố metric sau khi toàn bộ agent
active hoàn tất. SSE và polling chỉ đọc `run_updates` đã commit.

## Quy tắc phụ thuộc

- `gateways` không biết SQLite, policy hay bước tiếp theo.
- `simulation/context` không gọi model.
- `simulation/decision` không tự điều phối phiên.
- `simulation/metrics` chỉ đọc event đã commit, không gọi JEV/LLM.
- `backend/api` gọi runtime và read services, không chứa logic mô phỏng.
- `simulation/legacy` chỉ giữ mã tham khảo; không thêm import ngược vào code mới.

## Kiểm tra tối thiểu

```bash
cd ecoSim
.venv/bin/python -m backend.api.self_check
.venv/bin/python -m backend.self_check
.venv/bin/python -m simulation.execution.regression_check
.venv/bin/python -m gateways.openai
```

Các kiểm tra chuyên biệt khác có thể chạy từ root:

```bash
PYTHONPATH=ecoSim python3 -m simulation.execution.self_check
PYTHONPATH=ecoSim python3 -m simulation.execution.regression_check
PYTHONPATH=ecoSim python3 -m gateways.jev
PYTHONPATH=ecoSim python3 -m paper_research.validate_context_rendering_v2
```

Các lệnh trên không gọi API trả phí. Live gateway chỉ chạy khi người dùng
chủ động yêu cầu và cấu hình secret trong `.env`.

# Model Gateway và cấu hình router

## Phạm vi

`simulation/model_gateway.py` là lớp giao tiếp HTTP giữa runtime và model.
Nó hỗ trợ:

- JEV qua Decisions API;
- LLM fallback qua OpenAI-compatible Chat Completions;
- một endpoint 9Router OpenAI-compatible; upstream providers/models do 9Router
  quản lý;
- fallback trực tiếp qua OpenAI Chat Completions với Pydantic Structured
  Outputs;
- pool nhiều endpoint độc lập như một phương án fallback mở rộng.

Gateway chỉ trả kết quả thô đã ánh xạ về contract nội bộ. Threshold, chọn tag,
`attend/skip` và nhánh mô phỏng vẫn do `policy.py` và `orchestrator.py` xử lý.

## Direct OpenAI fallback

MVP dùng OpenAI trực tiếp cho fallback khi cần structured output đáng tin cậy:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-nano
```

```python
from simulation.model_gateway import build_jev_gateway
from simulation.openai_gateway import build_openai_gateway

stages = StageService(store, build_jev_gateway(), build_openai_gateway())
```

`simulation.openai_gateway` tạo một Pydantic model riêng cho từng stage.
Descriptions của field lấy từ question contract và tag registry; Pydantic
được dùng làm `response_format`, rồi output được ánh xạ về cùng dạng với JEV:
`probabilities`, `distributions` hoặc `answer`. Pydantic không quyết định
threshold, tag floor hay action; đó vẫn là trách nhiệm của policy deterministic.

## Cấu hình router

Không lưu API key trong JSON. Có thể dùng file cấu hình:

```json
{
  "routers": [
    {
      "name": "router_1",
      "endpoint": "https://provider.example/v1",
      "model": "provider/model",
      "protocol": "chat_completions",
      "api_key_env": "ROUTER_1_API_KEY",
      "timeout": 45
    }
  ]
}
```

Hoặc dùng biến môi trường theo vị trí:

```text
PROJECTDUT_ROUTER_1_NAME
PROJECTDUT_ROUTER_1_ENDPOINT
PROJECTDUT_ROUTER_1_MODEL
PROJECTDUT_ROUTER_1_PROTOCOL
PROJECTDUT_ROUTER_1_API_KEY_ENV
```

Loader đọc từ `PROJECTDUT_ROUTER_1_*` đến `PROJECTDUT_ROUTER_9_*` nếu ứng dụng
có nhiều endpoint độc lập. Đây không phải cách cấu hình nội bộ của 9Router.
`protocol` nhận `chat_completions` hoặc `decisions`. Router được thử theo thứ
tự cấu hình; khi một router trả kết quả thành công, pool dừng tại router đó.

Với 9Router, ứng dụng chỉ cần một cấu hình:

```text
PROJECTDUT_9ROUTER_ENDPOINT
PROJECTDUT_9ROUTER_MODEL
PROJECTDUT_9ROUTER_API_KEY_ENV
```

Sau đó:

```python
from simulation.model_gateway import build_9router_gateway

llm = build_9router_gateway()
```

Endpoint có thể là base OpenAI-compatible URL hoặc đã bao gồm
`/chat/completions`; gateway tự bổ sung path trong trường hợp base URL.

JEV mặc định được dựng từ key trong `.env`:

```text
endpoint: https://openrouter.ai/api/alpha/decisions
model: typesafe/jev-1.13
protocol: decisions
```

`.env` có thể là một dòng OpenRouter key thô hoặc dạng
`OPENROUTER_API_KEY=...`. Key không được ghi vào request log hoặc cấu hình
JSON.

## Sử dụng

```python
from simulation.model_gateway import build_jev_gateway, build_llm_gateway

jev = build_jev_gateway()
fallback = build_llm_gateway("data/contracts/model-router.config.json")
```

Hiện repository chỉ có key OpenRouter và thông tin JEV mặc định. Endpoint,
model và key của 9Router chưa xuất hiện trong workspace, nên chưa điền giả vào
cấu hình. Khi cung cấp các biến `PROJECTDUT_9ROUTER_*`, dùng
`build_9router_gateway` mà không phải sửa orchestrator.

## Kiểm tra offline

```bash
python3 -m simulation.model_gateway
```

Lệnh này kiểm tra question contract, JEV response parser và structured-output
schema mà không gọi mạng.

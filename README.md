# EcoSim — Hướng dẫn khởi động

> Làm việc với Claude Code agent trên repo này? Đọc [CLAUDE.md](CLAUDE.md) trước.

## Yêu cầu hệ thống

| Thành phần | Phiên bản |
|-----------|-----------|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| Docker | ≥ 24 (cho FalkorDB) |
| Caddy | 2.x (cho API Gateway, tuỳ chọn — có fallback) |

## Cấu trúc dự án

```
EcoSim/
├── .env                       ← Cấu hình môi trường (tạo thủ công)
├── docker-compose.yml         ← 5-service stack
├── scripts/                   ← start.ps1 / stop.ps1 / restart.ps1
├── apps/
│   ├── core/                  ← Flask :5001 (Campaign + Report)
│   ├── simulation/            ← FastAPI :5002 (Graph, Sim, Survey, Interview, Analysis)
│   ├── gateway/               ← Caddy :5000 (reverse proxy)
│   └── frontend/              ← Vue 3 + Vite :5173
├── libs/
│   └── ecosim-common/         ← Shared Python library (config, llm_client, file_parser, atomic_io)
├── vendored/
│   └── oasis/                 ← Upstream camel-oasis (don't touch)
└── data/                      ← Runtime (gitignored)
```

---

## Bước 1: Khởi động FalkorDB (Knowledge Graph)

```bash
cd EcoSim
docker compose up -d falkordb
```

Kiểm tra: mở http://localhost:3000 (FalkorDB Browser UI)

---

## Bước 2: Tạo file `.env`

Tạo file `EcoSim/.env` với nội dung:

```env
# LLM (OpenAI-compatible)
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# FalkorDB
FALKORDB_HOST=localhost
FALKORDB_PORT=6379

# Ports
CORE_SERVICE_PORT=5001
SIM_SERVICE_PORT=5002
GATEWAY_PORT=5000
```

> [!NOTE]
> `LLM_BASE_URL` hỗ trợ mọi endpoint OpenAI-compatible: OpenAI, Groq, Together AI, OpenRouter, Ollama...

---

## Bước 3: Cài đặt dependencies (lần đầu)

**Core Service (Flask):**

```bash
cd EcoSim
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate            # Linux/macOS
pip install -r apps/core/requirements.txt
```

**Simulation Service (FastAPI + camel-oasis):**

```bash
cd vendored/oasis
poetry install                        # Tạo .venv ở apps/simulation/.venv/
```

> Venv của Simulation nằm riêng (`apps/simulation/.venv/`) để không conflict với Core venv.

**Frontend:**

```bash
cd apps/frontend
npm install
```

---

## Bước 4: Khởi động (all-in-one)

**Windows:**

```powershell
.\scripts\start.ps1
```

Script này khởi chạy 5 terminal: FalkorDB, Core :5001, Simulation :5002, Gateway :5000, Frontend :5173.

**Docker all-in-one:**

```bash
docker compose up -d
```

---

## Khởi động thủ công (dev một service)

```bash
# Core Service
cd apps/core && python run.py

# Simulation Service
cd apps/simulation && .venv/Scripts/python -m uvicorn sim_service:app --port 5002

# Gateway (Caddy)
caddy run --config apps/gateway/Caddyfile

# Frontend
cd apps/frontend && npm run dev
```

---

## API Endpoints chính (qua Gateway :5000)

| Endpoint | Method | Service | Mô tả |
|----------|--------|---------|-------|
| `/api/health` | GET | — | Aggregate health |
| `/api/campaign/upload` | POST | Core | Upload campaign file |
| `/api/campaign/list` | GET | Core | List campaigns |
| `/api/graph/build` | POST | Sim | Build KG |
| `/api/graph/entities` | GET | Sim | KG entities |
| `/api/sim/prepare` | POST | Sim | Prepare sim (profiles + config + crisis) |
| `/api/sim/start` | POST | Sim | Start sim subprocess |
| `/api/sim/{id}/stream` | GET (SSE) | Sim | Live progress |
| `/api/report/generate` | POST | Core | ReACT report |
| `/api/survey/*` | POST | Sim | Bulk survey |
| `/api/interview/*` | POST | Sim | Per-agent chat |

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Giải pháp |
|-----|-------------|-----------|
| `ConnectionError: FalkorDB` | Docker chưa chạy | `docker compose up -d falkordb` |
| `AuthenticationError: OpenAI` | API key sai/hết hạn | Kiểm tra `LLM_API_KEY` trong `.env` |
| `ModuleNotFoundError: ecosim_common` | Chưa bootstrap libs | Chạy qua entry point (`run.py` hoặc `sim_service.py`), không import trực tiếp |
| `ModuleNotFoundError: oasis` | Missing vendored bootstrap | Chạy `run_simulation.py` qua subprocess của Sim Service, không standalone |
| Port 5000/5001/5002/5173 bị chiếm | App khác | Đổi port trong `.env` hoặc kill process |
| Caddy không có | Windows chưa cài | `scripts/start.ps1` tự fallback sang `apps/gateway/gateway.py.bak` (Flask proxy) |

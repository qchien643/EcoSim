# EcoSim — Hướng dẫn chạy dự án

> Đang làm việc với Claude Code agent? Đọc [CLAUDE.md](CLAUDE.md) trước.

## TL;DR — Lần đầu

```powershell
# 1. Cài uv (nếu chưa có)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Tạo file .env (xem mẫu bên dưới)
notepad .env

# 3. Cài deps cho 3 service
cd apps/core         && uv sync                  ; cd ../..
cd apps/simulation   && uv sync --python 3.11   ; cd ../..
cd apps/frontend     && npm install              ; cd ../..

# 4. Bật Docker Desktop, rồi chạy all-in-one
.\scripts\start.ps1
```

Mở [http://localhost:5173](http://localhost:5173) — UI Next.js sẽ gọi qua gateway `:5000` → Core `:5001` + Simulation `:5002` + FalkorDB `:6379`.

---

## Yêu cầu hệ thống

| Thành phần | Phiên bản | Ghi chú |
|------------|-----------|---------|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Quản lý 2 Python venv + lock |
| Python (Core) | ≥ 3.10 | uv pick highest (3.14 OK) |
| Python (Simulation) | ≥ 3.10, < 3.13 | Bị giới hạn bởi `vendored/oasis/pyproject.toml`. Khuyến nghị 3.11 |
| Node.js | ≥ 18 | Cho Next.js frontend |
| Docker Desktop | ≥ 24 | Bắt buộc — FalkorDB chạy trong container |
| Caddy 2 | tuỳ chọn | API Gateway. Có fallback sang `gateway.py.bak` nếu không cài |

uv tự cài Python nếu thiếu: `uv python install 3.11`.

---

## Cấu trúc dự án

```
EcoSim/
├── .env                       ← Cấu hình môi trường (tạo thủ công, xem §Tạo .env)
├── docker-compose.yml         ← 5-service stack (Docker mode)
├── scripts/                   ← start.ps1 / stop.ps1 / restart.ps1 (Windows)
├── apps/
│   ├── core/                  ← Flask :5001 — Campaign + Report
│   │   ├── pyproject.toml + uv.lock     ← uv project (Python ≥3.10)
│   │   └── .venv/                       ← uv-managed venv
│   ├── simulation/            ← FastAPI :5002 — Graph, Sim, Survey, Interview, Analysis
│   │   ├── pyproject.toml + uv.lock     ← uv project (Python 3.10–3.12)
│   │   └── .venv/                       ← uv-managed venv
│   ├── gateway/               ← Caddy :5000 — Reverse proxy
│   └── frontend/              ← Next.js 16 :5173 — App Router + TS + Tailwind 3
├── libs/
│   └── ecosim-common/         ← Shared Python lib (config, LLM client, parsing, atomic I/O)
├── vendored/
│   └── oasis/                 ← Upstream camel-oasis — KHÔNG patch
└── data/                      ← Runtime (gitignored — uploads, sim outputs, FalkorDB volume)
```

---

## Setup chi tiết

### 1. Cài uv

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Kiểm tra: `uv --version` (≥ 0.5).

### 2. Tạo file `.env`

Ở root `EcoSim/.env`:

```env
# LLM (OpenAI-compatible — OpenAI, Groq, Together, OpenRouter, Ollama, ...)
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# Optional: stronger model cho KG extraction (Stage 1 + Stage 3)
# LLM_EXTRACTION_MODEL=gpt-4o

# FalkorDB
FALKORDB_HOST=localhost
FALKORDB_PORT=6379

# Ports
CORE_SERVICE_PORT=5001
SIM_SERVICE_PORT=5002
GATEWAY_PORT=5000
```

### 3. Cài Python deps

**Core Service** (Python ≥3.10, uv pick highest có sẵn — thường là 3.14):

```bash
cd apps/core
uv sync
```

Sinh `.venv/` + `uv.lock`. `libs/ecosim-common` được pull tự động (editable path dep).

**Simulation Service** (Python 3.10–3.12 — pin `--python 3.11` vì vendored/oasis chưa hỗ trợ 3.13+):

```bash
cd apps/simulation
uv sync --python 3.11
```

Sinh `.venv/` riêng + `uv.lock`. Kéo cả camel-oasis (editable từ `vendored/oasis/`), keybert, sentence-transformers, torch, transformers — lần đầu mất 5–10 phút và ~5 GB.

> **Vì sao 2 venv riêng?** Core có thể chạy trên Python mới nhất; Simulation bị pin <3.13 bởi upstream. Mỗi service có pyproject + lock + `.venv` độc lập, không kéo lẫn dependency.

### 4. Cài Node deps

```bash
cd apps/frontend
npm install
```

---

## Chạy dự án

### Cách A — All-in-one (Windows)

```powershell
.\scripts\start.ps1
```

Spawn 5 cửa sổ rời (xem trên taskbar — tiêu đề "EcoSim - …"):
1. FalkorDB (Docker `falkordb` container) — port 6379
2. Core Service — port 5001
3. Simulation Service — port 5002
4. Gateway (Caddy hoặc fallback Python) — port 5000
5. Frontend (Next.js dev server) — port 5173

Flag hữu ích:
- `.\scripts\start.ps1 -SkipDocker` — bỏ qua FalkorDB (nếu đang chạy sẵn)
- `.\scripts\start.ps1 -Only sim` — chỉ bật 1 service (`falkordb | core | sim | gateway | frontend`)

### Cách B — Docker all-in-one

```bash
docker compose up -d
```

5 container (5 service). Logs: `docker compose logs -f <service>`.

### Cách C — Manual per-service (dev)

```bash
# Terminal 1: FalkorDB
docker compose up -d falkordb

# Terminal 2: Core
cd apps/core && uv run python run.py

# Terminal 3: Simulation
cd apps/simulation && uv run uvicorn sim_service:app --port 5002 --reload

# Terminal 4: Gateway
caddy run --config apps/gateway/Caddyfile

# Terminal 5: Frontend
cd apps/frontend && npm run dev
```

`uv run` tự kích hoạt `.venv` đúng — không cần `activate`. Muốn shell có venv: `.\apps\core\.venv\Scripts\Activate.ps1` (Windows) hoặc `source apps/core/.venv/bin/activate` (Linux/macOS).

---

## Dừng / Khởi động lại

```powershell
.\scripts\stop.ps1                    # dừng tất cả (giữ Docker chạy)
.\scripts\stop.ps1 -KeepDocker        # dừng tất cả trừ Docker
.\scripts\restart.ps1                 # stop + start
docker compose down                   # nếu chạy bằng Cách B
```

---

## Verify

```bash
curl http://localhost:5000/api/health        # gateway → core+sim health
curl http://localhost:5001/api/health        # core direct
curl http://localhost:5002/api/health        # sim direct
```

UI: [http://localhost:5173](http://localhost:5173) (Next.js) — FalkorDB Browser: [http://localhost:3000](http://localhost:3000) (image FalkorDB ship sẵn UI).

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Giải pháp |
|-----|-------------|-----------|
| `Failed! Is Docker running?` lúc khởi động | Docker Desktop chưa lên | Mở Docker Desktop, chờ ~30s, thử lại |
| `ConnectionError: FalkorDB` runtime | FalkorDB container chưa chạy | `docker compose up -d falkordb` |
| `AuthenticationError: OpenAI` | API key sai / hết quota | Kiểm tra `LLM_API_KEY` trong `.env` |
| `ModuleNotFoundError: ecosim_common` / `oasis` | Venv chưa sync hoặc chạy sai entry point | `cd apps/<service> && uv sync`; chạy qua `run.py` / `sim_service.py`, đừng import standalone |
| `[COGNITION] KeyBERT not installed` | Sim venv thiếu keybert | `cd apps/simulation && uv sync` |
| Port 5000/5001/5002/5173 bị chiếm | App khác giữ port | Đổi port trong `.env` hoặc kill process |
| Caddy không có | Chưa cài Caddy | start.ps1 tự fallback sang `apps/gateway/gateway.py.bak` (Flask proxy) |
| `requires-python>=3.10,<3.13` lúc sync sim | Máy chưa có Python 3.11 | `uv python install 3.11` rồi sync lại |
| Turbopack crash khi xoá `.next/` lúc dev đang chạy | Cache corruption | Stop frontend → `Remove-Item -Recurse -Force apps/frontend/.next` → restart |

---

## Tiếp theo

- Pipeline + kiến trúc microservice: [docs/01_overview.md](docs/01_overview.md) → [docs/02_architecture.md](docs/02_architecture.md)
- API endpoints + env vars chi tiết: [docs/reference.md](docs/reference.md)
- Hướng dẫn cho Claude Code agent: [CLAUDE.md](CLAUDE.md)

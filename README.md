# EcoSim — Hướng dẫn khởi động

## Yêu cầu hệ thống

| Thành phần | Phiên bản |
|-----------|-----------|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| Docker | ≥ 24 (cho FalkorDB) |

## Cấu trúc dự án

```
EcoSim/
├── .env                    ← Cấu hình môi trường (tạo thủ công)
├── docker-compose.yml      ← FalkorDB
├── backend/
│   ├── run.py              ← Entry point Flask
│   ├── requirements.txt    ← Python dependencies
│   └── app/                ← Flask app
└── frontend/
    ├── package.json        ← Node dependencies
    └── src/                ← Vue 3 app
```

---

## Bước 1: Khởi động FalkorDB (Knowledge Graph)

```bash
cd EcoSim
docker compose up -d
```

Kiểm tra: mở http://localhost:3000 (FalkorDB Browser UI)

---

## Bước 2: Tạo file `.env`

Tạo file `EcoSim/.env` với nội dung:

```env
# Flask
FLASK_DEBUG=true
FLASK_PORT=5000

# LLM (OpenAI-compatible)
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# FalkorDB
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
```

> [!NOTE]
> `LLM_BASE_URL` hỗ trợ các dịch vụ OpenAI-compatible: OpenAI, Groq, Together AI, OpenRouter...

---

## Bước 3: Khởi động Backend

```bash
cd EcoSim

# Tạo virtual environment (lần đầu)
python -m venv venv

# Kích hoạt venv
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Windows CMD:
.\venv\Scripts\activate.bat
# Linux/macOS:
source venv/bin/activate

# Cài dependencies (lần đầu)
pip install -r backend/requirements.txt

# Chạy backend
cd backend
python run.py
```

**Output khi thành công:**
```
🚀 EcoSim starting on port 5000...
   LLM: gpt-4o-mini
   FalkorDB: localhost:6379
   Health: http://localhost:5000/api/health
```

Kiểm tra: `GET http://localhost:5000/api/health`

---

## Bước 4: Khởi động Frontend

Mở terminal mới:

```bash
cd EcoSim/frontend

# Cài dependencies (lần đầu)
npm install

# Chạy dev server
npm run dev
```

**Output khi thành công:**
```
VITE v6.3.0  ready in 500 ms
➜  Local:   http://localhost:5173/
```

Mở trình duyệt: http://localhost:5173

---

## Tóm tắt nhanh (sau lần đầu)

Sau khi đã cài đặt đầy đủ, mỗi lần chạy chỉ cần 3 terminal:

```bash
# Terminal 1: FalkorDB
docker compose up -d

# Terminal 2: Backend
cd EcoSim/backend
..\venv\Scripts\Activate.ps1
python run.py

# Terminal 3: Frontend
cd EcoSim/frontend
npm run dev
```

---

## API Endpoints chính

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/health` | GET | Health check |
| `/api/campaign/upload` | POST | Upload campaign file (.md) |
| `/api/campaign/list` | GET | Danh sách campaigns |
| `/api/graph/entities` | GET | KG entities |
| `/api/sim/prepare` | POST | Chuẩn bị mô phỏng (5-step MiroFish) |
| `/api/sim/start` | POST | Bắt đầu mô phỏng OASIS |
| `/api/sim/status?sim_id=` | GET | Trạng thái mô phỏng |

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Giải pháp |
|-----|-------------|-----------|
| `ConnectionError: FalkorDB` | Docker chưa chạy | `docker compose up -d` |
| `AuthenticationError: OpenAI` | API key sai/hết hạn | Kiểm tra `LLM_API_KEY` trong `.env` |
| `ModuleNotFoundError` | Chưa activate venv | `.\venv\Scripts\Activate.ps1` |
| Port 5000/5173 bị chiếm | Ứng dụng khác đang dùng port | Đổi `FLASK_PORT` hoặc kill process |

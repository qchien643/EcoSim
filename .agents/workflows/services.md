---
description: Start, stop, restart EcoSim services
---

# EcoSim Service Management

## Venvs
- **Core + Gateway**: `venv/Scripts/python.exe` (project root)
- **Simulation**: `oasis/.venv/Scripts/python.exe`

## Start All Services
// turbo
1. Run `.\start.ps1` from the project root

## Stop All Services
// turbo
2. Run `.\stop.ps1` from the project root

## Restart All Services
// turbo
3. Run `.\restart.ps1` from the project root

## Start a Single Service
// turbo
4. Run `.\start.ps1 -Only <service>` where service is one of: `falkordb`, `core`, `sim`, `gateway`, `frontend`

## Manual Commands (for reference)
```powershell
# FalkorDB
docker-compose up -d falkordb

# Core Service (port 5001)
.\venv\Scripts\python.exe backend\run.py

# Simulation Service (port 5002)  
cd oasis && .venv\Scripts\python.exe -m uvicorn sim_service:app --port 5002

# API Gateway (port 5000)
.\venv\Scripts\python.exe gateway\gateway.py

# Frontend (port 5173)
cd frontend && npm run dev
```

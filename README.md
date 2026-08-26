# Sim-AI

A self-hosted AI chat + coding assistant, powered by the Claude API, running entirely in Docker.

## Stack
- **backend** — FastAPI, proxies streaming responses from Claude, stores history in Postgres
- **frontend** — lightweight vanilla JS chat UI (no framework, easy to hack on)
- **db** — Postgres for conversation history

## Setup

1. Copy the env template and add your Anthropic API key:
   ```bash
   cp .env.example .env
   # edit .env and paste your ANTHROPIC_API_KEY
   ```

2. Build and start everything:
   ```bash
   docker compose up --build
   ```

3. Open the UI:
   - Frontend: http://localhost:3000
   - Backend health check: http://localhost:8000/api/health

## Project layout
```
sim/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── main.py          # FastAPI app: chat endpoint, streaming, history
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html        # chat UI
│   └── Dockerfile
└── db/                   # (Postgres data lives in a named Docker volume)
```

## Roadmap
- [x] Streaming chat with conversation history (Postgres-backed)
- [x] Dockerized, `docker compose up` and go
- [ ] Sandboxed code execution container so Sim can run/test code it writes
- [ ] File upload / RAG for local document context
- [ ] Auth (so it's safe to expose beyond localhost)
- [ ] Multi-model routing (fast model for simple queries, bigger model for hard ones)

## Pushing to a git repo

```bash
cd sim
git init
git add .
git commit -m "Initial commit: Sim MVP - streaming chat backend + UI + Postgres history"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

`.env` is gitignored — never commit your API key.

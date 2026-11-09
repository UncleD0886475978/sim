<div align="center">

# ✨ SimAI

### Your own AI chat + coding assistant — running 100% locally

**No cloud. No API key. No subscription.** SimAI runs Google's **Gemma 4** model on your own
computer with llama.cpp and Docker, keeps your chat history in Postgres, and even drafts
cover letters with **Maya**, its built-in resume-aware assistant.

![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Gemma 4](https://img.shields.io/badge/Model-Gemma%204%20E4B-4285F4?logo=google&logoColor=white)
![llama.cpp](https://img.shields.io/badge/Runtime-llama.cpp-orange)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![Postgres](https://img.shields.io/badge/History-Postgres-4169E1?logo=postgresql&logoColor=white)
![Privacy](https://img.shields.io/badge/Privacy-100%25%20Local-success)

</div>

---

## 🌟 What it does

| Feature | What you get |
|---|---|
| 💬 **Streaming chat** | Replies type out live, token by token, from your local model |
| 🧠 **Local Gemma 4** | Gemma 4 E4B via llama.cpp — sharp answers, zero cloud calls |
| 🗂️ **Chat history** | Conversations are saved in Postgres and survive restarts |
| ✍️ **Maya cover letters** | Paste a job posting, get a cover letter grounded in your real resume |
| 🎨 **Polished UI** | Clean dark interface, welcome screen with starter prompts, Maya in its own tab |
| 🔒 **Private by design** | Everything runs on your machine — your data never leaves it |

## 🏗️ How it fits together

```
┌────────────┐      ┌────────────┐      ┌──────────────────┐
│  Frontend  │ ───▶ │  Backend   │ ───▶ │  Model           │
│  Vanilla JS│      │  FastAPI   │      │  llama.cpp server│
│  :3000     │      │  :8000     │      │  Gemma 4 E4B     │
└────────────┘      └─────┬──────┘      └──────────────────┘
     browser              │                  local, offline
                          ▼
                    ┌────────────┐
                    │  Database  │
                    │  Postgres  │
                    │  history   │
                    └────────────┘
```

- **model** — [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` serving **Gemma 4 E4B** (GGUF, from Hugging Face: `ggml-org/gemma-4-E4B-it-GGUF`) through an OpenAI-compatible API
- **backend** — FastAPI, streams responses from the local model, stores history in Postgres
- **frontend** — lightweight vanilla JS chat UI (no framework, easy to hack on)
- **db** — Postgres for conversation history

## ✅ Requirements

- Docker with Compose
- **16 GB+ RAM** for the default Gemma 4 E4B **Q8_0** build (model file ≈ 8.59 GB, downloaded on first start)
- ~10 GB free disk for the model cache (kept in the `sim_model_cache` Docker volume)

## 🚀 Quick start

**1.** (Optional) Copy the env template — the defaults work without it, and **no API key is needed**:

```bash
cp .env.example .env
```

**2.** Build and start everything:

```bash
docker compose up --build
```

> ⏳ The first start downloads the Gemma 4 model (~8.6 GB for Q8_0) — this takes a while.
> Later starts reuse the downloaded model and work fully offline.

**3.** Open the UI:

- 🖥️ **Frontend:** http://localhost:3000
- ❤️ **Backend health check:** http://localhost:8000/api/health

## 🎛️ Changing the model size / quantization

Set `GEMMA_QUANT` in `.env` (or your shell) before `docker compose up`:

- `Q8_0` (default) — ≈ 8.59 GB, needs 16 GB+ RAM, best quality
- `Q4_0` — ≈ 5 GB, lighter and faster if RAM is tight

To use a different Gemma 4 size (e.g. E2B if your machine is short on RAM, or 12B if you have 24 GB+), change the `-hf` repository in the `model` service in `docker-compose.yml` (e.g. `ggml-org/gemma-4-E2B-it-GGUF:Q8_0`) and set `SIM_MODEL` to a matching name — the backend only talks to the model server's OpenAI-compatible API, so no code changes are needed.

## 📁 Project layout

```
sim/
├── docker-compose.yml      # db, model (llama-server + Gemma 4), backend, frontend
├── .env.example
├── backend/
│   ├── main.py             # FastAPI app: streaming chat endpoint, history, Maya cover letters
│   ├── requirements.txt
│   ├── data/resume.txt     # resume Maya references for cover letters
│   └── Dockerfile
├── frontend/
│   ├── index.html          # chat UI (consumes the streaming chat endpoint)
│   └── Dockerfile
└── db/                     # (Postgres data lives in a named Docker volume)
```

## 🗺️ Roadmap

- [x] Streaming chat with conversation history (Postgres-backed) — chat streams token-by-token from the local model
- [x] Dockerized, `docker compose up` and go
- [x] Local open model (Gemma 4 via llama.cpp) — no cloud API key
- [x] Polished UI — gradient dark theme, welcome screen, starter prompts
- [ ] Sandboxed code execution container so Sim can run/test code it writes
- [ ] File upload / RAG for local document context
- [ ] Auth (so it's safe to expose beyond localhost)
- [ ] Multi-model routing (fast model for simple queries, bigger model for hard ones)

---

<div align="center">

**Built to run at home, on your hardware, with your data staying yours.** 🏠

</div>

# sim (SimAI) — Build Notes

## One-line install (fresh Ubuntu/Debian VM)

```bash
curl -fsSL https://raw.githubusercontent.com/UncleD0886475978/sim/main/setup.sh | bash
```

The script installs its own prerequisites (git, curl, and Docker Engine + Compose via the official get.docker.com installer), clones the repo, creates `.env` from `.env.example` if missing, then builds and starts the whole stack with `docker compose up -d --build` and waits for it to answer.

Alternative — clone and run:

```bash
git clone https://github.com/UncleD0886475978/sim.git
cd sim && ./setup.sh
```

- **Repo:** https://github.com/UncleD0886475978/sim
- **Public status:** Public.
- **Stack actually found:** Docker Compose with 4 services — `model` (llama.cpp `llama-server` serving Gemma 4 E4B locally, OpenAI-compatible endpoint), `backend` (FastAPI, host port 8000), `frontend` (static site served on host port 3000), `db` (Postgres for chat history). The Maya cover-letter feature uses `backend/data/resume.txt`. No cloud API key — the model runs on the machine itself.
- **What setup.sh does:** Bootstraps base tools + Docker, finds or clones the repo, checks RAM (warns under ~14 GB and points at the smaller quant), creates `.env` from the example, runs `docker compose up -d --build`, and polls `http://localhost:8000/api/health` + `http://localhost:3000` for up to ~5 minutes before printing the URLs and day-to-day commands.
- **Requirements:** 16 GB+ RAM for the default Q8_0 model (~8.6 GB download on first run) and ~15 GB free disk. On smaller machines: `GEMMA_QUANT=Q4_0 bash setup.sh` (~5 GB model).
- **Issue it prevents:** The "it works on my machine" gap — one paste on a fresh VM installs Docker itself instead of stopping at "docker not found," and the summary warns against `docker compose down -v`, which would delete the chat-history database and the downloaded model.

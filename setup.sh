#!/usr/bin/env bash
# setup.sh — sim (SimAI)
# Self-hosted AI chat + coding assistant: FastAPI backend, vanilla-JS
# frontend, Postgres history, and a local Gemma 4 model served by
# llama.cpp (llama-server) — all wired in docker-compose.yml
# (services: model, backend, frontend, db). Frontend on host port 3000,
# backend API on 8000. No cloud API key needed: the model runs locally.
# First run downloads the Gemma 4 E4B model (~8.6 GB at Q8_0) and wants
# 16 GB+ RAM; on smaller machines set GEMMA_QUANT=Q4_0 (~5 GB).
set -e

REPO_NAME="sim"
REPO="sim"
OWNER="UncleD0886475978"
REPO_URL="https://github.com/UncleD0886475978/${REPO_NAME}.git"
RUN_ONELINE="curl -fsSL https://raw.githubusercontent.com/${OWNER}/${REPO}/main/setup.sh | bash"

echo "==> Step 1/6: Platform check + base bootstrap (git, curl)"
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "ERROR: this script needs root or sudo to install packages."
    exit 1
  fi
fi
APT=0
if [ "$(uname -s)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then APT=1; fi
INSTALLED=""
APT_UPDATED=""
note_installed() { INSTALLED="${INSTALLED} $1"; }
apt_update_once() {
  if [ -z "${APT_UPDATED}" ]; then $SUDO apt-get update -y; APT_UPDATED=1; fi
}
apt_install() {
  apt_update_once
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y "$@"
}
if [ "${APT}" -eq 1 ]; then
  BASE_PKGS=""
  command -v git >/dev/null 2>&1 || BASE_PKGS="${BASE_PKGS} git"
  command -v curl >/dev/null 2>&1 || BASE_PKGS="${BASE_PKGS} curl"
  [ -f /etc/ssl/certs/ca-certificates.crt ] || BASE_PKGS="${BASE_PKGS} ca-certificates"
  command -v gpg >/dev/null 2>&1 || BASE_PKGS="${BASE_PKGS} gnupg"
  if [ -n "${BASE_PKGS}" ]; then
    echo "    Installing base tools:${BASE_PKGS}"
    # shellcheck disable=SC2086
    apt_install ${BASE_PKGS}
    note_installed "${BASE_PKGS}"
  else
    echo "    Base tools already present (git, curl, ca-certificates, gnupg)."
  fi
else
  echo "    Non-apt platform detected — bootstrap will only CHECK tools and print install guidance."
fi

echo "==> Step 2/6: Locate the repo"
if [ -f "$0" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
else
  SCRIPT_DIR="$PWD"
fi
if [ -f "docker-compose.yml" ] && [ -f "backend/main.py" ]; then
  REPO_DIR="$PWD"
  echo "    Already inside the repo checkout: $REPO_DIR"
else
  REPO_DIR="$HOME/repos/$REPO_NAME"
  if [ -d "$REPO_DIR/.git" ]; then
    echo "    Existing checkout found — pulling latest..."
    git -C "$REPO_DIR" pull --ff-only || true
  else
    if ! command -v git >/dev/null 2>&1; then
      echo "    ERROR: git not found. Install git first: https://git-scm.com/downloads"
      exit 1
    fi
    echo "    Cloning $REPO_URL into $REPO_DIR ..."
    mkdir -p "$HOME/repos"
    git clone "$REPO_URL" "$REPO_DIR"
  fi
fi
cd "$REPO_DIR"

echo "==> Step 3/6: Bootstrap Docker"
DOCKER="docker"
install_docker() {
  if command -v docker >/dev/null 2>&1; then
    echo "    docker: already present ($(docker --version))"
  elif [ "${APT}" -eq 1 ]; then
    echo "    Installing Docker Engine via the official get.docker.com script..."
    curl -fsSL https://get.docker.com | $SUDO sh
    note_installed "docker"
  else
    return 1
  fi
  if ! docker info >/dev/null 2>&1 && ! $SUDO docker info >/dev/null 2>&1; then
    echo "    Starting the Docker daemon..."
    $SUDO systemctl enable --now docker 2>/dev/null || $SUDO service docker start 2>/dev/null || true
    for _i in $(seq 1 15); do
      if docker info >/dev/null 2>&1 || $SUDO docker info >/dev/null 2>&1; then break; fi
      sleep 2
    done
  fi
  if docker info >/dev/null 2>&1; then
    DOCKER="docker"
  elif $SUDO docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
    if [ "$(id -u)" -ne 0 ]; then
      $SUDO usermod -aG docker "$USER" 2>/dev/null || true
      echo "    NOTE: you were added to the 'docker' group (applies at next login); this run uses 'sudo docker'."
    fi
  else
    echo "ERROR: Docker is installed but the daemon could not be started."
    echo "       On a VM:  sudo systemctl start docker   |   In a container/WSL without systemd, Docker cannot run here."
    exit 1
  fi
  echo "    docker daemon OK (using: ${DOCKER})"
}
MISSING_LIST=""
install_docker || MISSING_LIST="${MISSING_LIST} docker(https://docs.docker.com/get-docker/)"
if [ -n "${MISSING_LIST}" ]; then
  echo "ERROR: could not auto-install on this platform. Missing:${MISSING_LIST}"
  echo "Install the tool(s) manually, then re-run this script."
  exit 1
fi
# shellcheck disable=SC2086
if ! ${DOCKER} compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' (v2 plugin) is not available."
  echo "       The get.docker.com installer normally includes it; on Debian/Ubuntu you can also run:"
  echo "       sudo apt-get install -y docker-compose-plugin"
  exit 1
fi
echo "    docker: $(docker --version)"

echo "==> Step 4/6: Machine check + environment file"
if [ -r /proc/meminfo ]; then
  MEM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
  echo "    RAM detected: ~${MEM_GB} GB"
  if [ "${MEM_GB:-0}" -lt 14 ] && [ "${GEMMA_QUANT:-Q8_0}" = "Q8_0" ]; then
    echo "    WARNING: the default model (Gemma 4 E4B, Q8_0) wants 16 GB+ RAM."
    echo "             On this machine, re-run with the smaller quant:"
    echo "               GEMMA_QUANT=Q4_0 bash setup.sh"
    echo "             Continuing anyway — the model service may run out of memory."
  fi
fi
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "    Created .env from .env.example (defaults are fine for local use)."
fi

echo "==> Step 5/6: Build and start SimAI (docker compose up -d --build)"
echo "    First run downloads the Gemma 4 model (~8.6 GB) — this can take a while."
# shellcheck disable=SC2086
${DOCKER} compose up -d --build

echo "==> Step 6/6: Wait for SimAI to answer"
APP_URL="http://localhost:3000"
HEALTH_URL="http://localhost:8000/api/health"
READY=0
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null "$HEALTH_URL" 2>/dev/null && curl -fsS -o /dev/null "$APP_URL" 2>/dev/null; then
    READY=1; break
  fi
  sleep 5
done
if [ "$READY" = "1" ]; then
  echo "    SimAI is responding (backend health + frontend)."
else
  echo "    WARNING: not responding yet after ~5 minutes — the model may still be"
  echo "    downloading/loading. Check progress with the logs command below."
fi

cat <<EOF

=================== BOOTSTRAP SUMMARY ===================
Installed during this run:${INSTALLED:- (nothing — all tools were already present)}
Working copy: ${REPO_DIR}
Next time, set up from scratch on any fresh Ubuntu VM with one line:
  ${RUN_ONELINE}
=========================================================
EOF

echo ""
echo "============================================================"
echo "Done. SimAI is at:        $APP_URL"
echo "Backend health check:     $HEALTH_URL"
echo ""
echo "Day-to-day:"
echo "  Start:  cd $REPO_DIR && ${DOCKER} compose up -d"
echo "  Stop:   cd $REPO_DIR && ${DOCKER} compose down        (keeps chat history + model)"
echo "  Logs:   cd $REPO_DIR && ${DOCKER} compose logs -f"
echo "  NEVER run 'docker compose down -v' unless you want to delete"
echo "  the chat history database AND the downloaded model."
echo "============================================================"

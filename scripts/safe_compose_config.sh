#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

docker_compose_available() {
  local docker_bin="$1"
  local output
  output="$("${docker_bin}" compose version 2>&1 || true)"
  [[ "${output}" == *"Docker Compose version"* ]]
}

DOCKER_BIN=""
if command -v docker >/dev/null 2>&1 && docker_compose_available docker; then
  DOCKER_BIN="docker"
elif command -v docker.exe >/dev/null 2>&1 && docker_compose_available docker.exe; then
  DOCKER_BIN="docker.exe"
elif [ -x "/c/Program Files/Docker/Docker/resources/bin/docker.exe" ] \
  && docker_compose_available "/c/Program Files/Docker/Docker/resources/bin/docker.exe"; then
  DOCKER_BIN="/c/Program Files/Docker/Docker/resources/bin/docker.exe"
elif [ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ] \
  && docker_compose_available "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"; then
  DOCKER_BIN="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
else
  echo "ERROR: docker compose is not available in this shell." >&2
  exit 1
fi

"${DOCKER_BIN}" compose config "$@" | sed -E \
  -e "s/^([[:space:]]*(ADMIN_TOKEN|ASK_ANSWER_WEBHOOK_SECRET|SESSION_SECRET|GOOGLE_CLIENT_SECRET|DISCORD_BOT_TOKEN|DISCORD_WEBHOOK_URL|SMTP_USER|SMTP_PASS|N8N_DB_PASSWORD|N8N_ENCRYPTION_KEY|N8N_TOKEN|LLM_API_KEY|LOCAL_LLM_API_KEY|PROXMOX_API_TOKEN|UNIFI_API_KEY|HOMEASSISTANT_TOKEN|PLEX_TOKEN|OVERSEERR_API_KEY|TAUTULLI_API_KEY|RADARR_API_KEY|SONARR_API_KEY):).*/\1 REDACTED/I" \
  -e "s/(Bearer )[A-Za-z0-9._~+\\/=:-]+/\1REDACTED/g" \
  -e "s/sk-[A-Za-z0-9_-]+/sk-REDACTED/g"

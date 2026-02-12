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

OUT_DIR="${ROOT_DIR}/output"
mkdir -p "${OUT_DIR}"

STRICT_HARDENING="${STRICT_HARDENING:-0}"
COMPOSE_FILES=(-f docker-compose.yml)
MODE_LABEL="default"
if [[ "${STRICT_HARDENING}" == "1" ]]; then
  COMPOSE_FILES+=(-f docker-compose.hardened.yml)
  MODE_LABEL="strict"
fi

compose_cmd() {
  "${DOCKER_BIN}" compose "${COMPOSE_FILES[@]}" "$@"
}

backend_block_has_pattern() {
  local file="$1"
  local pattern="$2"
  awk -v pattern="${pattern}" '
    /^  backend:/ { in_backend=1; next }
    in_backend && /^  [a-zA-Z0-9_-]+:/ { in_backend=0 }
    in_backend && $0 ~ pattern { found=1 }
    END { exit(found ? 0 : 1) }
  ' "${file}"
}

echo "[1/10] docker compose config (redacted) mode=${MODE_LABEL}"
bash scripts/safe_compose_config.sh "${COMPOSE_FILES[@]}" > "${OUT_DIR}/compose.config.${MODE_LABEL}.redacted.yaml"

echo "[2/10] backend hardening source checks"
backend_block_has_pattern docker-compose.yml "read_only:[[:space:]]*true"
backend_block_has_pattern docker-compose.yml "tmpfs:"
backend_block_has_pattern docker-compose.yml "cap_drop:"
if backend_block_has_pattern docker-compose.yml "no-new-privileges:true"; then
  echo "ERROR: backend default compose must not set no-new-privileges:true on this host." >&2
  exit 1
fi
backend_block_has_pattern docker-compose.hardened.yml "no-new-privileges:true"
backend_block_has_pattern docker-compose.yml "command:[[:space:]]*\\[\"python\", \"-m\", \"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"\\]"

echo "[3/10] docker compose up -d --build"
compose_cmd up -d --build

echo "[4/10] docker compose ps"
compose_cmd ps | tee "${OUT_DIR}/compose.ps.${MODE_LABEL}.txt"

echo "[5/10] wait for backend health"
BACKEND_CID="$(compose_cmd ps -q backend)"
if [[ -z "${BACKEND_CID}" ]]; then
  echo "ERROR: backend container is not running." >&2
  exit 1
fi
deadline=$((SECONDS + 120))
while true; do
  backend_health="$("${DOCKER_BIN}" inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${BACKEND_CID}")"
  if [[ "${backend_health}" == "healthy" ]]; then
    echo "backend health=healthy" | tee "${OUT_DIR}/backend.health.${MODE_LABEL}.txt"
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "ERROR: backend did not become healthy (final status: ${backend_health})." >&2
    compose_cmd logs --no-color --tail=200 backend > "${OUT_DIR}/backend.logs.${MODE_LABEL}.tail.txt"
    exit 1
  fi
  sleep 2
done

echo "[6/10] docker compose exec -T frontend nginx -T"
compose_cmd exec -T frontend nginx -T > "${OUT_DIR}/nginx.runtime.conf"

echo "[7/10] curl /healthz"
curl -fsS "http://localhost:9182/healthz" | tee "${OUT_DIR}/healthz.json"

echo "[8/10] Dockerfile USER checks"
grep -n "^USER " backend/Dockerfile
grep -n "^USER " frontend/Dockerfile

echo "[9/10] compose hardening flag checks"
grep -n "read_only: true" docker-compose.yml
grep -n "tmpfs:" docker-compose.yml
grep -n "cap_drop:" docker-compose.yml
grep -n "pids_limit:" docker-compose.yml
grep -n "mem_limit:" docker-compose.yml
grep -n "no-new-privileges:true" docker-compose.hardened.yml

echo "[10/10] log leak checks"
LOG_FILE="${OUT_DIR}/compose.logs.${MODE_LABEL}.txt"
compose_cmd logs --no-color --tail=500 > "${LOG_FILE}"
if grep -E -i "(X-Plex-Token|apikey|access_token)=[^*&[:space:]][^&[:space:]]*" "${LOG_FILE}" >/dev/null; then
  echo "ERROR: raw query-token values found in compose logs." >&2
  grep -n -E -i "(X-Plex-Token|apikey|access_token)=[^*&[:space:]][^&[:space:]]*" "${LOG_FILE}" >&2 || true
  exit 1
fi
if grep -E -i "Bearer[[:space:]]+[^*[:space:]][^[:space:]]*" "${LOG_FILE}" >/dev/null; then
  echo "ERROR: raw bearer token values found in compose logs." >&2
  grep -n -E -i "Bearer[[:space:]]+[^*[:space:]][^[:space:]]*" "${LOG_FILE}" >&2 || true
  exit 1
fi
if grep -E -i "(SESSION_SECRET|ADMIN_TOKEN)" "${LOG_FILE}" >/dev/null; then
  echo "ERROR: secret variable names found in compose logs." >&2
  grep -n -E -i "(SESSION_SECRET|ADMIN_TOKEN)" "${LOG_FILE}" >&2 || true
  exit 1
fi

echo "Audit checks completed for mode=${MODE_LABEL}."

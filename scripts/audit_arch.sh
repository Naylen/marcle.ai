#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN=""
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DOCKER_BIN="docker"
elif command -v docker.exe >/dev/null 2>&1 && docker.exe compose version >/dev/null 2>&1; then
  DOCKER_BIN="docker.exe"
else
  echo "ERROR: docker compose is not available in this shell." >&2
  exit 1
fi

OUT_DIR="${ROOT_DIR}/output"
mkdir -p "${OUT_DIR}"

echo "[1/7] docker compose config (redacted)"
bash scripts/safe_compose_config.sh > "${OUT_DIR}/compose.config.redacted.yaml"

echo "[2/7] docker compose up -d --build"
"${DOCKER_BIN}" compose up -d --build

echo "[3/7] docker compose ps"
"${DOCKER_BIN}" compose ps

echo "[4/7] docker compose exec -T frontend nginx -T"
"${DOCKER_BIN}" compose exec -T frontend nginx -T > "${OUT_DIR}/nginx.runtime.conf"

echo "[5/7] curl /healthz"
curl -fsS "http://localhost:9182/healthz" | tee "${OUT_DIR}/healthz.json"

echo "[6/7] Dockerfile USER checks"
grep -n "^USER " backend/Dockerfile
grep -n "^USER " frontend/Dockerfile

echo "[7/7] compose hardening flag checks"
grep -n "read_only: true" docker-compose.yml
grep -n "tmpfs:" docker-compose.yml
grep -n "cap_drop:" docker-compose.yml
grep -n "no-new-privileges:true" docker-compose.yml
grep -n "pids_limit:" docker-compose.yml
grep -n "mem_limit:" docker-compose.yml

echo "Audit checks completed."

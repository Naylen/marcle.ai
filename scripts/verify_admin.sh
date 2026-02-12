#!/usr/bin/env bash
set -u

BASE_URL="${MARCLE_BASE_URL:-http://localhost:9182}"
FAILURES=0

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1"
  FAILURES=$((FAILURES + 1))
}

http_status() {
  local url="$1"
  local header="${2:-}"
  if [[ -n "$header" ]]; then
    curl -sS -o /dev/null -w "%{http_code}" -H "$header" "$url" 2>/dev/null || true
  else
    curl -sS -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true
  fi
}

check_status() {
  local url="$1"
  local expected="$2"
  local label="$3"
  local header="${4:-}"
  local got

  got="$(http_status "$url" "$header")"
  if [[ "$got" == "$expected" ]]; then
    pass "$label (HTTP $got)"
  else
    fail "$label expected HTTP $expected but got ${got:-<none>}"
  fi
}

echo "Starting backend + frontend with build..."
if docker compose up -d --build backend frontend; then
  pass "docker compose up -d --build backend frontend"
else
  fail "docker compose up -d --build backend frontend"
fi

echo "Waiting for public endpoints to respond..."
for _ in $(seq 1 45); do
  if [[ "$(http_status "$BASE_URL/")" == "200" ]] && [[ "$(http_status "$BASE_URL/api/status")" == "200" ]]; then
    break
  fi
  sleep 2
done

check_status "$BASE_URL/" "200" "Landing page /"
check_status "$BASE_URL/admin" "200" "Admin page /admin"
check_status "$BASE_URL/api/status" "200" "Status API /api/status"

admin_html="$(curl -sS "$BASE_URL/admin" 2>/dev/null || true)"
if [[ "$admin_html" == *'id="admin-root"'* ]]; then
  pass "/admin contains admin shell root id"
else
  fail "/admin missing id=\"admin-root\""
fi

if [[ -n "${ADMIN_TOKEN:-}" ]]; then
  check_status "$BASE_URL/api/admin/services" "200" "Admin services API with bearer token" "Authorization: Bearer $ADMIN_TOKEN"
else
  echo "SKIP: ADMIN_TOKEN is unset; skipping authenticated /api/admin/services check"
fi

if [[ "$FAILURES" -eq 0 ]]; then
  echo "VERIFY RESULT: PASS"
  exit 0
fi

echo "VERIFY RESULT: FAIL ($FAILURES issues)"
echo "---- frontend logs (last 60 lines) ----"
docker compose logs frontend --tail 60 || true
exit 1

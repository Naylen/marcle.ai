#!/usr/bin/env bash
set -u

BASE_URL="${1:-${MARCLE_BASE_URL:-http://localhost:9182}}"
FAILURES=0

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1"
  FAILURES=$((FAILURES + 1))
}

check_status() {
  local url="$1"
  local expected="$2"
  local label="$3"
  local extra_header="${4:-}"
  local status

  if [[ -n "$extra_header" ]]; then
    status="$(curl -sS -o /dev/null -w "%{http_code}" -H "$extra_header" "$url" 2>/dev/null || true)"
  else
    status="$(curl -sS -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)"
  fi

  if [[ "$status" == "$expected" ]]; then
    pass "$label (HTTP $status)"
  else
    fail "$label expected HTTP $expected but got ${status:-<none>}"
  fi
}

echo "Running admin smoke checks against: $BASE_URL"

admin_html="$(curl -sS "$BASE_URL/admin" 2>/dev/null || true)"
if [[ -z "$admin_html" ]]; then
  fail "/admin did not return HTML"
else
  pass "/admin returned content"

  for required_id in 'id="admin-root"' 'id="admin-token"' 'id="service-list-body"'; do
    if grep -Fq "$required_id" <<<"$admin_html"; then
      pass "/admin contains $required_id"
    else
      fail "/admin missing $required_id"
    fi
  done
fi

check_status "$BASE_URL/styles.css" "200" "styles.css serves"
check_status "$BASE_URL/admin.js" "200" "admin.js serves"
check_status "$BASE_URL/" "200" "landing page serves"
check_status "$BASE_URL/ask" "200" "ask page serves"
check_status "$BASE_URL/api/status" "200" "public /api/status"
check_status "$BASE_URL/api/overview" "200" "public /api/overview"
check_status "$BASE_URL/api/admin/services" "401" "admin services requires token"

if [[ -n "${ADMIN_TOKEN:-}" ]]; then
  check_status "$BASE_URL/api/admin/services" "200" "admin services with bearer token" "Authorization: Bearer $ADMIN_TOKEN"
else
  echo "SKIP: ADMIN_TOKEN not set; skipping authenticated admin API check"
fi

if [[ "$FAILURES" -eq 0 ]]; then
  echo "SMOKE RESULT: PASS"
  exit 0
fi

echo "SMOKE RESULT: FAIL ($FAILURES issues)"
exit 1

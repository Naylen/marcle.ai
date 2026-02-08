#!/usr/bin/env python3
import json
import os
import urllib.request

BASE_URL = os.getenv("MARCLE_BASE_URL", "http://localhost:9181").rstrip("/")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


def http_json(path: str, auth: bool = False):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    if auth:
        if not ADMIN_TOKEN:
            raise RuntimeError("ADMIN_TOKEN env var is not set for audit script.")
        req.add_header("Authorization", f"Bearer {ADMIN_TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    admin = http_json("/api/admin/services", auth=True)
    status = http_json("/api/status", auth=False)

    status_services = status.get("services", status)

    status_by_id = {}
    if isinstance(status_services, list):
        for svc in status_services:
            sid = svc.get("id")
            if sid:
                status_by_id[sid] = svc
    elif isinstance(status_services, dict):
        status_by_id = status_services

    services = admin.get("services", admin)
    if not isinstance(services, list):
        print("Unexpected /api/admin/services response shape.")
        print(json.dumps(admin, indent=2))
        return 2

    services = sorted(services, key=lambda item: str(item.get("id") or ""))
    problems = 0
    print(f"\nAudit: {len(services)} services from {BASE_URL}\n")

    for svc in services:
        sid = svc.get("id")
        name = svc.get("name", sid)
        enabled = svc.get("enabled")
        url = svc.get("url")
        check_type = svc.get("check_type")
        auth_ref = svc.get("auth_ref")
        cred_present = svc.get("credential_present")

        status_svc = status_by_id.get(sid, {})
        health = status_svc.get("health") or status_svc.get("status") or "unknown"
        last_error = status_svc.get("error") or status_svc.get("last_error") or ""

        auth_scheme = None
        if auth_ref:
            auth_scheme = auth_ref.get("scheme")

        issues = []
        if enabled and not url:
            issues.append("enabled but url missing")
        if enabled and not check_type:
            issues.append("enabled but check_type missing")
        if auth_ref and auth_scheme in ("header", "bearer", "basic", "query_param") and cred_present is False:
            issues.append(f"credential_missing(env={auth_ref.get('env')})")
        if auth_scheme == "query_param" and not auth_ref.get("param_name"):
            issues.append("query_param missing param_name")
        if auth_scheme == "header" and not auth_ref.get("header_name"):
            issues.append("header missing header_name")
        if enabled and str(health).lower() in ("degraded", "down", "unknown") and last_error:
            issues.append(f"health={health} error={last_error}")

        line = (
            f"- {sid:14} | {name:18} | enabled={str(enabled):5} | "
            f"health={str(health):8} | auth={auth_scheme or 'none':11} | cred={cred_present}"
        )
        print(line)
        if issues:
            problems += 1
            for issue in issues:
                print(f"    ! {issue}")

    print(f"\nDone. Services with issues: {problems}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

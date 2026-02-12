# Secrets Handling

## Why `docker compose config` Is Sensitive

`docker compose config` resolves environment interpolation and prints effective
service configuration. That output can include plaintext credentials such as:

- `ADMIN_TOKEN`
- `SESSION_SECRET`
- `ASK_ANSWER_WEBHOOK_SECRET`
- OAuth client secrets
- API tokens and SMTP credentials

Treat resolved compose output as secret material.

## Safe Sharing Policy

- Do not paste raw `docker compose config` output in chat, tickets, or logs.
- Use redacted output when troubleshooting:

```bash
bash scripts/safe_compose_config.sh
```

## Operational Checklist

- Keep `.env` local and never commit it.
- Store secret files under `./secrets/` when using Docker secrets overlays.
- Rotate tokens immediately if raw resolved config is exposed.

## Runtime Log Redaction

Backend logging now redacts sensitive values before output.

- Query parameters keep keys but replace sensitive values with `***`.
- Bearer tokens in log lines are replaced with `Bearer ***`.
- `httpx` / `httpcore` raw request logging is reduced to avoid unsafe URL output.

Example (sanitized):

- Before: `GET http://plex.local/identity?X-Plex-Token=abc123&apikey=xyz789`
- After: `GET http://plex.local/identity?X-Plex-Token=***&apikey=***`

## Optional Docker Secrets Overlay

Default workflow remains unchanged (`.env` works as-is).

For file-based secret injection, use the optional override:

```bash
docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d
```

Create secret files first (for example `secrets/ADMIN_TOKEN`,
`secrets/SESSION_SECRET`, etc.).

## Optional Strict Backend Hardening

Default backend security is host-compatible and keeps non-root execution, `cap_drop: [ALL]`,
`read_only: true`, and `tmpfs` for `/tmp`.

To opt into stricter backend policy (`no-new-privileges:true`), use:

```bash
docker compose -f docker-compose.yml -f docker-compose.hardened.yml up -d --build
```

Some host policies can block backend startup in this strict mode with `operation not permitted`
on Python exec. Keep strict mode opt-in unless your host confirms compatibility.

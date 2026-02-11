# n8n Workflows

This directory stores versioned n8n workflow exports used by `marcle.ai` automations.
Keeping exports in git provides review history, reproducible automation setup, and easier promotion between environments.

## Manual Import (n8n UI)

1. Open n8n.
2. Go to **Workflows**.
3. Choose **Import from File**.
4. Select a workflow JSON from `n8n/workflows/`.
5. Reconnect credentials (for Discord) and activate the workflow.

## Recommended Automated Import (High Level)

For production, keep workflows in this repo as the source of truth and sync them to n8n through an automated deployment step (for example using n8n API-driven upsert in CI/CD).
Use a deterministic manifest (`n8n/workflow_manifest.json`) so deployment can map each logical workflow key to a specific JSON file.

## Required Environment Variables

These workflows expect the following environment variables in n8n runtime:

- `BACKEND_BASE_URL` (example: `http://backend:8000`)
- `N8N_TOKEN` (used as `X-N8N-TOKEN` header when calling backend)
- `DISCORD_QUESTIONS_CHANNEL_ID` (questions intake channel)
- `DISCORD_GUILD_ID` (Discord server/guild id)

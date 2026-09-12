# V2.13.1.7.3 — Automatic Score Refresh

Built from the confirmed-stable V2.13.1.7.2 baseline.

## What changed
- Adds `AUTO_SYNC_TOKEN` environment-variable support.
- Adds protected `POST /api/auto-score-refresh` for Supabase Cron.
- Endpoint refreshes the current NFL week using the already-working NFLData + ESPN score pipeline.
- Endpoint returns week, game count, final-game count, and refresh timestamp.
- Adds the endpoint to the shared-site public-route exemption; access is still protected by `X-Auto-Sync-Token`.
- Keeps the lightweight `/health` endpoint unchanged.
- No database migration.
- No background thread or in-process scheduler.

## Recommended schedule
Supabase Cron calls the endpoint every 5 minutes. This keeps score data current during games and also refreshes schedule/status changes outside game windows.

## Render
Keep Start Command:
`gunicorn --workers 1 --threads 4 --timeout 60 app:app`

Keep existing `AUTO_SYNC_TOKEN` environment variable configured.

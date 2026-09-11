# V2.13.1.7.1 — Lightweight Health Check

## Purpose
Prevent Render's 5-second HTTP health probe from being blocked by external Supabase requests.

## Change
The `/health` endpoint now returns a local JSON liveness response only:

```json
{"status":"ok","season":2026}
```

The previous health endpoint performed 13 sequential Supabase REST checks on every Render health probe. Those external calls could exceed Render's 5-second health-check timeout and cause temporary instance failures, HTTP 502/503 responses, or partially loaded pages.

## Unchanged
- Draft Pool scoring and rosters
- Survivor Pool
- Confidence Pool
- Member accounts
- Forum
- ESPN/NFL score refresh behavior
- Supabase schema/data
- No migration required
- No new environment variables

## Recommended Render Start Command
`gunicorn --workers 1 --threads 4 --timeout 60 app:app`

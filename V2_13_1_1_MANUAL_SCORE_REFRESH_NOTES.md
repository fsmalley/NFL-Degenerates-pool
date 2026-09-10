# V2.13.1.1 — Manual Score Refresh Test

Built directly from the known-good V2.13.1 Member Export baseline.

## Purpose
This is a controlled stability test before reintroducing automatic score refresh.

## Changes
- Adds one Commissioner-only endpoint: `POST /api/admin/score-refresh`
- Adds **Manual NFL Score Refresh** to Commissioner Test Lab
- Lets the Commissioner optionally specify Week 1–18
- Uses the existing `sync_week()` logic
- Reports total games and final games after refresh

## Intentionally NOT included
- No Supabase Cron
- No scheduler endpoint
- No automatic page-triggered sync
- No Results-page timer
- No background threads/timers
- No new database tables
- No new environment variables required

If this version remains stable on Render, the next controlled step will be adding only the protected scheduler endpoint.

# V2.13.1.2 — NFLData Final Status Fix

Built directly from the stable V2.13.1.1 manual-score-refresh test.

## Root cause
NFLData's games endpoint is backed by nflverse schedule/game data. That data does
not reliably provide a textual `status` value such as `final`. The app therefore
defaulted completed games to `scheduled`, even when final scores were present.

The nflverse `result` field is the authoritative completion signal for this
dataset: it is populated after a completed game and null for games not yet played.

## Fix
- `normalize_game()` now marks a game `final` when either:
  - the source explicitly provides a recognized final status, OR
  - the NFLData/nflverse `result` field is populated.
- Winner, loser, and point margin are then calculated normally.
- Added a quality check using an nflverse-style completed-game row.

## Not changed
- No automatic scheduler
- No Supabase Cron
- No page polling changes
- No database migration
- No new environment variables

## Expected Week 1 test
After deployment, Commissioner -> Test Lab -> Manual NFL Score Refresh should
report `Week 1 refreshed. 1/16 games final.` if NFLData has ingested the completed
Seattle-New England result.

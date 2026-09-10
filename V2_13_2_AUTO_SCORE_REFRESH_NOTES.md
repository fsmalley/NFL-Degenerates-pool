# V2.13.2 — Automatic Score Refresh

NFL Degenerates now supports automatic score refresh throughout the entire NFL week.

The logic uses actual kickoff timestamps rather than assuming Sunday games, so Wednesday, Thursday, Saturday, Sunday, Monday, international, and other special-schedule games are handled automatically.

## Behavior
- Around scheduled kickoffs and for several hours afterward: refreshes are allowed about every 20 minutes.
- Away from games: refreshes are allowed about once every 20 hours.
- Supabase Cron wakes the Render site every 30 minutes.
- When a week becomes fully final, the next week's schedule is staged automatically.
- NFL Results refreshes every 2 minutes while open.
- Draft and Confidence scoring remain final-only.
- Commissioner Test Lab includes **Refresh Scores Now**.

## Setup
1. Deploy V2.13.2.
2. Add `AUTO_SYNC_TOKEN` in Render with a long random value.
3. Replace the placeholder in `v2_13_2_auto_score_refresh_cron.sql` with the same value.
4. Run that SQL in Supabase.
5. Use Commissioner → **Refresh Scores Now** to verify the application-side refresh.

No new tables are required. Existing `site_settings` stores last-refresh timestamps.

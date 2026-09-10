# V2.13.2 Revised — Scheduler-Only Automatic Score Refresh

This revision removes all external NFL score synchronization from ordinary member page requests.

## Architecture
Supabase Cron -> protected `/api/system/score-refresh` -> NFLData/ESPN enrichment -> Supabase.

Member pages -> Supabase stored data only.

## Behavior
- Uses actual kickoff timestamps; no Sunday-only assumptions.
- Around active game windows, the app allows refreshes about every 20 minutes.
- Away from games, it allows about one refresh every 20 hours.
- Supabase Cron wakes the endpoint every 30 minutes.
- Results page re-reads stored Supabase scores every 2 minutes while open; it never contacts NFLData directly.
- Draft and Confidence official scoring remain final-only.
- Commissioner retains a manual **Refresh Scores Now** fallback.
- When all games in a week are final, the next week's schedule is staged automatically.

## Important change from the first V2.13.2 build
The first build connected normal dashboard/Draft/results traffic to smart synchronization. This revised build intentionally does not. Normal browsing cannot trigger an external score pull.

No new database tables are required.

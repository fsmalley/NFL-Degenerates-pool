# V2.13.1.3 — ESPN Live Score Source

Controlled update from V2.13.1.2.

ESPN was already used for kickoff times. This version extends that same scoreboard
feed to current scores and final-game status. NFLData remains the base/fallback.

A game is final when ESPN reports `status.type.completed=true` or `state=post`.
Live games can display current scores but remain non-final, so pool scoring stays
final-only.

No scheduler, Supabase Cron, background timer, database migration, or new
environment variable is included.

Expected Week 1 manual-refresh result: 1/16 final, with Seattle 13 and New England 10.

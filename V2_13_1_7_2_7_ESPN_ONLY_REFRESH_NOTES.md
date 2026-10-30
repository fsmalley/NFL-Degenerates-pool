# V2.13.1.7.2.7 — ESPN-only NFL refresh

- Manual and other existing `sync_week` callers now use ESPN scoreboard directly; NFLData is not called.
- Preserves existing `games.id` by matching season/week/away/home, avoiding duplicate rows after the source switch.
- Preserves existing rows if ESPN fails, returns no games, or returns fewer than 10 games for a week.
- Writes kickoff, game state, score, and final winning margin to the existing `games` table.
- No schema or environment changes. Existing lightweight `/health` unchanged.
- Note: ESPN scoreboard is an undocumented third-party endpoint. Live Render verification is still needed.

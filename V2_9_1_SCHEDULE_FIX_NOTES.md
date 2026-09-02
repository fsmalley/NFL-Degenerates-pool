# V2.9.1 Schedule Date / Time Fix

Problem:
NFLData future schedules commonly provide a date without a full kickoff timestamp. V2.9 therefore could not reliably display or sort actual game kickoff times.

Fix:
The app now fetches the ESPN weekly NFL scoreboard and matches games by away/home team. ESPN's ISO kickoff timestamp is written to the existing `games.game_date` field during `sync_week()`.

Impact:
- Confidence Weekly Picks shows actual kickoff date/time in Eastern Time.
- Confidence entry lock uses the actual first kickoff.
- Confidence final-game tiebreaker uses the actual last scheduled kickoff.
- Survivor kickoff locking also receives better timestamps.
- Draft scoring logic is unchanged.

Database:
No migration required.

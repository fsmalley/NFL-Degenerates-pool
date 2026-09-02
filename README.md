# NFL Results Dashboard V2.0 - Supabase Connection Fix

1. Create a free Supabase project.
2. Open SQL Editor and run `supabase_schema.sql`.
3. In Supabase Project Settings, copy the Project URL and service_role key.
4. In Render > your web service > Environment, add:
   SUPABASE_URL
   SUPABASE_SERVICE_KEY
   ADMIN_PASSWORD
   NFL_SEASON=2026
5. Remove NFL_DB if it exists.
6. Replace the files in your GitHub repository with this V1.6 version and commit.
7. Render will redeploy automatically.

Build command:
    pip install -r requirements.txt

Start command:
    gunicorn app:app

Health check:
    /health

IMPORTANT: Keep the Supabase service_role key private. It belongs only in Render's environment variables.


## V2.0 connection fix

- Supports the newer `sb_secret_...` Supabase secret key and the legacy `service_role` key.
- Automatically removes `/rest/v1` if it was included in `SUPABASE_URL`.
- Writes the exact Supabase health-check error to Render logs if the connection still fails.


## V2.0 Draft Team Pool improvements

- Public leaderboard is read-only by default.
- Commissioner Edit mode verifies the admin password before enabling edits.
- NFL team selections use full-name dropdowns instead of typed abbreviations.
- Duplicate team selections for the same player are blocked.
- Positive scores are highlighted green; negative scores are highlighted red.
- Click a player name to view Week 1-18 scoring breakdown.
- Summary cards show player count, current leader, leading differential, and scoring weeks.
- Improved responsive/mobile layout.
- Existing Render + Supabase environment variables are unchanged.


## V2.0 visual refresh

- Dark fantasy-football dashboard styling.
- Gold accent treatment and stronger first-place emphasis.
- More polished summary cards, team pills, score badges, weekly scorecards, and mobile layout.
- No database or Render/Supabase configuration changes required.


## V2.0 Survivor Pool

New pages:

- `/survivor` — player weekly pick entry.
- `/survivor/results` — weekly Survivor results.

Survivor behavior:

- Players enter their name, NFL week, and one team selection.
- Submitting again with the same player name and week updates that week's pick.
- The same NFL team cannot be used by the same player in another week.
- A win = `SURVIVED`.
- A loss or tie = `ELIMINATED`.
- Games without a final result = `PENDING`.
- Results are calculated automatically from the existing NFL game data.

### Required V2.0 database update

Before deploying V2.0, open the Supabase SQL Editor and run:

`survivor_schema_update.sql`

This creates the persistent `survivor_picks` table. Existing Draft Team Pool and NFL game data are not changed.

### Current submission model

V2.0 is designed as an open player-entry page. A player can correct their own weekly pick by entering the same name and week again. There is not yet a player PIN/login or automatic game-start lock. Those can be added in a later version if desired.


## V2.0 Survivor Controls

- Player PIN protection for Survivor selections. PINs are stored as password hashes only.
- Automatic kickoff lock: a player cannot select a team whose game has started.
- Once the originally selected team's game has started, that week's selection cannot be changed.
- Commissioner override using the existing `ADMIN_PASSWORD`.
- Previously used teams are disabled in the pick dropdown.
- Full-season `/survivor/board` view with Weeks 1–18 and Alive/Eliminated status.
- Current results continue to show Survived, Eliminated, and Pending.

### Required V2.0 database update

Before deploying V2.0, run `survivor_v2_schema_update.sql` once in the Supabase SQL Editor.

This creates the `survivor_players` table used for hashed player PINs. Existing NFL, Draft Team Pool, and Survivor pick data are not deleted or replaced.


## V2.1 Safe Commissioner Test Lab

V2.1 adds `/test-lab`, an isolated commissioner-only test environment.

The Test Lab:
- Uses separate Supabase tables prefixed with `test_`.
- Never writes to live `games`, `draft_players`, `survivor_players`, or `survivor_picks`.
- Seeds a sample Week 1 with four games, three Survivor players, and three Draft Team players.
- Lets the commissioner finalize sample scores and verify Survivor outcomes and Draft Team point differential scoring.
- Includes a reset action that deletes only test-table data.

Before deploying V2.1, run `test_mode_schema_update.sql` once in Supabase SQL Editor.

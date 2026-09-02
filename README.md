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


## V2.2 Full Draft Pool Test

The Test Lab now supports a full Draft Team Pool stress test:

- 25 synthetic Draft players.
- 8 unique NFL teams assigned to each test player.
- 18 synthetic weeks with 16 games per week (288 test games).
- Deterministic fake scores so repeated tests give consistent results.
- Week 1, Weeks 1–5, Weeks 1–10, and full-season simulation controls.
- Weekly scoring columns plus season totals.
- Positive and negative point differential.
- Intentional tied games to verify zero-point behavior.
- Shared ranking numbers when players finish with equal totals.
- All simulation data remains in isolated `test_` Supabase tables.

Before deploying V2.2, run `v2_2_full_draft_test_schema_update.sql` once in Supabase SQL Editor. It only adds team3 through team8 to `test_draft_players`.


### V2.2 running-total enhancement

The Draft Test Lab now displays:
- each player's score for the selected week;
- cumulative running total through that week;
- player rank as of the selected week;
- weekly score and running total together for Weeks 1–18;
- leaderboard re-sorting whenever the selected "as of" week changes.

This makes it possible to verify that standings move correctly from week to week instead of ranking only by the current week's result.


## V2.3 Organized Pool Navigation

The top navigation is now grouped by pool so visitors can immediately see which pages belong together.

- **Draft Pool**
  - Season Standings
  - Leaderboard
  - Player / Team Breakdown
- **Survivor Pool**
  - Make a Pick
  - Weekly Results
  - Season Board
- **Confidence Pool**
  - Placeholder group marked Coming Soon
- **Commissioner**
  - Test Lab

Page headings now repeat the pool name, such as `Draft Pool — Season Standings` and `Survivor Pool — Weekly Results`. This release changes navigation and labels only; scoring and database behavior are unchanged.


## V2.4 Survivor Pick Delete

Commissioners can now delete an incorrect Survivor pick from the **Survivor Pool → Weekly Results** page.

1. Select the desired week.
2. Enter the commissioner password under **Manage Survivor Picks**.
3. Enable Delete Controls.
4. Click **Delete Pick** beside the player and confirm.

The deletion removes only that week's `survivor_picks` row. It does not remove the player's Survivor PIN/account, so the player can submit a replacement pick. No Supabase schema changes are required.


## V2.5 Survivor Pick Visibility & Deadlines

V2.5 adds weekly Survivor privacy and deadline controls.

- Default weekly pick deadline: **Sunday at 1:00 PM Eastern**
- Default weekly reveal time: **Sunday at 1:00 PM Eastern**
- Commissioner can change deadline and reveal independently for each week
- Before reveal, public pages show only **Pick Submitted** and do not expose the selected team
- Player history is now protected by the player's Survivor PIN
- Each selected team still locks at its own kickoff
- All remaining teams lock when the weekly deadline arrives
- Commissioner override remains available after player deadlines
- Commissioner mode on Weekly Results can still view and delete hidden picks

### Required Supabase update

Run `survivor_v2_5_visibility_schema_update.sql` once in the Supabase SQL Editor before deploying V2.5.

## V2.6 Quality & Refinement

V2.6 is a reliability-focused release. Confidence Pool remains **Coming Soon**.

### Production safeguards

- Draft Pool point differential is counted only after the NFL data source explicitly reports the game as final/completed/closed.
- Survivor outcomes remain Pending until the game is explicitly final, even if live scores are present.
- Public Survivor Season Board no longer leaks an elimination before that week's reveal time.
- Server-side Survivor validation blocks a team that is not scheduled to play that week, including bye-week teams.
- Draft standings now use shared competition ranking for tied totals (1, 1, 3).
- Survivor player lookup and creation are explicitly season-scoped.
- New Survivor PIN records use Werkzeug hashing while retaining compatibility with the prior V2.x custom PIN hash format.
- Health check now verifies Draft, Survivor picks, Survivor players, and weekly Survivor settings tables.
- Duplicate/dead helper implementations were removed from app.py.

### Deployment

There is **no new Supabase migration for V2.6**. If V2.5 is already working, deploy the V2.6 code normally through GitHub/Render.


## V2.7 Draft Pool Salary Cap & Team Values

V2.7 adds a season-configurable salary system to the Draft Pool.

- 2026 salary cap: **$39,500**
- All 32 team values are seeded from the approved 2026 salary schedule
- Draft team dropdowns display each team's salary
- Every player row shows **Salary Used** and **Remaining**
- Salary totals update immediately while teams are selected
- Rows are visually flagged if a selection exceeds the cap
- Duplicate team selections remain prohibited
- The server independently rejects any Draft selection above the cap
- Commissioner Mode includes **Salary Settings** to change the cap and all 32 team values
- Salary cap/team values are stored by season for future-year setup

### Required Supabase update

Run `draft_v2_7_salary_schema_update.sql` once in the Supabase SQL Editor before deploying V2.7.


## V2.8 Reliability & Test Lab Refinement

V2.8 is a quality-focused release. Confidence Pool remains Coming Soon.

- Added commissioner-only automated quality checks and live Supabase diagnostics.
- Fixed Survivor submit-button state after the weekly deadline.
- Draft salary changes warn if existing rosters become over the cap.
- Improved mobile commissioner controls and touch-friendly table scrolling.
- Quality checks are read-only and do not alter live pool records.
- No Supabase schema migration is required for V2.8.


## V2.9 Confidence Pool

V2.9 activates the Confidence Pool while leaving the stable Draft and Survivor pools intact.

### Player entry
- Players choose a winner for every NFL game scheduled in the selected week.
- Each game receives one confidence value.
- Every value from **1 through the number of games that week** must be used exactly once.
- Example: a 16-game week uses 16, 15, 14 ... 1.
- A perfect 16-game week is worth 136 confidence points.
- Players use a private 4–12 digit Confidence PIN to retrieve/update their own entry.
- The full weekly entry locks when the first scheduled game begins.
- Other players' selections remain hidden until the weekly entry lock.

### Tiebreaker
- The player predicts the combined score of the final scheduled game of the week.
- Weekly standings rank by confidence points first.
- If confidence points are tied and the final game is complete, the closest tiebreaker prediction ranks higher.

### Results and standings
- `/confidence` — Make Weekly Picks
- `/confidence/results` — Weekly Results
- `/confidence/standings` — Season Standings
- Correct picks earn the assigned confidence value.
- Incorrect picks and tied NFL games earn 0 points.
- Season standings total all earned confidence points from completed games.

### Database update required
Run `confidence_v2_9_schema_update.sql` in the Supabase SQL Editor before deploying V2.9.

### V2.9 Test Lab
The existing commissioner quality check now also verifies Confidence Pool rule basics and the three new Confidence Supabase tables.


## V2.9.1 — Scheduled Game Dates & Kickoff Times

V2.9.1 fixes future-game schedule timing.

- NFLData remains the source for NFL games, scores, winners, and margins.
- ESPN's NFL scoreboard schedule is used to enrich each matchup with the actual scheduled kickoff timestamp.
- Matchups are paired by away/home teams, including abbreviation normalization such as WSH -> WAS.
- The enriched kickoff timestamp is saved back into the existing `games.game_date` field.
- Confidence Pool games now sort in true scheduled order.
- The final scheduled game used for the weekly tiebreaker is determined using actual kickoff timestamps.
- Confidence entries lock at kickoff of the actual first game of the week.
- Survivor kickoff locks also benefit from the improved timestamps.
- If ESPN is temporarily unavailable, the app falls back to the existing NFLData schedule instead of breaking.

No Supabase schema migration is required for V2.9.1.

## V2.9.2 — Player Instructions
Added collapsible How to Submit instructions to Draft, Survivor, and Confidence player-entry pages. No Supabase migration is required.


## V2.10 — Private Member Login

V2.10 adds a password-protected member landing page titled **NFL Degenerates**.

- All pool pages and APIs require a signed-in member session.
- `/login` is the public landing/login page.
- `/logout` signs the member out.
- The login uses a shared member password.
- The saved member password is stored as a one-way hash in Supabase.
- Commissioner/Test Lab now includes **Change Member Site Password**.
- Changing the member password requires the existing `ADMIN_PASSWORD`.
- The Commissioner password itself is not changed.
- Until a separate member password has been saved, the existing Commissioner password acts as the initial login password. An optional `SITE_PASSWORD` Render environment variable may also be used as the bootstrap password.
- Existing logged-in sessions are not forcibly terminated when the password changes; they remain valid until logout/session expiration.
- The login background is an original football-stadium/field themed CSS design and does not use NFL/team logos.

### Database update required
Run `v2_10_private_login_schema_update.sql` in the Supabase SQL Editor before deploying V2.10.


## V2.10.2 — Visitor Count & Landing Footer

The private NFL Degenerates landing page now displays:
- Visitor Count
- Designed by
- Date / year

The visitor count increments only after a successful member login, rather than on every page refresh.

Commissioner → Test Lab includes **Visitor Count & Design Credit** controls. The commissioner can update the displayed designer credit and date/year using the existing Commissioner password.

This release uses the existing `site_settings` table from V2.10, so no additional Supabase migration is required.

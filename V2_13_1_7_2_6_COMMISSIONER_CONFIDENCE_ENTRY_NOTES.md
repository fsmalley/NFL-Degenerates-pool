# V2.13.1.7.2.6 — Commissioner Confidence Pick Entry

Built directly on V2.13.1.7.2.5.

## Changes
- Adds a Commissioner-only **Enter Picks for Player** panel to the Confidence Picks page.
- Commissioner can select an active member / established Confidence player and load that player's existing weekly pick sheet.
- Commissioner can save partial picks and tiebreaker values on that player's behalf.
- Normal individual-game kickoff locks remain enforced. Commissioner entry through this screen cannot add, change, or backfill a game after scheduled kickoff.
- Existing confidence-value uniqueness rules remain enforced across saved and locked games.
- Player-facing behavior is unchanged.
- No database migration or new environment variables are required.

## Validation
- Python source compiles successfully with `py_compile`.
- Full Flask runtime integration test was not run in the build container because Flask is not installed there.

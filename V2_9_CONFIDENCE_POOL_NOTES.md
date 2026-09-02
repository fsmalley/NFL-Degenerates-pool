# V2.9 — Confidence Pool

## Rules implemented
- One winner selection for every scheduled game.
- Confidence values 1 through N used exactly once, where N is the week's game count.
- Correct pick earns its confidence value.
- Incorrect pick earns 0.
- NFL tie earns 0.
- Final scheduled game combined score is the weekly tiebreaker.
- Weekly ties: highest points, then closest tiebreaker.
- Entire entry locks at kickoff of the first scheduled game.
- Picks remain private to the player before lock.

## Security / privacy
- Players use a separate Confidence PIN.
- PIN hashes are stored, not plaintext PINs.
- Public results hide picks before the weekly lock.
- Server validates every team, game, confidence value, and tiebreaker.

## Required migration
Run `confidence_v2_9_schema_update.sql` before deploying.

## Existing pools
No Draft or Survivor schema changes are required.

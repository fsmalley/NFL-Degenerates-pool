# V2.13.1.6 — Restore Players + Safe Placeholder Cleanup

This release corrects the V2.13.1.5 cleanup behavior.

## Safety change
Permanent deletion of unused Draft slots is disabled. The standings now hide only
obvious placeholder names such as `x2`, `x3`, or `Player 24` when they have no teams.
A real named player is never hidden merely because the roster is empty.

## Recovery
Commissioner Mode includes **Restore Mike P & Yong**.

Restored rosters:
- Mike P: LAR, LAC, CIN, DEN, NE, NO, CHI, NYG
- Yong: LAR, DET, CIN, MIA, NE, ARI, CAR, NYJ

The restore operation reuses an existing member account's prior `draft_player_id`
when possible and repairs that member-account link if a new Draft row ID is required.

No database migration or new environment variable is required.

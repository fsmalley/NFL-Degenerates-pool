# V2.13.1.4 — Draft Winning Margin Fix

Built directly from V2.13.1.3.

## Draft scoring rule
- Winning team: positive winning margin.
- Losing team: 0 points.
- Tie: 0 points.

Example:
Seattle 13, New England 10
- SEA = +3
- NE = 0
- Player owning both = +3

This change is limited to Draft Pool scoring. Stored game scores, winner/loser,
margin, ESPN refresh behavior, Survivor, and Confidence are unchanged.

No database migration, scheduler, Cron, or environment-variable change.

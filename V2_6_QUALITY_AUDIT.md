# V2.6 Quality Audit

Baseline: V2.5 Survivor Pick Visibility & Deadlines

## Corrected in V2.6

1. **Final-game scoring safeguard** — Production Draft and Survivor calculations now require an explicitly final/completed/closed game status. Live scores can no longer create a winner, margin, Survivor result, or Draft points.
2. **Survivor reveal privacy** — The public Season Board now masks both the team and any elimination caused by an unrevealed week's pick. Until reveal, it shows Submitted and preserves only elimination status from already-revealed weeks.
3. **Bye-week/direct API protection** — Survivor picks are validated server-side against the actual Week schedule. A valid NFL abbreviation is no longer enough if that team is not playing that week.
4. **Survivor player season scope** — Player lookup and creation now include the season and use the database's `(season, player_key)` unique key.
5. **PIN backward compatibility** — New PINs use Werkzeug password hashing, while existing legacy V2.x salt/digest PIN hashes remain verifiable.
6. **Draft tie ranking** — Production standings now use competition ranking for equal totals, e.g. 1, 1, 3.
7. **Health check coverage** — `/health` checks all core production tables needed by the two active pools.
8. **Code cleanup** — Removed duplicate helper definitions that accumulated during earlier version patches.

## Validation completed

- Python syntax compilation passed.
- Duplicate top-level Python function check passed: none remain.
- JavaScript syntax checks passed for all six templates.
- Targeted scoring tests passed for live-vs-final game handling, Survivor result behavior, Draft live-score exclusion, and tied standings.
- Confidence Pool navigation remains Coming Soon.

## No database change

V2.6 does not require a Supabase schema update beyond the migrations already used through V2.5.

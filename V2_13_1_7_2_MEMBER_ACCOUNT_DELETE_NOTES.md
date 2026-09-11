# V2.13.1.7.2 — Safe Member Account Delete

Built directly from the stable V2.13.1.7.1 lightweight-health-check baseline.

## Change
- Adds a **Delete Account** button to each non-Commissioner member card on the Commissioner/Test Lab page.
- Uses the existing `/api/admin/members` endpoint with `action: "delete"`; no new Flask route was added.
- Requires the Commissioner password and a browser confirmation before deletion.
- Server-side protection prevents deleting any account whose role is `COMMISSIONER`.
- Deletes only the selected row from `member_accounts`. Draft players, Survivor picks, Confidence picks, forum posts, and pool history are not deleted.
- The member list refreshes immediately after a successful deletion.

## Unchanged
- V2.13.1.7.1 lightweight `/health` endpoint remains unchanged.
- No database migration.
- No score-refresh/scheduler changes.
- No Draft/Survivor/Confidence scoring changes.

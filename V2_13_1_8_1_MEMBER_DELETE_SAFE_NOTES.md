# V2.13.1.8.1 — Safe Member Account Delete

Built directly from the known-good V2.13.1.7 release.

- Adds Delete Account to each non-Commissioner member card.
- Uses the existing `/api/admin/members` POST endpoint with `action:"delete"`.
- Requires the Commissioner password.
- Confirms display name + username before deletion.
- Deletes only the `member_accounts` row.
- Does not delete Draft, Survivor, Confidence, forum, or pool-history data.
- Commissioner-role accounts are protected from deletion.
- No new Flask route was added.
- No database migration or new environment variable is required.

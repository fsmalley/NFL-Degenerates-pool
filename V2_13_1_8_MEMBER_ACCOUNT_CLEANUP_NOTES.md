# V2.13.1.8 — Member Account Cleanup

Adds a safe per-account delete option to Existing Member Accounts.

Safety behavior:
- Deletes only the selected row from `member_accounts`.
- Does not delete Draft players, Survivor picks, Confidence picks, forum posts, or pool history.
- Commissioner-role accounts are blocked from deletion.
- Requires Commissioner password and a visible confirmation showing display name + username.
- Reloads the account list after successful deletion.

Also retires the one-time Mike P/Yong recovery tool now that both players were restored manually.

No database migration or new environment variable is required.

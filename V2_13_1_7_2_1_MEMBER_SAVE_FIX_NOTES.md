# V2.13.1.7.2.1 — Member Save Fix

Built directly from the stable V2.13.1.7.2 package.

- Fixes Commissioner > Existing Member Accounts > Save Account.
- Member updates now use a targeted Supabase PATCH for editable fields instead of upserting the complete member row.
- Adds immediate “Saving member account…” feedback and a Commissioner-password guard.
- Preserves the lightweight `/health` endpoint and safe Delete Account behavior.
- No database migration, environment-variable, score, Draft, Survivor, Confidence, or forum changes.

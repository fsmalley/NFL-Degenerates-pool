# V2.13.1.7 — Draft Member Query Fix

Fixes two member-management queries that incorrectly filtered `draft_players`
by a nonexistent `season` column, causing Supabase/PostgREST HTTP 400.

Preserves V2.13.1.6 recovery for Mike P and Yong, safe placeholder hiding,
disabled destructive cleanup, ESPN scoring refresh, and Draft scoring rules.

No database migration or new environment variable is required.

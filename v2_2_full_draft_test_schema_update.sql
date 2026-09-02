-- NFL Degenerates Pool V2.2 Full Draft Pool Test
-- Run once in Supabase SQL Editor before deploying V2.2.
-- This alters only the isolated test_draft_players table.

alter table public.test_draft_players add column if not exists team3 text;
alter table public.test_draft_players add column if not exists team4 text;
alter table public.test_draft_players add column if not exists team5 text;
alter table public.test_draft_players add column if not exists team6 text;
alter table public.test_draft_players add column if not exists team7 text;
alter table public.test_draft_players add column if not exists team8 text;

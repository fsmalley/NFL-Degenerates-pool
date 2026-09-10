-- NFL Degenerates V2.13.2
-- Automatic score refresh scheduler
--
-- BEFORE RUNNING:
-- 1. Add AUTO_SYNC_TOKEN in Render Environment.
-- 2. Replace PASTE_THE_SAME_AUTO_SYNC_TOKEN_HERE below with that exact token.

create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;

do $$
declare
  existing_job bigint;
begin
  select jobid into existing_job
  from cron.job
  where jobname = 'nfl-degenerates-auto-score-refresh'
  limit 1;

  if existing_job is not null then
    perform cron.unschedule(existing_job);
  end if;
end $$;

select vault.create_secret(
  'https://nfl-degenerates-pool.onrender.com/api/system/score-refresh',
  'nfl_degenerates_score_refresh_url'
)
where not exists (
  select 1 from vault.decrypted_secrets
  where name = 'nfl_degenerates_score_refresh_url'
);

select vault.create_secret(
  'PASTE_THE_SAME_AUTO_SYNC_TOKEN_HERE',
  'nfl_degenerates_score_refresh_token'
)
where not exists (
  select 1 from vault.decrypted_secrets
  where name = 'nfl_degenerates_score_refresh_token'
);

select cron.schedule(
  'nfl-degenerates-auto-score-refresh',
  '*/30 * * * *',
  $cron$
    select net.http_get(
      url := (
        select decrypted_secret
        from vault.decrypted_secrets
        where name = 'nfl_degenerates_score_refresh_url'
        limit 1
      ),
      headers := jsonb_build_object(
        'X-Auto-Sync-Token',
        (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'nfl_degenerates_score_refresh_token'
          limit 1
        )
      ),
      timeout_milliseconds := 120000
    );
  $cron$
);

-- Verify:
-- select jobid, jobname, schedule, active
-- from cron.job
-- where jobname = 'nfl-degenerates-auto-score-refresh';

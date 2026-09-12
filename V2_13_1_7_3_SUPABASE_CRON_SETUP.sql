-- V2.13.1.7.3 — Supabase Cron setup
-- Run only AFTER the new Render build is live and the endpoint has been tested.
--
-- Before running:
--   1) In Supabase, enable Cron (pg_cron) and pg_net if they are not already enabled.
--   2) Replace REPLACE_WITH_YOUR_AUTO_SYNC_TOKEN below with the SAME AUTO_SYNC_TOKEN used in Render.
--
-- This schedules one HTTPS POST every 5 minutes.

-- Remove an older job with this name if it exists.
select cron.unschedule(jobid)
from cron.job
where jobname = 'nfl-degenerates-auto-score-refresh';

select cron.schedule(
  'nfl-degenerates-auto-score-refresh',
  '*/5 * * * *',
  $$
  select net.http_post(
    url := 'https://nfl-degenerates-pool.onrender.com/api/auto-score-refresh',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Auto-Sync-Token', 'REPLACE_WITH_YOUR_AUTO_SYNC_TOKEN'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 60000
  ) as request_id;
  $$
);

-- Verify the job exists:
select jobid, jobname, schedule, active
from cron.job
where jobname = 'nfl-degenerates-auto-score-refresh';

-- MANUAL ONLY: run only after an explicit rollback decision.
SELECT cron.unschedule(jobid)
FROM cron.job
WHERE jobname = 'pr-d-e12-capture-every-minute';

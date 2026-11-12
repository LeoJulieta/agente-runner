-- SANDBOX CANDIDATE ONLY. Never apply to a live project from this branch.
-- Adds explicit YouTube publication and observation instants without changing
-- legacy rows or assuming youtube_video_id is the primary key.
ALTER TABLE public.youtube_shorts_log
    ADD COLUMN IF NOT EXISTS published_at timestamptz,
    ADD COLUMN IF NOT EXISTS sync_captured_at timestamptz;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'youtube_shorts_log_sync_capture_window_ck'
          AND conrelid = 'public.youtube_shorts_log'::regclass
    ) THEN
        ALTER TABLE public.youtube_shorts_log
            ADD CONSTRAINT youtube_shorts_log_sync_capture_window_ck
            CHECK (
                (published_at IS NULL AND sync_captured_at IS NULL)
                OR (
                    published_at IS NOT NULL
                    AND sync_captured_at IS NOT NULL
                    AND sync_captured_at >= published_at + interval '3 hours'
                    AND sync_captured_at <= published_at + interval '6 hours'
                )
            );
    END IF;
END;
$migration$;

-- CAS must identify the existing bigint row id AND its YouTube text identifier.
-- A successful first write changes views_primeras_3h from NULL; all competing
-- writers then affect zero rows. Legacy populated rows are intentionally kept.
CREATE INDEX IF NOT EXISTS youtube_shorts_log_sync_capture_pending_idx
    ON public.youtube_shorts_log (id)
    WHERE views_primeras_3h IS NULL;

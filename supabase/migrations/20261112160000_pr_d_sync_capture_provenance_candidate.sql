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
                    AND views_primeras_3h IS NOT NULL
                    AND views_primeras_3h >= 0
                    AND sync_captured_at >= published_at + interval '2 hours 55 minutes'
                    AND sync_captured_at <= published_at + interval '3 hours 5 minutes'
                )
            );
    END IF;
END;
$migration$;

-- Reusable compare-and-set operation. Both stable identifiers must match;
-- only an unpopulated metric/provenance row can be claimed exactly once.
CREATE OR REPLACE FUNCTION public.pr_d_capture_views_once(
    p_row_id bigint, p_youtube_video_id text, p_views integer,
    p_published_at timestamptz, p_sync_captured_at timestamptz
)
RETURNS boolean
LANGUAGE sql
AS $function$
    WITH changed AS (
        UPDATE public.youtube_shorts_log
        SET views_primeras_3h = p_views,
            published_at = p_published_at,
            sync_captured_at = p_sync_captured_at
        WHERE id = p_row_id
          AND youtube_video_id = p_youtube_video_id
          AND views_primeras_3h IS NULL
          AND published_at IS NULL
          AND sync_captured_at IS NULL
          AND p_views IS NOT NULL
          AND p_views >= 0
          AND p_published_at IS NOT NULL
          AND p_sync_captured_at >= p_published_at + interval '2 hours 55 minutes'
          AND p_sync_captured_at <= p_published_at + interval '3 hours 5 minutes'
        RETURNING id
    )
    SELECT EXISTS (SELECT 1 FROM changed);
$function$;

-- Least privilege: PostgreSQL grants EXECUTE on new functions to PUBLIC by default.
-- The capture RPC is an internal writer and must only be callable by the trusted runner role.
REVOKE ALL ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, integer, timestamptz, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pr_d_capture_views_once(
    bigint, text, integer, timestamptz, timestamptz
) TO service_role;

CREATE INDEX IF NOT EXISTS youtube_shorts_log_sync_capture_pending_idx
    ON public.youtube_shorts_log (id)
    WHERE views_primeras_3h IS NULL;

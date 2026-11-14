-- Applied to the connected production project as migration 20261114184047.
-- This migration does not modify rows or RLS policies.
-- It removes TRUNCATE from client-facing roles on current public tables and
-- prevents postgres-created public tables from granting table privileges to
-- anon/authenticated by default. service_role remains unchanged.
--
-- Note: Supabase's separate supabase_admin default ACL is not modified here.
-- Current application tables were verified to be owned by postgres.

REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES FROM anon, authenticated;

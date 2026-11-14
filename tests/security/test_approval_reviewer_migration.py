import os
import unittest
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "20261114190000_authenticated_approval_reviewer_flow.sql"
REVIEWER = UUID("11111111-2222-4333-8444-555555555555")
NON_REVIEWER = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


class ApprovalReviewerMigrationTests(unittest.TestCase):
    def test_authenticated_allowlist_and_atomic_review_rpc(self):
        database_url = os.environ["TEST_DATABASE_URL"]
        migration_sql = MIGRATION.read_text(encoding="utf-8")

        with psycopg.connect(database_url, autocommit=True) as db:
            db.execute("""
                DO $$ BEGIN CREATE ROLE anon NOLOGIN;
                EXCEPTION WHEN duplicate_object THEN NULL; END $$;
            """)
            db.execute("""
                DO $$ BEGIN CREATE ROLE authenticated NOLOGIN;
                EXCEPTION WHEN duplicate_object THEN NULL; END $$;
            """)
            db.execute("""
                DO $$ BEGIN CREATE ROLE service_role NOLOGIN BYPASSRLS;
                EXCEPTION WHEN duplicate_object THEN
                    ALTER ROLE service_role BYPASSRLS;
                END $$;
            """)

            db.execute("DROP TABLE IF EXISTS public.approval_reviewers CASCADE")
            db.execute("DROP FUNCTION IF EXISTS public.review_pending_approval(text,text)")
            db.execute("DROP TABLE IF EXISTS public.pending_approvals CASCADE")
            db.execute("DROP FUNCTION IF EXISTS auth.uid()")
            db.execute("DROP SCHEMA IF EXISTS auth CASCADE")
            db.execute("CREATE SCHEMA auth")
            db.execute("CREATE TABLE auth.users (id uuid PRIMARY KEY)")
            db.execute("""
                CREATE FUNCTION auth.uid() RETURNS uuid
                LANGUAGE sql STABLE
                AS $$
                  SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
                $$
            """)
            db.execute("GRANT USAGE ON SCHEMA auth TO authenticated")
            db.execute("GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated")
            db.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role")

            db.execute("""
                CREATE TABLE public.pending_approvals (
                    id text PRIMARY KEY,
                    title text NOT NULL,
                    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
                    status text NOT NULL DEFAULT 'pending',
                    resolved_at timestamptz
                )
            """)
            db.execute("ALTER TABLE public.pending_approvals ENABLE ROW LEVEL SECURITY")
            db.execute("""
                GRANT ALL PRIVILEGES ON TABLE public.pending_approvals
                TO anon, authenticated, service_role
            """)
            db.execute("""
                CREATE POLICY "Permitir lectura anon"
                ON public.pending_approvals FOR SELECT TO anon USING (true)
            """)
            db.execute("""
                CREATE POLICY anon_review_pending_approvals
                ON public.pending_approvals FOR UPDATE TO anon
                USING (status = 'pending')
                WITH CHECK (status IN ('approved','rejected') AND resolved_at IS NOT NULL)
            """)
            db.execute(
                "INSERT INTO auth.users(id) VALUES (%s), (%s)",
                (REVIEWER, NON_REVIEWER),
            )
            db.execute(
                "INSERT INTO public.pending_approvals(id,title,payload) VALUES ('APR-001','test','{}')"
            )

            db.execute(migration_sql)
            db.execute(
                "INSERT INTO public.approval_reviewers(user_id, active) VALUES (%s, true)",
                (REVIEWER,),
            )

            privileges = db.execute("""
                SELECT
                  has_table_privilege('anon','public.pending_approvals','SELECT'),
                  has_table_privilege('anon','public.pending_approvals','UPDATE'),
                  has_column_privilege('anon','public.pending_approvals','status','UPDATE'),
                  has_column_privilege('anon','public.pending_approvals','resolved_at','UPDATE'),
                  has_column_privilege('anon','public.pending_approvals','payload','UPDATE'),
                  has_table_privilege('authenticated','public.pending_approvals','SELECT'),
                  has_table_privilege('authenticated','public.pending_approvals','UPDATE'),
                  has_table_privilege('service_role','public.pending_approvals','UPDATE'),
                  has_function_privilege('anon','public.review_pending_approval(text,text)','EXECUTE'),
                  has_function_privilege('authenticated','public.review_pending_approval(text,text)','EXECUTE')
            """).fetchone()
            self.assertEqual(
                privileges,
                (False, False, False, False, False, True, False, True, False, True),
            )

            function_security = db.execute("""
                SELECT prosecdef, proconfig::text
                FROM pg_proc
                WHERE oid='public.review_pending_approval(text,text)'::regprocedure
            """).fetchone()
            self.assertTrue(function_security[0])
            self.assertIn("search_path=pg_catalog,public,auth", str(function_security[1]).replace(" ", ""))

            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (str(NON_REVIEWER),))
            self.assertEqual(
                db.execute("SELECT count(*) FROM public.pending_approvals").fetchone()[0],
                0,
            )
            with self.assertRaises(errors.InsufficientPrivilege):
                db.execute(
                    "SELECT public.review_pending_approval('APR-001','approved')"
                )
            db.execute("RESET ROLE")

            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (str(REVIEWER),))
            self.assertEqual(
                db.execute("SELECT count(*) FROM public.pending_approvals").fetchone()[0],
                1,
            )
            self.assertTrue(
                db.execute(
                    "SELECT public.review_pending_approval('APR-001','approved')"
                ).fetchone()[0]
            )
            self.assertFalse(
                db.execute(
                    "SELECT public.review_pending_approval('APR-001','rejected')"
                ).fetchone()[0]
            )
            status = db.execute(
                "SELECT status,resolved_at IS NOT NULL FROM public.pending_approvals WHERE id='APR-001'"
            ).fetchone()
            self.assertEqual(status, ("approved", True))
            db.execute("RESET ROLE")

            db.execute("SET ROLE anon")
            with self.assertRaises(errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pending_approvals")
            db.execute("RESET ROLE")


if __name__ == "__main__":
    unittest.main()

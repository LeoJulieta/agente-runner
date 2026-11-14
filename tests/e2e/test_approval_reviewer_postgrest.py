import json
import os
import urllib.error
import urllib.request
import unittest
from urllib.parse import quote

import psycopg


def http_json(url, *, method="GET", headers=None, body=None):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"message": raw[:500]}
        return error.code, payload


class SupabaseApprovalReviewerHttpTests(unittest.TestCase):
    def test_real_auth_jwt_rls_and_atomic_rpc(self):
        base_url = os.environ["SUPABASE_URL"].rstrip("/")
        anon_key = os.environ["SUPABASE_ANON_KEY"]
        service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        database_url = os.environ["TEST_DATABASE_URL"]

        reviewer_email = "reviewer-e2e@example.test"
        reviewer_password = "Local-Only-Reviewer-Password-93!"
        nonreviewer_email = "nonreviewer-e2e@example.test"
        nonreviewer_password = "Local-Only-NonReviewer-Password-93!"

        admin_headers = {
            "apikey": service_key,
            "Authorization": "Bearer " + service_key,
            "Content-Type": "application/json",
        }

        reviewer_status, reviewer_user = http_json(
            base_url + "/auth/v1/admin/users",
            method="POST",
            headers=admin_headers,
            body={
                "email": reviewer_email,
                "password": reviewer_password,
                "email_confirm": True,
            },
        )
        self.assertIn(reviewer_status, (200, 201), reviewer_user)
        reviewer_id = reviewer_user["id"]

        nonreviewer_status, nonreviewer_user = http_json(
            base_url + "/auth/v1/admin/users",
            method="POST",
            headers=admin_headers,
            body={
                "email": nonreviewer_email,
                "password": nonreviewer_password,
                "email_confirm": True,
            },
        )
        self.assertIn(nonreviewer_status, (200, 201), nonreviewer_user)

        with psycopg.connect(database_url, autocommit=True) as db:
            db.execute(
                "INSERT INTO public.approval_reviewers(user_id,active) VALUES (%s,true)",
                (reviewer_id,),
            )
            db.execute("""
                INSERT INTO public.pending_approvals(
                    id,title,payload,reasoning,type,status,created_at
                ) VALUES (
                    'APR-HTTP-001','E2E reviewer fixture','{}'::jsonb,
                    'fixture only','other','pending',clock_timestamp()
                )
            """)

        def sign_in(email, password):
            status, payload = http_json(
                base_url + "/auth/v1/token?grant_type=password",
                method="POST",
                headers={"apikey": anon_key, "Content-Type": "application/json"},
                body={"email": email, "password": password},
            )
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload.get("access_token"))
            return payload["access_token"]

        reviewer_token = sign_in(reviewer_email, reviewer_password)
        nonreviewer_token = sign_in(nonreviewer_email, nonreviewer_password)

        reviewer_headers = {
            "apikey": anon_key,
            "Authorization": "Bearer " + reviewer_token,
            "Content-Type": "application/json",
        }
        nonreviewer_headers = {
            "apikey": anon_key,
            "Authorization": "Bearer " + nonreviewer_token,
            "Content-Type": "application/json",
        }
        anon_headers = {
            "apikey": anon_key,
            "Content-Type": "application/json",
        }

        approvals_url = base_url + "/rest/v1/pending_approvals?select=id,status"
        status, rows = http_json(approvals_url, headers=reviewer_headers)
        self.assertEqual(status, 200, rows)
        self.assertEqual(rows, [{"id": "APR-HTTP-001", "status": "pending"}])

        status, rows = http_json(approvals_url, headers=nonreviewer_headers)
        self.assertEqual(status, 200, rows)
        self.assertEqual(rows, [])

        status, payload = http_json(approvals_url, headers=anon_headers)
        self.assertIn(status, (401, 403), payload)

        rpc_url = base_url + "/rest/v1/rpc/review_pending_approval"
        status, result = http_json(
            rpc_url,
            method="POST",
            headers=reviewer_headers,
            body={"p_approval_id": "APR-HTTP-001", "p_decision": "approved"},
        )
        self.assertEqual(status, 200, result)
        self.assertIs(result, True)

        status, result = http_json(
            rpc_url,
            method="POST",
            headers=reviewer_headers,
            body={"p_approval_id": "APR-HTTP-001", "p_decision": "rejected"},
        )
        self.assertEqual(status, 200, result)
        self.assertIs(result, False)

        status, payload = http_json(
            rpc_url,
            method="POST",
            headers=nonreviewer_headers,
            body={"p_approval_id": "APR-HTTP-001", "p_decision": "approved"},
        )
        self.assertIn(status, (400, 401, 403), payload)

        status, payload = http_json(
            rpc_url,
            method="POST",
            headers=anon_headers,
            body={"p_approval_id": "APR-HTTP-001", "p_decision": "approved"},
        )
        self.assertIn(status, (401, 403), payload)

        status, payload = http_json(
            base_url + "/rest/v1/pending_approvals?id=eq.APR-HTTP-001",
            method="PATCH",
            headers=reviewer_headers | {"Prefer": "return=representation"},
            body={"status": "rejected", "resolved_at": None},
        )
        self.assertIn(status, (401, 403), payload)

        with psycopg.connect(database_url) as db:
            final_row = db.execute(
                "SELECT status,resolved_at IS NOT NULL FROM public.pending_approvals WHERE id='APR-HTTP-001'"
            ).fetchone()
        self.assertEqual(final_row, ("approved", True))


if __name__ == "__main__":
    unittest.main()

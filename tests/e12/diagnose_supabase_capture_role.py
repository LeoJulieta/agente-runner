from __future__ import annotations

import json
import os

import psycopg


def memberships(conn, role_oid: int):
    return conn.execute(
        """
        SELECT granted.rolname AS granted_role, member.rolname AS member_role
        FROM pg_auth_members m
        JOIN pg_roles granted ON granted.oid = m.roleid
        JOIN pg_roles member ON member.oid = m.member
        WHERE m.roleid = %s OR m.member = %s
        ORDER BY granted.rolname, member.rolname
        """,
        (role_oid, role_oid),
    ).fetchall()


def main() -> None:
    with psycopg.connect(os.environ["E12_GATEWAY_DB_URL"], autocommit=True) as conn:
        existing = conn.execute(
            "SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = 'pr_d_capture_owner'"
        ).fetchone()
        if existing:
            schema = conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspowner = %s ORDER BY nspname",
                (existing[0],),
            ).fetchall()
            print(json.dumps({
                "state": "preexisting",
                "attributes": existing[1:],
                "memberships": memberships(conn, existing[0]),
                "owned_schemas": schema,
            }, default=str), flush=True)
            return

        conn.execute("""
            CREATE ROLE pr_d_capture_owner
                NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOINHERIT NOREPLICATION NOBYPASSRLS
        """)
        probe = conn.execute(
            "SELECT oid FROM pg_roles WHERE rolname = 'pr_d_capture_owner'"
        ).fetchone()[0]
        edges = memberships(conn, probe)
        print(json.dumps({
            "state": "created_by_probe",
            "memberships": edges,
        }, default=str), flush=True)
        if edges:
            raise RuntimeError("local Supabase automatically attached memberships to the capture-owner role")
        conn.execute("DROP ROLE pr_d_capture_owner")
        print("PASS: capture-owner role can be created without memberships in local Supabase", flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os

import psycopg


def memberships(conn, role_oid: int):
    return conn.execute(
        """
        SELECT granted.rolname AS granted_role,
               member.rolname AS member_role,
               m.admin_option
        FROM pg_auth_members m
        JOIN pg_roles granted ON granted.oid = m.roleid
        JOIN pg_roles member ON member.oid = m.member
        WHERE m.roleid = %s OR m.member = %s
        ORDER BY granted.rolname, member.rolname
        """,
        (role_oid, role_oid),
    ).fetchall()


def validate(conn, role_oid: int) -> None:
    edges = memberships(conn, role_oid)
    unexpected = [
        edge for edge in edges
        if not (edge[0] == "pr_d_capture_owner" and edge[1] == "postgres")
    ]
    if unexpected:
        raise RuntimeError(f"untrusted capture-owner role memberships: {unexpected}")
    print(json.dumps({
        "capture_owner_memberships": edges,
        "allowed_admin_membership": "postgres only",
    }, default=str), flush=True)


def main() -> None:
    with psycopg.connect(os.environ["E12_GATEWAY_DB_URL"], autocommit=True) as conn:
        existing = conn.execute(
            """
            SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolinherit, rolreplication, rolbypassrls
            FROM pg_roles WHERE rolname = 'pr_d_capture_owner'
            """
        ).fetchone()
        if existing is None:
            conn.execute("""
                CREATE ROLE pr_d_capture_owner
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS
            """)
            existing = conn.execute(
                """
                SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                       rolinherit, rolreplication, rolbypassrls
                FROM pg_roles WHERE rolname = 'pr_d_capture_owner'
                """
            ).fetchone()

        assert existing is not None
        expected_attributes = (False, False, False, False, False, False, False)
        assert existing[1:] == expected_attributes, {
            "actual_attributes": existing[1:],
            "expected_attributes": expected_attributes,
        }
        validate(conn, existing[0])
        print(
            "PASS: local Supabase capture-owner role has safe attributes; "
            "only trusted postgres admin membership is permitted",
            flush=True,
        )


if __name__ == "__main__":
    main()

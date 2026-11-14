from __future__ import annotations

import base64
import os

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_key_b64 = base64.b64encode(private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )).decode("ascii")
    public_key_b64 = base64.b64encode(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode("ascii")
    hmac_secret = os.urandom(32)
    hmac_secret_b64 = base64.b64encode(hmac_secret).decode("ascii")
    key_id = "e12-supabase-gateway-e2e-key"

    with psycopg.connect(os.environ["E12_GATEWAY_DB_URL"], autocommit=True) as conn:
        conn.execute("SET ROLE pr_d_capture_owner")
        try:
            conn.execute(
                """
                INSERT INTO pr_d_internal.e12_collector_key_registry(
                    key_id, algorithm, public_key_spki_base64, hmac_secret, status
                ) VALUES (%s, 'Ed25519', %s, %s, 'active')
                """,
                (key_id, public_key_b64, hmac_secret),
            )
        finally:
            conn.execute("RESET ROLE")
        conn.execute(
            """
            INSERT INTO public.youtube_shorts_log(
                id, youtube_video_id, status, created_at
            ) VALUES (
                4, 'e12-supabase-gateway-video', 'published',
                clock_timestamp() - interval '4 hours'
            )
            """
        )
        conn.execute("NOTIFY pgrst, 'reload schema'")

    cron_secret = "e12-local-gateway-cron-hmac-secret-at-least-32-bytes"
    values = {
        "E12_GATEWAY_CRON_SECRET": cron_secret,
        "E12_GATEWAY_PRIVATE_KEY_PKCS8_B64": private_key_b64,
        "E12_GATEWAY_PUBLIC_KEY_SPKI_B64": public_key_b64,
        "E12_GATEWAY_HMAC_SECRET_B64": hmac_secret_b64,
    }
    for name in (
        "E12_GATEWAY_CRON_SECRET",
        "E12_GATEWAY_PRIVATE_KEY_PKCS8_B64",
        "E12_GATEWAY_HMAC_SECRET_B64",
    ):
        print(f"::add-mask::{values[name]}", flush=True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")

    print("PASS: ephemeral E12 attestation key and candidate registered in local Supabase DB")


if __name__ == "__main__":
    main()

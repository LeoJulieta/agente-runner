from __future__ import annotations

import os
import shlex
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, separator, raw_value = line.partition("=")
        if not separator:
            continue
        parsed = shlex.split(raw_value, posix=True)
        values[key.strip()] = parsed[0] if parsed else ""
    return values


def main() -> None:
    values = parse_env_file(Path(os.environ["SUPABASE_STATUS_ENV_FILE"]))
    api_url = values.get("API_URL") or values.get("SUPABASE_URL")
    db_url = values.get("DB_URL") or values.get("SUPABASE_DB_URL")
    secret_key = values.get("SECRET_KEY") or values.get("SUPABASE_SECRET_KEY")
    publishable_key = values.get("PUBLISHABLE_KEY") or values.get("SUPABASE_PUBLISHABLE_KEY")
    if not all((api_url, db_url, secret_key, publishable_key)):
        raise RuntimeError("local Supabase status is missing API_URL, DB_URL, SECRET_KEY or PUBLISHABLE_KEY")
    if not secret_key.startswith("sb_secret_") or not publishable_key.startswith("sb_publishable_"):
        raise RuntimeError("local Supabase CLI did not provide modern sb_secret_/sb_publishable_ keys")

    values_to_export = {
        "E12_GATEWAY_API_URL": api_url,
        "E12_GATEWAY_DB_URL": db_url,
        "E12_GATEWAY_SECRET_KEY": secret_key,
        "E12_GATEWAY_PUBLISHABLE_KEY": publishable_key,
    }
    print(f"::add-mask::{secret_key}", flush=True)
    for name, value in values_to_export.items():
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")
    print("PASS: local Supabase modern API key prefixes and connection endpoints validated")


if __name__ == "__main__":
    main()

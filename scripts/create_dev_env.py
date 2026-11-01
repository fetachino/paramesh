"""Create local development credentials without printing or overwriting secrets."""

import argparse
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operations", action="store_true", help="Add local demo exporter settings"
    )
    arguments = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / ".env"
    names = (
        "PARAMESH_RPC_TOKEN",
        "PARAMESH_ADMIN_TOKEN",
        "PARAMESH_S3_ACCESS_KEY",
        "PARAMESH_S3_SECRET_KEY",
        "PARAMESH_NATS_TOKEN",
        "PARAMESH_GRAFANA_PASSWORD",
        "PARAMESH_DASHBOARD_PASSWORD",
    )
    defaults = {}
    if arguments.operations:
        defaults = {
            "PARAMESH_NATS_URL": "nats://nats:4222",
            "PARAMESH_OTLP_ENDPOINT": "http://tempo:4318/v1/traces",
            "PARAMESH_TRACE_SAMPLE_RATIO": "1",
            "PARAMESH_STEPS": "1000",
            "PARAMESH_STEP_DELAY": "0.05",
        }
        names += tuple(defaults)
    prefix = ""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        previous = path.read_text()
        existing = {line.split("=", 1)[0] for line in previous.splitlines() if "=" in line}
        prefix = "\n" if previous and not previous.endswith("\n") else ""
        names = tuple(name for name in names if name not in existing)
        if not names:
            print("Using existing .env; credentials were not overwritten.")
            return
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(prefix)
        for name in names:
            stream.write(f"{name}={defaults.get(name) or secrets.token_urlsafe(32)}\n")
    print("Added missing random service credentials; existing values were preserved.")


if __name__ == "__main__":
    main()

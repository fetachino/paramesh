"""Verify disposable PostgreSQL streaming replication and promotion with Docker."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

IMAGE = "postgres:17-alpine"


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], check=check, text=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip()[-500:] if error.stderr else "no diagnostic"
        raise RuntimeError(f"docker {args[0]} failed: {detail}") from None


def sql(container: str, password: str, statement: str) -> str:
    result = docker(
        "exec",
        "-e",
        f"PGPASSWORD={password}",
        container,
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-At",
        "-c",
        statement,
    )
    return result.stdout.strip()


def wait_for(
    container: str, password: str, statement: str, expected: str, timeout: float = 60
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = docker(
            "exec",
            "-e",
            f"PGPASSWORD={password}",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-At",
            "-c",
            statement,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == expected:
            return result.stdout.strip()
        time.sleep(1)
    raise TimeoutError(f"{container} did not reach {expected!r}: {statement}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suffix = uuid.uuid4().hex[:10]
    network = f"paramesh-pg-ha-{suffix}"
    primary = f"{network}-primary"
    standby = f"{network}-standby"
    primary_volume = f"{network}-primary-data"
    standby_volume = f"{network}-standby-data"
    password = secrets.token_urlsafe(24)
    replication_password = secrets.token_urlsafe(24)
    started = datetime.now(UTC).isoformat()
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "running",
        "image": IMAGE,
        "started_at": started,
        "topology": {"primary": primary, "standby": standby, "replication": "streaming"},
    }
    try:
        docker("network", "create", network)
        docker("volume", "create", primary_volume)
        docker("volume", "create", standby_volume)
        docker(
            "run",
            "-d",
            "--name",
            primary,
            "--network",
            network,
            "--network-alias",
            "primary",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-v",
            f"{primary_volume}:/var/lib/postgresql/data",
            IMAGE,
            "postgres",
            "-c",
            "wal_level=replica",
            "-c",
            "max_wal_senders=10",
            "-c",
            "wal_keep_size=64MB",
        )
        wait_for(primary, password, "SELECT 1", "1")
        sql(
            primary,
            password,
            f"CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '{replication_password}'",
        )
        docker(
            "exec",
            primary,
            "sh",
            "-c",
            "printf '%s\\n' 'host replication replicator 0.0.0.0/0 scram-sha-256' "
            ">> /var/lib/postgresql/data/pg_hba.conf",
        )
        docker("restart", primary)
        wait_for(primary, password, "SELECT 1", "1")
        docker(
            "run",
            "--rm",
            "--network",
            network,
            "-e",
            f"PGPASSWORD={replication_password}",
            "-v",
            f"{standby_volume}:/var/lib/postgresql/data",
            IMAGE,
            "pg_basebackup",
            "-h",
            "primary",
            "-D",
            "/var/lib/postgresql/data",
            "-U",
            "replicator",
            "-Fp",
            "-Xs",
            "-P",
            "-R",
            "--checkpoint=fast",
        )
        docker(
            "run",
            "-d",
            "--name",
            standby,
            "--network",
            network,
            "--network-alias",
            "standby",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-v",
            f"{standby_volume}:/var/lib/postgresql/data",
            IMAGE,
            "postgres",
        )
        wait_for(standby, password, "SELECT pg_is_in_recovery()", "t")
        sql(
            primary,
            password,
            "CREATE TABLE replication_probe (id integer PRIMARY KEY, note text NOT NULL)",
        )
        sql(primary, password, "INSERT INTO replication_probe VALUES (1, 'before-failover')")
        wait_for(standby, password, "SELECT count(*) FROM replication_probe", "1")
        result["before_failover"] = {
            "primary_recovery": sql(primary, password, "SELECT pg_is_in_recovery()"),
            "standby_recovery": sql(standby, password, "SELECT pg_is_in_recovery()"),
            "standby_rows": sql(standby, password, "SELECT count(*) FROM replication_probe"),
            "replication_state": sql(
                primary,
                password,
                "SELECT coalesce((SELECT state FROM pg_stat_replication LIMIT 1), 'missing')",
            ),
        }
        docker("stop", primary)
        docker(
            "exec",
            "-u",
            "postgres",
            standby,
            "pg_ctl",
            "promote",
            "-D",
            "/var/lib/postgresql/data",
            "-w",
        )
        wait_for(standby, password, "SELECT pg_is_in_recovery()", "f")
        sql(standby, password, "INSERT INTO replication_probe VALUES (2, 'after-promotion')")
        result["after_promotion"] = {
            "promoted_recovery": sql(standby, password, "SELECT pg_is_in_recovery()"),
            "rows": sql(standby, password, "SELECT count(*) FROM replication_probe"),
            "notes": sql(
                standby,
                password,
                "SELECT string_agg(note, ',' ORDER BY id) FROM replication_probe",
            ),
        }
        result["status"] = "complete"
    except BaseException as error:
        result.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        for container in (primary, standby):
            docker("rm", "-f", container, check=False)
        for volume in (primary_volume, standby_volume):
            docker("volume", "rm", volume, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()

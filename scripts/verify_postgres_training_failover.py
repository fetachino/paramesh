"""Verify ParamMesh training and checkpoint continuity across PostgreSQL failover."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import secrets
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Keep this runnable as ``python scripts/...`` as well as ``python -m``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_postgres_replication import docker, sql, wait_for


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def train_process(address: str, worker_id: str, steps: int, delay: float, queue: Any) -> None:
    from paramesh.worker import train_worker

    try:
        queue.put(
            {
                "worker_id": worker_id,
                "result": train_worker(address, worker_id, steps, timeout=3, step_delay=delay),
            }
        )
    except BaseException as error:
        queue.put({"worker_id": worker_id, "error": f"{type(error).__name__}: {error}"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suffix = secrets.token_hex(5)
    network = f"paramesh-pg-training-{suffix}"
    primary = f"{network}-primary"
    standby = f"{network}-standby"
    promoted = f"{network}-promoted"
    primary_volume = f"{network}-primary-data"
    standby_volume = f"{network}-standby-data"
    password = secrets.token_urlsafe(24)
    replication_password = secrets.token_urlsafe(24)
    host_db_port = free_port()
    coordinator_port = free_port()
    result: dict[str, object] = {"schema_version": 1, "status": "running"}
    coordinator_server = None
    coordinator_store = None
    shard_servers: list[Any] = []
    shard_stores: list[Any] = []
    workers: list[mp.Process] = []
    queue: Any = None
    try:
        from paramesh.checkpoint import export_online_checkpoint
        from paramesh.rpc import training_pb2 as pb
        from paramesh.rpc import training_pb2_grpc as rpc
        from paramesh.security import open_channel
        from paramesh.services import coordinator_server as make_coordinator_server
        from paramesh.services import managed_coordinator, shard_server
        from paramesh.shard import ParameterShard
        from paramesh.state import StateDB
        from paramesh.storage import LocalStore
        from paramesh.tensors import partition
        from paramesh.workload import bundled_workload, parameters_for

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
            "-p",
            f"127.0.0.1:{host_db_port}:5432",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-v",
            f"{primary_volume}:/var/lib/postgresql/data",
            "postgres:17-alpine",
            "postgres",
            "-c",
            "wal_level=replica",
            "-c",
            "max_wal_senders=10",
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
            "printf '%s\\n' 'host replication replicator 0.0.0.0/0 "
            "scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf",
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
            "postgres:17-alpine",
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
            "postgres:17-alpine",
            "postgres",
        )
        wait_for(standby, password, "SELECT pg_is_in_recovery()", "t")

        workload = bundled_workload(8)
        values = parameters_for(workload)
        settings = pb.RunConfig(
            run_id=f"postgres-ha-{suffix}",
            mode=pb.SYNCHRONOUS,
            shard_endpoints=[f"127.0.0.1:{free_port()}" for _ in range(2)],
            worker_ids=["worker-0", "worker-1"],
            learning_rate=0.05,
            max_staleness=1,
            barrier_timeout_seconds=15,
        )
        with tempfile.TemporaryDirectory(
            prefix="paramesh-pg-training-", ignore_cleanup_errors=True
        ) as temporary:
            root = Path(temporary)
            ownership = partition(values, 2)
            for index in range(2):
                store = StateDB(root / f"shard-{index}.sqlite")
                shard_stores.append(store)
                shard = ParameterShard(
                    settings,
                    {name: value for name, value in values.items() if ownership[name] == index},
                    state=store,
                )
                server, port = shard_server(shard, settings.shard_endpoints[index])
                server.start()
                shard_servers.append(server)
                settings.shard_endpoints[index] = f"127.0.0.1:{port}"

            from paramesh.postgres_state import PostgresStateDB

            coordinator_store = PostgresStateDB(
                f"postgresql://postgres:{password}@127.0.0.1:{host_db_port}/postgres",
                lock_name=f"training-{suffix}",
            )
            coordinator = managed_coordinator(
                settings, state=coordinator_store, suspect_after=1, unavailable_after=3
            )
            coordinator_server, port = make_coordinator_server(
                coordinator, f"127.0.0.1:{coordinator_port}"
            )
            coordinator_server.start()
            queue = mp.get_context("spawn").Queue()
            for worker_id in settings.worker_ids:
                process = mp.get_context("spawn").Process(
                    target=train_process,
                    args=(f"127.0.0.1:{coordinator_port}", worker_id, 80, 1.0, queue),
                )
                process.start()
                workers.append(process)

            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                states = coordinator.status().workers
                if len(states) == 2 and min(item.step for item in states) >= 3:
                    break
                time.sleep(0.2)
            before = {item.worker_id: item.step for item in coordinator.status().workers}
            if min(before.values(), default=0) < 3:
                result["observed_workers"] = before
                result["worker_exit_codes"] = [process.exitcode for process in workers]
                for process in workers:
                    process.join(timeout=1)
                if queue is not None:
                    messages = []
                    while not queue.empty():
                        messages.append(queue.get())
                    result["worker_messages"] = messages
                raise TimeoutError("workers did not enter active training before failover")

            coordinator_server.stop(0).wait()
            coordinator_store.close()
            coordinator_server = None
            coordinator_store = None
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
            docker("stop", standby)
            docker("rm", standby)
            docker(
                "run",
                "-d",
                "--name",
                promoted,
                "--network",
                network,
                "-p",
                f"127.0.0.1:{host_db_port}:5432",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-v",
                f"{standby_volume}:/var/lib/postgresql/data",
                "postgres:17-alpine",
                "postgres",
            )
            wait_for(promoted, password, "SELECT pg_is_in_recovery()", "f")

            coordinator_store = PostgresStateDB(
                f"postgresql://postgres:{password}@127.0.0.1:{host_db_port}/postgres",
                lock_name=f"training-{suffix}",
            )
            replacement = managed_coordinator(
                settings, state=coordinator_store, suspect_after=1, unavailable_after=3
            )
            coordinator_server, _ = make_coordinator_server(
                replacement, f"127.0.0.1:{coordinator_port}"
            )
            coordinator_server.start()

            # Replacement coordinators must fence the persisted generations before
            # workers can resume an in-flight synchronous barrier.
            for worker_id in settings.worker_ids:
                replacement.register(worker_id, 1)

            checkpoint_root = root / "checkpoint"
            checkpoint_store = LocalStore(checkpoint_root)
            checkpoint_error = None
            for _ in range(30):
                try:
                    checkpoint = export_online_checkpoint(
                        f"127.0.0.1:{coordinator_port}",
                        checkpoint_store,
                        "ha-after-failover",
                        None,
                        timeout=10,
                    )
                    break
                except Exception as error:
                    checkpoint_error = f"{type(error).__name__}: {error}"
                    time.sleep(1)
            else:
                raise TimeoutError(
                    "workers did not reach a checkpoint-safe lease after promotion: "
                    f"{checkpoint_error}"
                )
            for process in workers:
                process.join(timeout=90)
            messages = [queue.get(timeout=5) for _ in workers]
            final = replacement.status()
            shard_versions = []
            for endpoint in settings.shard_endpoints:
                with open_channel(endpoint, None) as channel:
                    progress = rpc.ParameterShardStub(channel).GetProgress(
                        pb.PullRequest(run_id=settings.run_id), timeout=5
                    )
                shard_versions.append(progress.version)
            result.update(
                status="complete",
                source="local-docker-postgres-17",
                before_failover=before,
                after_failover={item.worker_id: item.step for item in final.workers},
                recovered_workers=[
                    {"worker_id": item.worker_id, "health": item.health, "step": item.step}
                    for item in final.workers
                ],
                worker_messages=messages,
                shard_versions=shard_versions,
                checkpoint={
                    "id": "ha-after-failover",
                    "global_step": checkpoint["global_step"],
                    "shard_versions": checkpoint["shard_versions"],
                },
            )
    except BaseException as error:
        result.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        if coordinator_server is not None:
            coordinator_server.stop(0).wait()
        if coordinator_store is not None:
            coordinator_store.close()
        for process in workers:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        for server in shard_servers:
            server.stop(0).wait()
        for store in shard_stores:
            store.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
        for container in (primary, standby, promoted):
            docker("rm", "-f", container, check=False)
        for volume in (primary_volume, standby_volume):
            docker("volume", "rm", volume, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    main()

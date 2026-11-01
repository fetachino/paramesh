"""Command-line entry point."""

import argparse
import json
import os
import re
import signal
from importlib.metadata import version
from pathlib import Path

from google.protobuf.json_format import MessageToDict, Parse

from paramesh import events, telemetry
from paramesh.config import validate_config
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.tensors import partition


def _load(path: Path) -> pb.RunConfig:
    config = pb.RunConfig()
    Parse(path.read_text(encoding="utf-8"), config)
    validate_config(config)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(prog="paramesh")
    parser.add_argument("--version", action="version", version=version("paramesh"))
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="Run independent local processes and a correctness check"
    )
    demo.add_argument("--mode", choices=["sync", "async", "bounded"], default="sync")
    demo.add_argument("--workers", type=int, default=2)
    demo.add_argument("--shards", type=int, default=2)
    demo.add_argument("--steps", type=int, default=20)
    demo.add_argument("--output", type=Path, default=Path("artifacts/demo.json"))
    demo.add_argument("--failure", choices=["worker", "shard"], default=None)
    for name in ("coordinator", "shard"):
        service = commands.add_parser(name)
        service.add_argument("--config", type=Path, required=True)
        service.add_argument("--bind", default=None)
        service.add_argument("--state-dir", type=Path, default=Path("state"))
        if name == "coordinator":
            service.add_argument("--suspect-after", type=float, default=5)
            service.add_argument("--unavailable-after", type=float, default=15)
        if name == "shard":
            service.add_argument("--index", type=int, required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--coordinator", default="127.0.0.1:50050")
    worker.add_argument("--id", required=True)
    worker.add_argument("--steps", type=int, default=20)
    worker.add_argument("--state-dir", type=Path, default=Path("state"))
    worker.add_argument("--step-delay", type=float, default=0)
    status = commands.add_parser("status")
    status.add_argument("--coordinator", default="127.0.0.1:50050")
    check = commands.add_parser("check-shard")
    check.add_argument("--address", required=True)
    check.add_argument("--run-id", required=True)
    checkpoint = commands.add_parser("checkpoint", help="Export/restore an offline whole run")
    checkpoint.add_argument("action", choices=["export", "restore", "install"])
    checkpoint.add_argument("--id", required=True)
    checkpoint.add_argument("--state-dir", type=Path, required=True)
    checkpoint.add_argument("--store", type=Path, default=Path("checkpoints"))
    checkpoint.add_argument("--s3-endpoint")
    checkpoint.add_argument("--bucket")
    args = parser.parse_args()
    if (
        args.command in ("coordinator", "shard", "worker")
        and (args.state_dir / ".restore-incomplete").exists()
    ):
        parser.error("Checkpoint installation is incomplete; services must remain stopped")
    if args.command in ("coordinator", "shard", "worker", "checkpoint"):
        role = args.id if args.command == "worker" else args.command
        if args.command == "shard":
            role = f"shard-{args.index}"
        telemetry.start(role)
    security = (
        RpcSecurity.from_environment() if args.command not in ("demo", "checkpoint") else None
    )
    if args.command == "checkpoint":
        from paramesh.checkpoint import export_checkpoint, install_checkpoint, restore_checkpoint
        from paramesh.storage import LocalStore, ObjectStore, S3Store

        store: ObjectStore
        if args.s3_endpoint:
            store = S3Store(
                args.s3_endpoint,
                args.bucket or "",
                os.environ.get("PARAMESH_S3_ACCESS_KEY", ""),
                os.environ.get("PARAMESH_S3_SECRET_KEY", ""),
            )
        else:
            if args.bucket:
                parser.error("--bucket requires --s3-endpoint")
            store = LocalStore(args.store)
        if args.action == "export":
            report = export_checkpoint(args.state_dir, store, args.id)
        elif args.action == "install":
            report = install_checkpoint(store, args.id, args.state_dir)
        else:
            report = restore_checkpoint(store, args.id, args.state_dir)
        print(json.dumps(report, indent=2))
    elif args.command == "demo":
        from paramesh.demo import run_demo

        report = run_demo(
            mode=args.mode,
            workers=args.workers,
            shards=args.shards,
            steps=args.steps,
            output=args.output,
            failure=args.failure,
        )
        print(
            json.dumps(
                {key: value for key, value in report.items() if key != "worker_results"}, indent=2
            )
        )
    elif args.command == "worker":
        from paramesh.worker import train_worker

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.id):
            parser.error("--id must be a safe worker identifier")
        storage = StateDB(args.state_dir / f"{args.id}.sqlite")
        try:
            print(
                json.dumps(
                    train_worker(
                        args.coordinator,
                        args.id,
                        args.steps,
                        state=storage,
                        step_delay=args.step_delay,
                        security=security,
                    )
                )
            )
        finally:
            storage.close()
    elif args.command == "status":
        with open_channel(args.coordinator, security) as channel:
            state = rpc.CoordinatorStub(channel).GetStatus(pb.Empty(), timeout=3)
            print(json.dumps(MessageToDict(state, preserving_proto_field_name=True), indent=2))
    elif args.command == "check-shard":
        with open_channel(args.address, security) as channel:
            rpc.ParameterShardStub(channel).PullParameters(
                pb.PullRequest(run_id=args.run_id), timeout=3
            )
    else:
        config = _load(args.config)
        assert security is not None
        security.require_admin()
        if args.command == "coordinator":
            storage = StateDB(args.state_dir / "coordinator.sqlite")
            coordinator = managed_coordinator(
                config,
                state=storage,
                suspect_after=args.suspect_after,
                unavailable_after=args.unavailable_after,
                security=security,
            )
            if telemetry.active is not None:

                def coordinator_metrics() -> None:
                    current = coordinator.status()
                    telemetry.set_value("global_step", current.global_step)
                    telemetry.set_value(
                        "active_workers", sum(item.health == "healthy" for item in current.workers)
                    )
                    for item in current.workers:
                        labels = {"worker_id": item.worker_id}
                        telemetry.set_value("worker_step", item.step, **labels)
                        telemetry.set_value("worker_version", item.parameter_version, **labels)
                        telemetry.set_value(
                            "worker_available", int(item.health == "healthy"), **labels
                        )
                        telemetry.set_value("worker_generation", item.generation, **labels)
                        telemetry.set_value(
                            "heartbeat_age_seconds", item.heartbeat_age_seconds, **labels
                        )

                telemetry.active.probes.append(coordinator_metrics)
            server, port = coordinator_server(
                coordinator, args.bind or "127.0.0.1:50050", security=security
            )
        else:
            from paramesh.workload import parameters

            if not 0 <= args.index < len(config.shard_endpoints):
                parser.error("--index must identify a configured shard")
            values = parameters()
            owners = partition(values, len(config.shard_endpoints))
            storage = StateDB(args.state_dir / f"shard-{args.index}.sqlite")
            restored = storage.get("shard") is not None
            shard = ParameterShard(
                config, {k: v for k, v in values.items() if owners[k] == args.index}, state=storage
            )
            server, port = shard_server(
                shard, args.bind or config.shard_endpoints[args.index], security=security
            )
            if telemetry.active is not None:

                def shard_metrics() -> None:
                    with shard.condition:
                        telemetry.set_value("shard_version", shard.version)
                        telemetry.set_value("pending_workers", len(shard.pending))
                        for name, receipt in shard.receipts.items():
                            telemetry.set_value("staleness", receipt.staleness, worker_id=name)

                telemetry.active.probes.append(shard_metrics)
        server.start()
        if args.command == "shard" and restored:
            events.emit("shard_restored", run_id=config.run_id, version=shard.version)
        signal.signal(signal.SIGTERM, lambda signum, frame: server.stop(3))
        print(
            json.dumps(
                {
                    "event": "service_started",
                    "service": args.command,
                    "run_id": config.run_id,
                    "port": port,
                }
            ),
            flush=True,
        )
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(3).wait()
            storage.close()


if __name__ == "__main__":
    main()

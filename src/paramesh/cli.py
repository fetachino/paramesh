"""Command-line entry point."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

import grpc
from google.protobuf.json_format import MessageToDict, Parse

from paramesh.config import validate_config
from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.services import CHANNEL_OPTIONS, coordinator_server, shard_server
from paramesh.shard import ParameterShard
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
    for name in ("coordinator", "shard"):
        service = commands.add_parser(name)
        service.add_argument("--config", type=Path, required=True)
        service.add_argument("--bind", default=None)
        if name == "shard":
            service.add_argument("--index", type=int, required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--coordinator", default="127.0.0.1:50050")
    worker.add_argument("--id", required=True)
    worker.add_argument("--steps", type=int, default=20)
    status = commands.add_parser("status")
    status.add_argument("--coordinator", default="127.0.0.1:50050")
    check = commands.add_parser("check-shard")
    check.add_argument("--address", required=True)
    check.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.command == "demo":
        from paramesh.demo import run_demo

        report = run_demo(
            mode=args.mode,
            workers=args.workers,
            shards=args.shards,
            steps=args.steps,
            output=args.output,
        )
        print(
            json.dumps(
                {key: value for key, value in report.items() if key != "worker_results"}, indent=2
            )
        )
    elif args.command == "worker":
        from paramesh.worker import train_worker

        print(json.dumps(train_worker(args.coordinator, args.id, args.steps)))
    elif args.command == "status":
        with grpc.insecure_channel(args.coordinator, options=CHANNEL_OPTIONS) as channel:
            state = rpc.CoordinatorStub(channel).GetStatus(pb.Empty(), timeout=3)
            print(json.dumps(MessageToDict(state, preserving_proto_field_name=True), indent=2))
    elif args.command == "check-shard":
        with grpc.insecure_channel(args.address, options=CHANNEL_OPTIONS) as channel:
            rpc.ParameterShardStub(channel).PullParameters(
                pb.PullRequest(run_id=args.run_id), timeout=3
            )
    else:
        config = _load(args.config)
        if args.command == "coordinator":
            server, port = coordinator_server(Coordinator(config), args.bind or "127.0.0.1:50050")
        else:
            from paramesh.workload import parameters

            if not 0 <= args.index < len(config.shard_endpoints):
                parser.error("--index must identify a configured shard")
            values = parameters()
            owners = partition(values, len(config.shard_endpoints))
            shard = ParameterShard(
                config, {k: v for k, v in values.items() if owners[k] == args.index}
            )
            server, port = shard_server(shard, args.bind or config.shard_endpoints[args.index])
        server.start()
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


if __name__ == "__main__":
    main()

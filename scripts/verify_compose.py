"""Black-box check of training, RPC roles, private ports and persistent recreation."""

import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = f"paramesh-check-{uuid.uuid4().hex[:10]}"
    restored_project = f"{project}-restore"

    def command(*arguments: str, timeout: int = 180) -> str:
        return subprocess.check_output(arguments, cwd=ROOT, text=True, timeout=timeout).strip()

    def compose(*arguments: str, project_name: str = project) -> str:
        return command("docker", "compose", "--project-name", project_name, *arguments)

    def workers(project_name: str = project) -> list[dict]:
        results = []
        for name in ("worker-0", "worker-1"):
            container = compose("ps", "-aq", name, project_name=project_name)
            assert container, f"Missing {name} container"
            assert command("docker", "wait", container) == "0", f"{name} exited unsuccessfully"
            output = compose(
                "logs", "--no-color", "--no-log-prefix", name, project_name=project_name
            )
            reports = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            results.append(
                next(item for item in reversed(reports) if item.get("worker_id") == name)
            )
        return results

    def status(project_name: str = project) -> dict:
        return json.loads(
            compose(
                "exec",
                "-T",
                "coordinator",
                "paramesh",
                "status",
                "--coordinator",
                "coordinator:50050",
                project_name=project_name,
            )
        )

    probe = """
import grpc, json
from paramesh.rpc import training_pb2 as pb, training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
security=RpcSecurity.from_environment()
assert security.admin_token is None, 'Workers must not receive administrative credentials'
with grpc.insecure_channel('shard-0:50051') as channel:
    try:
        rpc.ParameterShardStub(channel).PullParameters(pb.PullRequest(run_id='compose-demo'),timeout=3)
    except grpc.RpcError as error:
        assert error.code()==grpc.StatusCode.UNAUTHENTICATED
    else:
        raise AssertionError('Unauthenticated model read succeeded')
versions=[]
for address in ('shard-0:50051','shard-1:50051'):
    with open_channel(address,security) as channel:
        client=rpc.ParameterShardStub(channel)
        versions.append(client.GetProgress(pb.PullRequest(run_id='compose-demo'),timeout=3).version)
        try:
            client.FenceWorker(pb.FenceRequest(run_id='compose-demo',worker_id='worker-0'),timeout=3)
        except grpc.RpcError as error:
            assert error.code()==grpc.StatusCode.PERMISSION_DENIED
        else:
            raise AssertionError('Worker credentials acquired administrative access')
print(json.dumps({'shard_versions':versions,'unauthenticated_read_denied':True,'admin_access_denied':True}))
"""
    try:
        compose("up", "-d", "--no-build")
        initial_workers = workers()
        initial_status = status()
        target = initial_workers[0]["steps"]
        assert all(
            item["steps"] == target and item["resumed_from"] == 0 for item in initial_workers
        )
        assert int(initial_status["global_step"]) == target
        assert all(item["health"] == "completed" for item in initial_status["workers"])
        ports = {}
        for name in ("coordinator", "shard-0", "shard-1", "worker-0", "worker-1"):
            container = compose("ps", "-aq", name)
            bindings = json.loads(
                command(
                    "docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container
                )
            )
            assert not bindings, f"{name} publishes an internal training port"
            ports[name] = bindings
        roles = json.loads(
            compose("run", "--rm", "--no-deps", "--entrypoint", "python", "worker-0", "-c", probe)
        )
        assert roles["shard_versions"] == [target, target]
        compose("down")
        checkpoint = json.loads(
            compose(
                "run",
                "--rm",
                "--no-deps",
                "checkpoint",
                "checkpoint",
                "export",
                "--id",
                "verified",
                "--state-dir",
                "/cluster",
                "--store",
                "/checkpoints",
            )
        )
        assert checkpoint["global_step"] == target
        assert checkpoint["shard_versions"] == [target, target]
        compose("--profile", "storage", "up", "-d", "--wait", "seaweedfs")
        s3_checkpoint = json.loads(
            compose(
                "run",
                "--rm",
                "--no-deps",
                "checkpoint",
                "checkpoint",
                "export",
                "--id",
                "verified-s3",
                "--state-dir",
                "/cluster",
                "--s3-endpoint",
                "http://seaweedfs:8333",
                "--bucket",
                "paramesh-checkpoints",
            )
        )
        assert s3_checkpoint["records"] == checkpoint["records"]
        s3_restore = json.loads(
            compose(
                "run",
                "--rm",
                "--no-deps",
                "checkpoint",
                "checkpoint",
                "restore",
                "--id",
                "verified-s3",
                "--state-dir",
                "/tmp/s3-restored",
                "--s3-endpoint",
                "http://seaweedfs:8333",
                "--bucket",
                "paramesh-checkpoints",
            )
        )
        assert s3_restore == s3_checkpoint
        compose(
            "run",
            "--rm",
            "--no-deps",
            "--volume",
            f"{project}_checkpoints:/checkpoints",
            "checkpoint",
            "checkpoint",
            "install",
            "--id",
            "verified",
            "--state-dir",
            "/cluster",
            "--store",
            "/checkpoints",
            project_name=restored_project,
        )
        compose("up", "-d", "--no-build", project_name=restored_project)
        checkpoint_workers = workers(restored_project)
        assert all(
            item["resumed_from"] == target and not item["losses"] for item in checkpoint_workers
        )
        assert int(status(restored_project)["global_step"]) == target
        compose("up", "-d", "--no-build")
        restored_workers = workers()
        restored_status = status()
        assert int(restored_status["global_step"]) == target
        assert all(
            item["resumed_from"] == target and item["losses"] == [] for item in restored_workers
        )
        assert all(
            int(after["generation"]) > int(before["generation"])
            for before, after in zip(
                initial_status["workers"], restored_status["workers"], strict=True
            )
        )
        report = {
            "project": project,
            "source_commit": command("git", "rev-parse", "HEAD"),
            "source_dirty": bool(command("git", "status", "--porcelain")),
            "engine_version": command("docker", "version", "--format", "{{.Server.Version}}"),
            "initial_workers": initial_workers,
            "restored_workers": restored_workers,
            "initial_status": initial_status,
            "restored_status": restored_status,
            "host_port_bindings": ports,
            "rpc_roles": roles,
            "checkpoint": checkpoint,
            "s3_checkpoint": s3_checkpoint,
            "checkpoint_restored_workers": checkpoint_workers,
        }
        output = ROOT / "artifacts" / "compose-verification.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            "Compose passed: training, RPC roles, private ports, restart and local/S3 checkpoints."
        )
    finally:
        # Only this invocation's unique project and synthetic test volumes are removed.
        for owned_project in (restored_project, project):
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    owned_project,
                    "--profile",
                    "storage",
                    "--profile",
                    "maintenance",
                    "down",
                    "--volumes",
                ],
                cwd=ROOT,
                check=True,
                timeout=120,
            )


if __name__ == "__main__":
    main()

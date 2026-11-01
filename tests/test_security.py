import shutil
import subprocess
from pathlib import Path

import grpc
import numpy as np
import pytest
from test_coordinator import config

from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.services import shard_server
from paramesh.shard import ParameterShard


def test_service_credentials_separate_data_and_admin_operations():
    security = RpcSecurity("d" * 43, "a" * 43)
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)})
    server, port = shard_server(shard, "127.0.0.1:0", security=security)
    server.start()
    address = f"127.0.0.1:{port}"
    try:
        with grpc.insecure_channel(address) as channel:
            with pytest.raises(grpc.RpcError) as error:
                rpc.ParameterShardStub(channel).PullParameters(
                    pb.PullRequest(run_id="test-run"), timeout=2
                )
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with open_channel(address, security) as channel:
            client = rpc.ParameterShardStub(channel)
            assert client.PullParameters(pb.PullRequest(run_id="test-run"), timeout=2).version == 0
            with pytest.raises(grpc.RpcError) as error:
                client.FenceWorker(
                    pb.FenceRequest(run_id="test-run", worker_id="worker-0", generation=1),
                    timeout=2,
                )
            assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
        with open_channel(address, security, admin=True) as channel:
            rpc.ParameterShardStub(channel).FenceWorker(
                pb.FenceRequest(run_id="test-run", worker_id="worker-0", generation=1), timeout=2
            )
        assert shard.worker_generations["worker-0"] == 1
        assert "d" * 43 not in repr(security) and "a" * 43 not in repr(security)
    finally:
        server.stop(0).wait()


def test_missing_weak_or_equal_credentials_fail_closed(monkeypatch):
    monkeypatch.delenv("PARAMESH_RPC_TOKEN", raising=False)
    with pytest.raises(ValueError, match="PARAMESH_RPC_TOKEN"):
        RpcSecurity.from_environment()
    with pytest.raises(ValueError, match="32"):
        RpcSecurity("short", "a" * 43)
    with pytest.raises(ValueError, match="distinct"):
        RpcSecurity("x" * 43, "x" * 43)


def test_unconfigured_admin_role_cannot_be_claimed_with_empty_bearer():
    security = RpcSecurity("d" * 43)
    server, port = shard_server(
        ParameterShard(config(), {"w": np.ones(1, dtype=np.float32)}),
        "127.0.0.1:0",
        security=security,
    )
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            with pytest.raises(grpc.RpcError) as error:
                rpc.ParameterShardStub(channel).FenceWorker(
                    pb.FenceRequest(
                        run_id="test-run",
                        worker_id="worker-0",
                        generation=1,
                    ),
                    timeout=2,
                    metadata=(("authorization", "Bearer "),),
                )
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        server.stop(0).wait()


def test_mutual_tls_requires_client_certificate_and_accepts_valid_peer(tmp_path):
    openssl = shutil.which("openssl") or str(Path("C:/Program Files/Git/usr/bin/openssl.exe"))
    assert Path(openssl).exists(), "OpenSSL is required for the TLS integration check"
    key, cert = tmp_path / "test.key", tmp_path / "test.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    security = RpcSecurity(
        "d" * 43,
        "a" * 43,
        ca=cert.read_bytes(),
        certificate=cert.read_bytes(),
        private_key=key.read_bytes(),
        require_client_certificate=True,
    )
    server, port = shard_server(
        ParameterShard(config(), {"w": np.ones(1, dtype=np.float32)}),
        "127.0.0.1:0",
        security=security,
    )
    server.start()
    try:
        with open_channel(f"127.0.0.1:{port}", security) as channel:
            assert (
                rpc.ParameterShardStub(channel)
                .PullParameters(pb.PullRequest(run_id="test-run"), timeout=3)
                .version
                == 0
            )
        without_certificate = RpcSecurity("d" * 43, ca=cert.read_bytes())
        with open_channel(f"127.0.0.1:{port}", without_certificate) as channel:
            with pytest.raises(grpc.RpcError):
                rpc.ParameterShardStub(channel).PullParameters(
                    pb.PullRequest(run_id="test-run"), timeout=1
                )
    finally:
        server.stop(0).wait()

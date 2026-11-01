import grpc
import numpy as np
import pytest
from test_coordinator import config

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.services import coordinator_server, shard_server
from paramesh.shard import ParameterShard
from paramesh.tensors import encode


def test_coordinator_roundtrip_and_status_codes():
    server, port = coordinator_server(Coordinator(config()), "127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            client = rpc.CoordinatorStub(channel)
            session = client.RegisterWorker(
                pb.RegisterWorkerRequest(worker_id="worker-0", protocol_version=1),
                timeout=2,
            )
            state = client.Heartbeat(
                pb.HeartbeatRequest(
                    run_id="test-run",
                    worker_id="worker-0",
                    session_id=session.session_id,
                ),
                timeout=2,
            )
            assert state.health == "healthy"
            assert len(client.GetStatus(pb.Empty(), timeout=2).workers) == 1
            with pytest.raises(grpc.RpcError) as error:
                client.Heartbeat(pb.HeartbeatRequest(run_id="test-run"), timeout=2)
            assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
    finally:
        server.stop(0).wait()


def test_shard_roundtrip_and_validation():
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)})
    server, port = shard_server(shard, "127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            client = rpc.ParameterShardStub(channel)
            result = client.PushGradients(
                pb.GradientUpdate(
                    run_id="test-run",
                    worker_id="worker-0",
                    tensors=[encode("weight", np.ones(1, dtype=np.float32))],
                ),
                timeout=2,
            )
            assert result.version == 1
            assert client.PullParameters(pb.PullRequest(run_id="test-run"), timeout=2).version == 1
            with pytest.raises(grpc.RpcError) as error:
                client.PullParameters(pb.PullRequest(run_id="wrong"), timeout=2)
            assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        server.stop(0).wait()

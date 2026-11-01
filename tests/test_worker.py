import grpc
import numpy as np
import pytest
from test_coordinator import config
from test_shard import update, weight

from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.services import coordinator_server, shard_server
from paramesh.shard import ParameterShard
from paramesh.tensors import encode, partition
from paramesh.worker import _push, train_worker
from paramesh.workload import load_parameters, model, parameters


def test_parameter_loading_rejects_broadcastable_shapes_before_mutating():
    network = model()
    values = parameters()
    values["0.weight"] = np.ones((1, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="shape"):
        load_parameters(network, values)
    for name, value in network.named_parameters():
        np.testing.assert_array_equal(value.detach().numpy(), parameters()[name])


def test_retry_after_lost_response_preserves_exact_update_and_commits_once():
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)})

    class LostResponse(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.DEADLINE_EXCEEDED

    class Transport:
        calls = 0

        def PushGradients(self, request, timeout):
            self.calls += 1
            result = shard.push(request)
            if self.calls == 1:
                raise LostResponse()
            return result

    client = Transport()
    assert _push(client, update(), 1).duplicate
    assert client.calls == 2
    assert weight(shard) == pytest.approx(0.8)


def test_bounded_refresh_does_not_resubmit_a_previously_committed_shard():
    settings = config(
        mode=pb.BOUNDED_STALENESS, max_staleness=0, shard_endpoints=["pending-0:0", "pending-1:0"]
    )
    values = parameters()
    owners = partition(values, 2)

    class CompetingUpdateShard(ParameterShard):
        injected = False

        def push(self, request, *, timeout=None):
            if not self.injected:
                self.injected = True
                super().push(
                    pb.GradientUpdate(
                        run_id=settings.run_id,
                        worker_id="worker-1",
                        tensors=[
                            encode(name, np.zeros_like(value))
                            for name, value in self.parameters.items()
                        ],
                    )
                )
            return super().push(request, timeout=timeout)

    shards = [
        ParameterShard(settings, {k: v for k, v in values.items() if owners[k] == 0}),
        CompetingUpdateShard(settings, {k: v for k, v in values.items() if owners[k] == 1}),
    ]
    servers = []
    endpoints = []
    try:
        for item in shards:
            server, port = shard_server(item, "127.0.0.1:0")
            servers.append(server)
            server.start()
            endpoints.append(f"127.0.0.1:{port}")
        settings.shard_endpoints[:] = endpoints
        coordinator = Coordinator(settings)
        server, port = coordinator_server(coordinator, "127.0.0.1:0")
        servers.append(server)
        server.start()
        result = train_worker(f"127.0.0.1:{port}", "worker-0", 2)
        assert result["refreshes"] == 1
        assert [item.version for item in shards] == [2, 3]
        assert coordinator.status().workers[0].health == "completed"
    finally:
        for server in servers:
            server.stop(0).wait()

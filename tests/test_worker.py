import grpc
import numpy as np
import pytest
import torch
from test_coordinator import config
from test_shard import update, weight

from paramesh.journal import Journal
from paramesh.rpc import training_pb2 as pb
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.tensors import encode, partition
from paramesh.worker import _rpc, train_worker
from paramesh.workload import (
    TrainingWorkload,
    dataset,
    load_parameters,
    local_reference,
    model,
    parameters,
)


def test_external_workload_factory_trains_with_existing_protocol(tmp_path):
    settings = config(mode=pb.SYNCHRONOUS, worker_ids=["worker-0"], shard_endpoints=["pending-0:0"])
    external = TrainingWorkload(
        model_factory=lambda: torch.nn.Linear(4, 1),
        dataset_factory=lambda _: dataset(0),
    )
    initial = {
        name: value.detach().numpy().copy()
        for name, value in external.model_factory().named_parameters()
    }
    shard = ParameterShard(settings, initial)
    shard_server_instance, shard_port = shard_server(shard, "127.0.0.1:0")
    shard_server_instance.start()
    settings.shard_endpoints[:] = [f"127.0.0.1:{shard_port}"]
    coordinator = managed_coordinator(settings)
    coordinator_server_instance, coordinator_port = coordinator_server(coordinator, "127.0.0.1:0")
    coordinator_server_instance.start()
    storage = StateDB(tmp_path / "worker.sqlite")
    try:
        result = train_worker(
            f"127.0.0.1:{coordinator_port}",
            "worker-0",
            2,
            state=storage,
            workload=external,
        )
        assert result["steps"] == 2
        assert shard.version == 2
    finally:
        storage.close()
        coordinator_server_instance.stop(0).wait()
        shard_server_instance.stop(0).wait()


def test_worker_rejects_cuda_without_a_cuda_runtime():
    if torch.cuda.is_available():
        pytest.skip("This host has CUDA; the negative-path contract is host-specific")
    with pytest.raises(ValueError, match="CUDA training requested"):
        train_worker("127.0.0.1:1", "worker-0", 1, device="cuda")


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

        def PushGradients(self, request, timeout, **options):
            self.calls += 1
            result = shard.push(request)
            if self.calls == 1:
                raise LostResponse()
            return result

    client = Transport()
    assert _rpc(client.PushGradients, update(), 1).duplicate
    assert client.calls == 2
    assert weight(shard) == pytest.approx(0.8)


def test_rpc_surfaces_deadline_without_retry_when_caller_handles_barrier_recovery():
    class Deadline(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.DEADLINE_EXCEEDED

    class Transport:
        calls = 0

        def PushGradients(self, request, timeout, **options):
            self.calls += 1
            raise Deadline()

    transport = Transport()
    with pytest.raises(Deadline):
        _rpc(transport.PushGradients, update(), 1, retry_deadline=False)
    assert transport.calls == 1


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
        coordinator = managed_coordinator(settings)
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


def test_restart_finishes_original_partial_step_and_matches_local_reference(tmp_path):
    settings = config(
        mode=pb.SYNCHRONOUS, worker_ids=["worker-0"], shard_endpoints=["pending-0:0", "pending-1:0"]
    )
    initial = parameters()
    owners = partition(initial, 2)
    shards = [
        ParameterShard(settings, {k: v for k, v in initial.items() if owners[k] == index})
        for index in range(2)
    ]
    servers = []
    storage = StateDB(tmp_path / "worker.sqlite")
    try:
        endpoints = []
        for shard in shards:
            server, port = shard_server(shard, "127.0.0.1:0")
            servers.append(server)
            server.start()
            endpoints.append(f"127.0.0.1:{port}")
        settings.shard_endpoints[:] = endpoints
        coordinator = managed_coordinator(settings)
        server, port = coordinator_server(coordinator, "127.0.0.1:0")
        servers.append(server)
        server.start()
        network = model()
        inputs, targets = dataset(0)
        loss = torch.nn.functional.mse_loss(network(inputs), targets)
        torch.autograd.backward(loss)
        requests = [
            pb.GradientUpdate(
                run_id=settings.run_id,
                worker_id="worker-0",
                tensors=[
                    encode(name, parameter.grad.detach().numpy())
                    for name, parameter in network.named_parameters()
                    if owners[name] == index
                ],
            )
            for index in range(2)
        ]
        journal = Journal(settings, "worker-0", storage)
        journal.prepare(requests, float(loss.detach()))
        # Crash point: the first shard committed, but the second has not received its request.
        shards[0].push(requests[0])
        storage.close()
        storage = StateDB(tmp_path / "worker.sqlite")
        result = train_worker(f"127.0.0.1:{port}", "worker-0", 4, state=storage)
        assert result["replayed_contributions"] == 1
        expected = local_reference(1, 4, settings.learning_rate)
        for shard in shards:
            assert shard.version == 4
            for name, value in shard.parameters.items():
                np.testing.assert_allclose(value, expected[name], atol=1e-6, rtol=0)
    finally:
        storage.close()
        for server in servers:
            server.stop(0).wait()

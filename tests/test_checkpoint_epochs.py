import socket
import threading
import time

import grpc
import numpy as np
import pytest
from test_coordinator import config
from test_shard import update

from paramesh.checkpoint import (
    abort_online_checkpoint,
    export_online_checkpoint,
    restore_checkpoint,
)
from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.storage import LocalStore


def test_shard_checkpoint_fence_survives_restart_and_rejects_stale_release(tmp_path):
    store = StateDB(tmp_path / "shard.sqlite")
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=store)
    shard.freeze_checkpoint("test-run", 1)
    with pytest.raises(PermissionError, match="checkpoint"):
        shard.push(update())
    store.close()

    reopened = StateDB(tmp_path / "shard.sqlite")
    restored = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)}, state=reopened)
    with pytest.raises(PermissionError, match="checkpoint"):
        restored.push(update())
    with pytest.raises(ValueError, match="epoch"):
        restored.unfreeze_checkpoint("test-run", 0)
    restored.unfreeze_checkpoint("test-run", 1)
    restored.unfreeze_checkpoint("test-run", 1)
    assert restored.push(update()).version == 1
    reopened.close()


def test_coordinator_reserves_epoch_and_persists_safe_worker_acknowledgments(tmp_path):
    store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = Coordinator(config(), state=store)
    sessions = {
        worker_id: coordinator.register(worker_id, 1) for worker_id in ("worker-0", "worker-1")
    }
    for worker_id, session in sessions.items():
        coordinator.heartbeat(
            pb.HeartbeatRequest(
                run_id="test-run", worker_id=worker_id, session_id=session.session_id
            )
        )
    status = coordinator.begin_checkpoint("online-1")
    assert status.control.epoch == 1
    assert status.control.phase == pb.CHECKPOINT_REQUESTED

    for worker_id, session in sessions.items():
        heartbeat = coordinator.heartbeat(
            pb.HeartbeatRequest(
                run_id="test-run",
                worker_id=worker_id,
                session_id=session.session_id,
                step=3,
            )
        )
        assert heartbeat.checkpoint_epoch == 1
        journal = pb.WorkerJournal(
            format_version=1,
            config_fingerprint=coordinator.config_fingerprint,
            worker_id=worker_id,
            next_step=3,
        )
        status = coordinator.acknowledge_checkpoint(
            pb.CheckpointAck(
                run_id="test-run",
                worker_id=worker_id,
                session_id=session.session_id,
                epoch=1,
                step=3,
                parameter_version=heartbeat.parameter_version,
                worker_journal=journal.SerializeToString(deterministic=True),
            )
        )
    assert status.all_workers_acknowledged
    assert len(status.workers) == 2
    assert status.workers[0].step == 3
    assert coordinator.begin_checkpoint("online-1").control.epoch == 1
    with pytest.raises(RuntimeError, match="in progress"):
        coordinator.begin_checkpoint("online-2")
    coordinator.set_checkpoint_phase(1, pb.CHECKPOINT_FROZEN)
    store.close()

    reopened = StateDB(tmp_path / "coordinator.sqlite")
    restored = Coordinator(config(), state=reopened)
    persisted = restored.checkpoint_status()
    assert persisted.control.phase == pb.CHECKPOINT_FROZEN
    assert persisted.all_workers_acknowledged and len(persisted.workers) == 2
    reopened.close()


def test_coordinator_rejects_pending_journal_and_wrong_session_ack(tmp_path):
    coordinator = Coordinator(config())
    session = coordinator.register("worker-0", 1)
    second = coordinator.register("worker-1", 1)
    for worker_id, current in (("worker-0", session), ("worker-1", second)):
        coordinator.heartbeat(
            pb.HeartbeatRequest(
                run_id="test-run", worker_id=worker_id, session_id=current.session_id
            )
        )
    coordinator.begin_checkpoint("online-1")
    journal = pb.WorkerJournal(
        format_version=1,
        config_fingerprint=coordinator.config_fingerprint,
        worker_id="worker-0",
        requests=[pb.GradientUpdate(run_id="test-run", worker_id="worker-0", step=0)],
    )
    request = pb.CheckpointAck(
        run_id="test-run",
        worker_id="worker-0",
        session_id=session.session_id,
        epoch=1,
        worker_journal=journal.SerializeToString(deterministic=True),
    )
    with pytest.raises(ValueError, match="empty"):
        coordinator.acknowledge_checkpoint(request)
    request.worker_journal = b"invalid"
    with pytest.raises(ValueError, match="journal"):
        coordinator.acknowledge_checkpoint(request)
    request.worker_journal = pb.WorkerJournal(
        format_version=1,
        config_fingerprint=coordinator.config_fingerprint,
        worker_id="worker-0",
    ).SerializeToString(deterministic=True)
    request.session_id = "expired-session"
    with pytest.raises(PermissionError, match="session"):
        coordinator.acknowledge_checkpoint(request)


def test_checkpoint_rpc_roles_and_frozen_snapshots(tmp_path):
    security = RpcSecurity("d" * 43, "a" * 43)
    settings = config()
    coordinator_store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = Coordinator(settings, state=coordinator_store)
    coordinator_host, coordinator_port = coordinator_server(
        coordinator, "127.0.0.1:0", security=security
    )
    shard_store = StateDB(tmp_path / "shard.sqlite")
    shard = ParameterShard(settings, {"weight": np.ones(1, dtype=np.float32)}, state=shard_store)
    shard_host, shard_port = shard_server(shard, "127.0.0.1:0", security=security)
    coordinator_host.start()
    shard_host.start()
    try:
        coordinator_address = f"127.0.0.1:{coordinator_port}"
        shard_address = f"127.0.0.1:{shard_port}"
        with open_channel(coordinator_address, security) as channel:
            client = rpc.CoordinatorStub(channel)
            sessions = {}
            for worker_id in settings.worker_ids:
                session = client.RegisterWorker(
                    pb.RegisterWorkerRequest(worker_id=worker_id, protocol_version=1), timeout=2
                )
                sessions[worker_id] = session
                client.Heartbeat(
                    pb.HeartbeatRequest(
                        run_id=settings.run_id,
                        worker_id=worker_id,
                        session_id=session.session_id,
                    ),
                    timeout=2,
                )
            with pytest.raises(grpc.RpcError) as error:
                client.BeginCheckpoint(
                    pb.CheckpointRequest(run_id=settings.run_id, checkpoint_id="rpc-epoch"),
                    timeout=2,
                )
            assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED

        with open_channel(coordinator_address, security, admin=True) as channel:
            admin = rpc.CoordinatorStub(channel)
            requested = admin.BeginCheckpoint(
                pb.CheckpointRequest(run_id=settings.run_id, checkpoint_id="rpc-epoch"),
                timeout=2,
            )
            assert requested.control.phase == pb.CHECKPOINT_REQUESTED
        with open_channel(coordinator_address, security) as channel:
            client = rpc.CoordinatorStub(channel)
            for worker_id, session in sessions.items():
                journal = pb.WorkerJournal(
                    format_version=1,
                    config_fingerprint=coordinator.config_fingerprint,
                    worker_id=worker_id,
                )
                client.AcknowledgeCheckpoint(
                    pb.CheckpointAck(
                        run_id=settings.run_id,
                        worker_id=worker_id,
                        session_id=session.session_id,
                        epoch=1,
                        worker_journal=journal.SerializeToString(deterministic=True),
                    ),
                    timeout=2,
                )
            assert (
                client.GetCheckpointControl(
                    pb.CheckpointRequest(run_id=settings.run_id, worker_id="worker-0"), timeout=2
                ).phase
                == pb.CHECKPOINT_REQUESTED
            )
        with open_channel(coordinator_address, security, admin=True) as channel:
            admin = rpc.CoordinatorStub(channel)
            admin.SetCheckpointPhase(
                pb.CheckpointPhaseRequest(
                    run_id=settings.run_id, epoch=1, phase=pb.CHECKPOINT_FROZEN
                ),
                timeout=2,
            )
            assert admin.GetCheckpointSnapshot(
                pb.CheckpointRequest(run_id=settings.run_id, checkpoint_id="rpc-epoch"),
                timeout=2,
            ).snapshot
        with open_channel(shard_address, security) as channel:
            with pytest.raises(grpc.RpcError) as error:
                rpc.ParameterShardStub(channel).FreezeCheckpoint(
                    pb.ShardCheckpointRequest(run_id=settings.run_id, epoch=1), timeout=2
                )
            assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
        with open_channel(shard_address, security, admin=True) as channel:
            client = rpc.ParameterShardStub(channel)
            request = pb.ShardCheckpointRequest(run_id=settings.run_id, epoch=1)
            client.FreezeCheckpoint(request, timeout=2)
            snapshot = pb.ShardSnapshot.FromString(
                client.ExportCheckpointSnapshot(request, timeout=2).snapshot
            )
            assert snapshot.checkpoint_epoch == 1 and snapshot.checkpoint_frozen
            client.UnfreezeCheckpoint(request, timeout=2)
    finally:
        coordinator_host.stop(0).wait()
        shard_host.stop(0).wait()
        coordinator_store.close()
        shard_store.close()


def test_live_checkpoint_abort_unfreezes_shards_and_releases_workers(tmp_path):
    settings = config(shard_endpoints=["pending"], worker_ids=["worker-0"])
    security = RpcSecurity.ephemeral()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        address = f"127.0.0.1:{reservation.getsockname()[1]}"
    settings.shard_endpoints[:] = [address]
    shard_store = StateDB(tmp_path / "shard.sqlite")
    from paramesh.workload import parameters

    shard = ParameterShard(settings, parameters(), state=shard_store)
    shard_host, shard_port = shard_server(shard, address, security=security)
    coordinator_store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = Coordinator(settings, state=coordinator_store)
    coordinator_host, coordinator_port = coordinator_server(
        coordinator, "127.0.0.1:0", security=security
    )
    shard_host.start()
    coordinator_host.start()
    try:
        session = coordinator.register("worker-0", 1)
        coordinator.heartbeat(
            pb.HeartbeatRequest(
                run_id=settings.run_id,
                worker_id="worker-0",
                session_id=session.session_id,
            )
        )
        coordinator.begin_checkpoint("abandoned-epoch")
        shard.freeze_checkpoint(settings.run_id, 1)
        abort_online_checkpoint(
            f"127.0.0.1:{coordinator_port}", "abandoned-epoch", security, timeout=5
        )
        assert coordinator.checkpoint_status().control.phase == pb.CHECKPOINT_RUNNING
        assert not shard.checkpoint_frozen and shard.checkpoint_epoch == 1
    finally:
        coordinator_host.stop(0).wait()
        shard_host.stop(0).wait()
        coordinator_store.close()
        shard_store.close()


def test_checkpoint_retries_uncertain_publish_and_partial_unfreeze_after_restart(tmp_path):
    settings = config(shard_endpoints=["pending", "pending"])
    security = RpcSecurity.ephemeral()
    from paramesh.tensors import partition
    from paramesh.workload import parameters

    initial = parameters()
    owners = partition(initial, len(settings.shard_endpoints))
    addresses = []
    shards = []
    shard_stores = []
    shard_hosts = []
    for index in range(2):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            address = f"127.0.0.1:{reservation.getsockname()[1]}"
        addresses.append(address)
        settings.shard_endpoints[index] = address
    for index, address in enumerate(addresses):
        shard_store = StateDB(tmp_path / f"shard-{index}.sqlite")
        shard = ParameterShard(
            settings,
            {name: value for name, value in initial.items() if owners[name] == index},
            state=shard_store,
        )
        shard_host, _ = shard_server(shard, address, security=security)
        shard_host.start()
        shards.append(shard)
        shard_stores.append(shard_store)
        shard_hosts.append(shard_host)

    coordinator_address = "127.0.0.1:0"
    coordinator_store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = Coordinator(settings, state=coordinator_store)
    coordinator_host, coordinator_port = coordinator_server(
        coordinator, coordinator_address, security=security
    )
    coordinator_host.start()
    address = f"127.0.0.1:{coordinator_port}"
    store = LocalStore(tmp_path / "online-checkpoints")
    try:
        sessions = {
            worker_id: coordinator.register(worker_id, 1) for worker_id in settings.worker_ids
        }
        for worker_id, session in sessions.items():
            coordinator.heartbeat(
                pb.HeartbeatRequest(
                    run_id=settings.run_id,
                    worker_id=worker_id,
                    session_id=session.session_id,
                )
            )
        epoch = coordinator.begin_checkpoint("restart-epoch")
        for worker_id, session in sessions.items():
            journal = pb.WorkerJournal(
                format_version=1,
                config_fingerprint=coordinator.config_fingerprint,
                worker_id=worker_id,
            )
            coordinator.acknowledge_checkpoint(
                pb.CheckpointAck(
                    run_id=settings.run_id,
                    worker_id=worker_id,
                    session_id=session.session_id,
                    epoch=epoch.control.epoch,
                    worker_journal=journal.SerializeToString(deterministic=True),
                )
            )
        coordinator.set_checkpoint_phase(1, pb.CHECKPOINT_FROZEN)
        for shard in shards:
            shard.freeze_checkpoint(settings.run_id, 1)

        class FailManifestOnce:
            failed = False

            def put(self, key, payload):
                store.put(key, payload)
                if key.startswith("manifests/") and not self.failed:
                    self.failed = True
                    raise OSError("injected lost manifest response")

            def get(self, key, limit=128 * 1024 * 1024):
                return store.get(key, limit)

        with pytest.raises(OSError, match="injected"):
            export_online_checkpoint(address, FailManifestOnce(), "restart-epoch", security)
        assert coordinator.checkpoint_status().control.phase == pb.CHECKPOINT_FROZEN
        assert all(shard.checkpoint_frozen for shard in shards)

        def restart_services():
            nonlocal coordinator, coordinator_host, coordinator_store
            coordinator_host.stop(0).wait()
            coordinator_store.close()
            coordinator_store = StateDB(tmp_path / "coordinator.sqlite")
            coordinator = Coordinator(settings, state=coordinator_store)
            coordinator_host, _ = coordinator_server(coordinator, address, security=security)
            coordinator_host.start()
            for index, shard_host in enumerate(shard_hosts):
                shard_host.stop(0).wait()
                shard_stores[index].close()
                shard_stores[index] = StateDB(tmp_path / f"shard-{index}.sqlite")
                shards[index] = ParameterShard(
                    settings,
                    {name: value for name, value in initial.items() if owners[name] == index},
                    state=shard_stores[index],
                )
                shard_hosts[index], _ = shard_server(
                    shards[index], addresses[index], security=security
                )
                shard_hosts[index].start()

        restart_services()

        def reject_one_unfreeze(run_id, epoch):
            raise RuntimeError("injected partial unfreeze failure")

        shards[1].unfreeze_checkpoint = reject_one_unfreeze
        with pytest.raises(grpc.RpcError) as error:
            export_online_checkpoint(address, store, "restart-epoch", security)
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        assert coordinator.checkpoint_status().control.phase == pb.CHECKPOINT_COMMITTED
        assert not shards[0].checkpoint_frozen and shards[1].checkpoint_frozen

        restart_services()

        manifest = export_online_checkpoint(address, store, "restart-epoch", security)
        assert manifest["checkpoint_id"] == "restart-epoch"
        assert coordinator.checkpoint_status().control.phase == pb.CHECKPOINT_RUNNING
        assert all(not shard.checkpoint_frozen for shard in shards)
    finally:
        coordinator_host.stop(0).wait()
        for shard_host in shard_hosts:
            shard_host.stop(0).wait()
        coordinator_store.close()
        for shard_store in shard_stores:
            shard_store.close()


@pytest.mark.parametrize("mode", [pb.SYNCHRONOUS, pb.ASYNCHRONOUS, pb.BOUNDED_STALENESS])
def test_workers_pause_at_durable_step_and_resume_after_epoch_release(tmp_path, mode):
    workers = ["worker-0", "worker-1"]
    settings = config(
        worker_ids=workers,
        shard_endpoints=["pending", "pending"],
        mode=mode,
        max_staleness=1,
    )
    security = RpcSecurity.ephemeral()
    from paramesh.tensors import partition
    from paramesh.workload import parameters

    addresses = []
    for _ in range(2):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            addresses.append(f"127.0.0.1:{reservation.getsockname()[1]}")
    settings.shard_endpoints[:] = addresses
    initial = parameters()
    owners = partition(initial, len(addresses))
    shards = []
    shard_stores = []
    shard_hosts = []
    for index, address in enumerate(addresses):
        shard_store = StateDB(tmp_path / f"shard-{index}.sqlite")
        shard = ParameterShard(
            settings,
            {name: value for name, value in initial.items() if owners[name] == index},
            state=shard_store,
        )
        shard_host, _ = shard_server(shard, address, security=security)
        shard_host.start()
        shard_stores.append(shard_store)
        shards.append(shard)
        shard_hosts.append(shard_host)
    coordinator_store = StateDB(tmp_path / "coordinator.sqlite")
    coordinator = managed_coordinator(settings, state=coordinator_store, security=security)
    coordinator_host, coordinator_port = coordinator_server(
        coordinator, "127.0.0.1:0", security=security
    )
    coordinator_host.start()
    worker_stores = {worker_id: StateDB(tmp_path / f"{worker_id}.sqlite") for worker_id in workers}
    results = {}
    errors = []

    def train(worker_id):
        try:
            from paramesh.worker import train_worker

            results[worker_id] = train_worker(
                f"127.0.0.1:{coordinator_port}",
                worker_id,
                40,
                state=worker_stores[worker_id],
                step_delay=0.2,
                security=security,
            )
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=train, args=(worker_id,)) for worker_id in workers]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            status = coordinator.status()
            if len(status.workers) == len(workers) and all(
                worker.health == "healthy" for worker in status.workers
            ):
                break
            time.sleep(0.01)
        assert all(worker.health == "healthy" for worker in coordinator.status().workers)
        coordinator.begin_checkpoint("worker-epoch")
        store = LocalStore(tmp_path / "online-checkpoints")
        manifest = export_online_checkpoint(
            f"127.0.0.1:{coordinator_port}",
            store,
            "worker-epoch",
            security,
            timeout=20,
        )
        assert 0 < manifest["global_step"] < 40
        restored = restore_checkpoint(store, "worker-epoch", tmp_path / "restored")
        assert restored["global_step"] == manifest["global_step"]
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads) and not errors
        assert all(result["steps"] == 40 for result in results.values())
        assert coordinator.status().global_step == 40
        assert (
            export_online_checkpoint(
                f"127.0.0.1:{coordinator_port}", store, "worker-epoch", security, timeout=5
            )
            == manifest
        )
        if mode == pb.SYNCHRONOUS:
            from paramesh.workload import local_reference

            reference = local_reference(len(workers), 40, settings.learning_rate)
            actual = {name: value for shard in shards for name, value in shard.parameters.items()}
            assert (
                max(np.max(np.abs(actual[name] - expected)) for name, expected in reference.items())
                < 1e-6
            )
    finally:
        coordinator_host.stop(0).wait()
        for shard_host in shard_hosts:
            shard_host.stop(0).wait()
        for worker_store in worker_stores.values():
            worker_store.close()
        coordinator_store.close()
        for shard_store in shard_stores:
            shard_store.close()

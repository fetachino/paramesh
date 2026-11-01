import json
import socket
import subprocess
import sys
from contextlib import ExitStack

import numpy as np
import pytest
import torch
from test_coordinator import config

import paramesh.checkpoint as checkpoint
from paramesh.checkpoint import export_checkpoint, install_checkpoint, restore_checkpoint
from paramesh.coordinator import Coordinator
from paramesh.journal import Journal
from paramesh.rpc import training_pb2 as pb
from paramesh.services import coordinator_server, managed_coordinator, shard_server
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.storage import LocalStore, S3Store
from paramesh.tensors import encode, partition
from paramesh.worker import train_worker
from paramesh.workload import dataset, local_reference, model, parameters


def partial_run(root):
    endpoints = []
    for _ in range(2):
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            endpoints.append(f"127.0.0.1:{connection.getsockname()[1]}")
    settings = config(mode=pb.SYNCHRONOUS, worker_ids=["worker-0"], shard_endpoints=endpoints)
    initial = parameters()
    owners = partition(initial, 2)
    with ExitStack() as stack:
        stores = {}
        for role in ("coordinator", "shard-0", "shard-1", "worker-0"):
            stores[role] = StateDB(root / role / f"{role}.sqlite")
            stack.callback(stores[role].close)
        shards = [
            ParameterShard(
                settings,
                {k: v for k, v in initial.items() if owners[k] == index},
                state=stores[f"shard-{index}"],
            )
            for index in range(2)
        ]
        coordinator = Coordinator(
            settings,
            state=stores["coordinator"],
            fence=lambda name, generation: [
                shard.fence(settings.run_id, name, generation) for shard in shards
            ],
        )
        session = coordinator.register("worker-0", 1)
        network = model()
        inputs, targets = dataset(0)
        loss = torch.nn.functional.mse_loss(network(inputs), targets)
        torch.autograd.backward(loss)
        requests = [
            pb.GradientUpdate(
                run_id=settings.run_id,
                worker_id="worker-0",
                generation=session.generation,
                tensors=[
                    encode(name, parameter.grad.detach().numpy())
                    for name, parameter in network.named_parameters()
                    if owners[name] == index
                ],
            )
            for index in range(2)
        ]
        Journal(settings, "worker-0", stores["worker-0"]).prepare(requests, float(loss.detach()))
        shards[0].push(requests[0])
    return settings


def test_portable_checkpoint_restores_partial_step_and_matches_uninterrupted_sgd(tmp_path):
    settings = partial_run(tmp_path / "source")
    store = LocalStore(tmp_path / "objects")
    manifest = export_checkpoint(tmp_path / "source", store, "partial")
    assert manifest["shard_versions"] == [1, 0]
    assert manifest["global_step"] == 0
    assert export_checkpoint(tmp_path / "source", store, "partial") == manifest
    restored = tmp_path / "restored"
    assert restore_checkpoint(store, "partial", restored) == manifest
    assert json.loads((restored / "run.json").read_text())["runId"] == settings.run_id
    initial, owners = parameters(), partition(parameters(), 2)
    with ExitStack() as stack:
        shards = []
        for index in range(2):
            database = StateDB(restored / f"shard-{index}" / f"shard-{index}.sqlite")
            stack.callback(database.close)
            shard = ParameterShard(
                settings, {k: v for k, v in initial.items() if owners[k] == index}, state=database
            )
            shards.append(shard)
            server, _ = shard_server(shard, settings.shard_endpoints[index])
            server.start()
            stack.callback(lambda server=server: server.stop(0).wait())
        coordinator_db = StateDB(restored / "coordinator" / "coordinator.sqlite")
        stack.callback(coordinator_db.close)
        coordinator = managed_coordinator(settings, state=coordinator_db)
        server, port = coordinator_server(coordinator, "127.0.0.1:0")
        server.start()
        stack.callback(lambda: server.stop(0).wait())
        worker_db = StateDB(restored / "worker-0" / "worker-0.sqlite")
        stack.callback(worker_db.close)
        result = train_worker(f"127.0.0.1:{port}", "worker-0", 4, state=worker_db)
        assert result["replayed_contributions"] == 1
        assert coordinator.status().global_step == 4
        expected = local_reference(1, 4, settings.learning_rate)
        for shard in shards:
            assert shard.version == 4
            for name, value in shard.parameters.items():
                np.testing.assert_allclose(value, expected[name], atol=1e-6, rtol=0)


def test_live_missing_or_inconsistent_state_cannot_be_exported(tmp_path):
    source = tmp_path / "source"
    settings = partial_run(source)
    store = LocalStore(tmp_path / "objects")
    database = StateDB(source / "shard-1" / "shard-1.sqlite")
    try:
        with pytest.raises(OSError, match="already in use"):
            export_checkpoint(source, store, "live")
    finally:
        database.close()
    with pytest.raises(ValueError, match="Missing coordinator"):
        export_checkpoint(tmp_path / "absent", store, "missing")
    database = StateDB(source / "worker-0" / "worker-0.sqlite")
    journal = Journal(settings, "worker-0", database)
    record = pb.WorkerJournal()
    record.CopyFrom(journal.record)
    del record.requests[:]
    database.put("worker", record.SerializeToString())
    database.close()
    with pytest.raises(ValueError, match="progress"):
        export_checkpoint(source, store, "inconsistent")
    assert list((tmp_path / "objects").iterdir()) == []


def test_corruption_and_existing_restore_destination_leave_existing_data_intact(tmp_path):
    source = tmp_path / "source"
    partial_run(source)
    store = LocalStore(tmp_path / "objects")
    manifest = export_checkpoint(source, store, "saved")
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "existing.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        restore_checkpoint(store, "saved", destination)
    assert sentinel.read_text() == "keep"
    blob = tmp_path / "objects" / manifest["records"][0]["key"]
    blob.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        restore_checkpoint(store, "saved", tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


def test_failed_upload_never_publishes_a_manifest(tmp_path):
    partial_run(tmp_path / "source")

    class FailedStore(LocalStore):
        calls = 0

        def put(self, key, payload):
            self.calls += 1
            if self.calls == 2:
                raise OSError("upload interrupted")
            super().put(key, payload)

    store = FailedStore(tmp_path / "objects")
    with pytest.raises(OSError, match="interrupted"):
        export_checkpoint(tmp_path / "source", store, "failed")
    with pytest.raises(FileNotFoundError):
        restore_checkpoint(store, "failed", tmp_path / "fresh")


def test_object_keys_size_limits_and_immutability(tmp_path):
    store = LocalStore(tmp_path / "objects")
    key = "manifests/saved.json"
    store.put(key, b"first")
    store.put(key, b"first")
    with pytest.raises(ValueError, match="different contents"):
        store.put(key, b"other")
    with pytest.raises(ValueError, match="size limit"):
        store.get(key, 4)
    with pytest.raises(ValueError, match="object key"):
        store.put("../../outside", b"bad")
    with pytest.raises(ValueError, match="safe identifier"):
        export_checkpoint(tmp_path, store, "../escape")
    with pytest.raises(ValueError, match="Explicit S3"):
        S3Store("https://secret:password@example.com", "bucket", "key", "secret")


def test_install_into_empty_volumes_and_fail_closed_on_interrupted_install(tmp_path, monkeypatch):
    partial_run(tmp_path / "source")
    store = LocalStore(tmp_path / "objects")
    manifest = export_checkpoint(tmp_path / "source", store, "saved")
    destination = tmp_path / "volumes"
    assert install_checkpoint(store, "saved", destination) == manifest
    assert not list(destination.rglob(".restore-incomplete"))
    before = (destination / "coordinator" / "coordinator.sqlite").read_bytes()
    with pytest.raises(FileExistsError, match="empty volumes"):
        install_checkpoint(store, "saved", destination)
    assert (destination / "coordinator" / "coordinator.sqlite").read_bytes() == before
    original = StateDB.put

    def fail_install(self, key, payload):
        if (
            key == "worker"
            and (tmp_path / "failed" / "coordinator" / ".restore-incomplete").exists()
        ):
            raise OSError("disk full")
        return original(self, key, payload)

    monkeypatch.setattr(StateDB, "put", fail_install)
    with pytest.raises(OSError, match="disk full"):
        install_checkpoint(store, "saved", tmp_path / "failed")
    assert (tmp_path / "failed" / "coordinator" / ".restore-incomplete").is_file()
    assert len(list((tmp_path / "failed").rglob(".restore-incomplete"))) == 4
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "paramesh.cli",
            "worker",
            "--id",
            "worker-0",
            "--state-dir",
            str(tmp_path / "failed" / "worker-0"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert refused.returncode == 2 and "installation is incomplete" in refused.stderr


@pytest.mark.parametrize(
    "change", ["format", "count", "role", "summary", "membership", "duplicate"]
)
def test_invalid_manifests_never_publish_a_destination(tmp_path, change):
    partial_run(tmp_path / "source")
    store = LocalStore(tmp_path / "objects")
    manifest = export_checkpoint(tmp_path / "source", store, "saved")
    if change == "format":
        manifest["format_version"] = 2
    elif change == "count":
        manifest["records"] = []
    elif change == "role":
        manifest["records"][0]["role"] = "../outside"
    elif change == "summary":
        manifest["global_step"] += 1
    elif change == "membership":
        manifest["records"] = manifest["records"][:-1]
    elif change == "duplicate":
        manifest["records"].append(manifest["records"][0])
    (tmp_path / "objects" / "manifests" / "saved.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        restore_checkpoint(store, "saved", tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


@pytest.mark.parametrize("change", ["receipt", "generation", "coordinator"])
def test_inconsistent_cross_service_state_cannot_be_published(tmp_path, change):
    partial_run(tmp_path / "source")
    root = tmp_path / "source"
    if change == "coordinator":
        database = StateDB(root / "coordinator" / "coordinator.sqlite")
        record = json.loads(database.get("coordinator"))
        record["workers"]["worker-0"]["step"] = 3
        database.put("coordinator", json.dumps(record).encode())
    else:
        database = StateDB(root / "shard-0" / "shard-0.sqlite")
        record = pb.ShardSnapshot()
        record.ParseFromString(database.get("shard"))
        if change == "receipt":
            record.receipts[0].digest = b"x" * 32
        else:
            record.worker_generations["worker-0"] = 20
        database.put("shard", record.SerializeToString())
    database.close()
    store = LocalStore(tmp_path / "objects")
    with pytest.raises(ValueError):
        export_checkpoint(root, store, "bad")
    assert list((tmp_path / "objects").iterdir()) == []


def test_checkpoint_total_size_bound_applies_before_publication_and_restore(tmp_path, monkeypatch):
    partial_run(tmp_path / "source")
    store = LocalStore(tmp_path / "objects")
    export_checkpoint(tmp_path / "source", store, "saved")
    monkeypatch.setattr(checkpoint, "MAX_BUNDLE_BYTES", 1)
    with pytest.raises(ValueError, match="bundle exceeds"):
        export_checkpoint(tmp_path / "source", store, "large")
    with pytest.raises(ValueError, match="bundle exceeds"):
        restore_checkpoint(store, "saved", tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()

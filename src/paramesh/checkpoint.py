"""Offline whole-run checkpoints, including journals for partially delivered steps."""

import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

from google.protobuf.json_format import MessageToJson

from paramesh import telemetry
from paramesh.config import validate_config
from paramesh.coordinator import Coordinator
from paramesh.events import emit
from paramesh.journal import Journal
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.storage import ObjectStore
from paramesh.tensors import FloatArray, partition

MAX_BUNDLE_BYTES = 128 * 1024 * 1024


def _manifest_key(checkpoint_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", checkpoint_id):
        raise ValueError("Checkpoint ID must be a safe identifier")
    return f"manifests/{checkpoint_id}.json"


def _config(payload: bytes) -> pb.RunConfig:
    saved = json.loads(payload)
    config = pb.RunConfig()
    config.ParseFromString(bytes.fromhex(saved["config"]))
    validate_config(config)
    return config


def _roles(config: pb.RunConfig) -> dict[str, str]:
    roles = (
        {"coordinator": "coordinator"}
        | {f"shard-{i}": "shard" for i in range(len(config.shard_endpoints))}
        | {name: "worker" for name in config.worker_ids}
    )
    if len(roles) != 1 + len(config.shard_endpoints) + len(config.worker_ids):
        raise ValueError("Worker IDs collide with checkpoint service names")
    return roles


def _open(stack: ExitStack, root: Path, role: str) -> StateDB:
    store = StateDB(root / role / f"{role}.sqlite")
    stack.callback(store.close)
    return store


def _validate(
    records: dict[str, bytes],
    root: Path,
    initial_parameters: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    from paramesh.workload import parameters

    config = _config(records["coordinator"])
    roles = _roles(config)
    if records.keys() != roles.keys():
        raise ValueError("Checkpoint membership is incomplete or unexpected")
    initial = parameters() if initial_parameters is None else initial_parameters
    owners = partition(initial, len(config.shard_endpoints))
    with ExitStack() as stack:
        stores = {name: _open(stack, root, name) for name in roles}
        for name, key in roles.items():
            stores[name].put(key, records[name])
        coordinator = Coordinator(config, state=stores["coordinator"])
        journals = {name: Journal(config, name, stores[name]) for name in config.worker_ids}
        versions = []
        for index in range(len(config.shard_endpoints)):
            shard = ParameterShard(
                config,
                {name: value for name, value in initial.items() if owners[name] == index},
                state=stores[f"shard-{index}"],
            )
            versions.append(shard.version)
            for name, journal in journals.items():
                position = shard.progress(config.run_id).next_steps[name]
                step = journal.record.next_step
                if position != step and not (journal.record.requests and position == step + 1):
                    raise ValueError("Shard progress cannot be recovered from worker journal")
                if position == step + 1:
                    request = pb.GradientUpdate()
                    request.CopyFrom(journal.record.requests[index])
                    request.ClearField("generation")
                    digest = hashlib.sha256(request.SerializeToString(deterministic=True)).digest()
                    if digest != shard.receipts[name].digest:
                        raise ValueError("Journal does not match committed shard receipt")
                if shard.worker_generations[name] > coordinator.generations[name]:
                    raise ValueError("Shard generation exceeds coordinator reservation")
        for name, worker in coordinator.workers.items():
            if worker.step > journals[name].record.next_step:
                raise ValueError("Coordinator progress exceeds durable worker progress")
    (root / "run.json").write_text(MessageToJson(config), encoding="utf-8")
    return {
        "run_id": config.run_id,
        "global_step": min(journal.record.next_step for journal in journals.values()),
        "shard_versions": versions,
        "optimizer": "sgd",
    }


def export_checkpoint(
    root: Path,
    store: ObjectStore,
    checkpoint_id: str,
    *,
    initial_parameters: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    _manifest_key(checkpoint_id)
    records: dict[str, bytes] = {}
    with ExitStack() as stack:
        path = root / "coordinator" / "coordinator.sqlite"
        if not path.is_file():
            raise ValueError("Missing coordinator database")
        coordinator = _open(stack, root, "coordinator").get("coordinator")
        if coordinator is None:
            raise ValueError("Missing coordinator record")
        records["coordinator"] = coordinator
        roles = _roles(_config(coordinator))
        stores = {}
        for role in roles:
            if role == "coordinator":
                continue
            if not (root / role / f"{role}.sqlite").is_file():
                raise ValueError(f"Missing {role} database")
            stores[role] = _open(stack, root, role)
        for role, storage in stores.items():
            payload = storage.get(roles[role])
            if payload is None:
                raise ValueError(f"Missing {role} record")
            records[role] = payload
        # Hold every exclusive process lease while reading the complete cut.
        if sum(map(len, records.values())) > MAX_BUNDLE_BYTES:
            raise ValueError("Checkpoint bundle exceeds size limit")
        with tempfile.TemporaryDirectory() as temporary:
            summary = _validate(records, Path(temporary), initial_parameters)
    return _publish_checkpoint(records, store, checkpoint_id, summary, started)


def _publish_checkpoint(
    records: dict[str, bytes],
    store: ObjectStore,
    checkpoint_id: str,
    summary: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    key = _manifest_key(checkpoint_id)
    entries = []
    for role, payload in sorted(records.items()):
        digest = hashlib.sha256(payload).hexdigest()
        object_key = f"blobs/{digest}"
        store.put(object_key, payload)
        entries.append({"role": role, "key": object_key, "sha256": digest, "size": len(payload)})
    manifest = {"format_version": 1, "checkpoint_id": checkpoint_id, **summary, "records": entries}
    store.put(key, json.dumps(manifest, sort_keys=True, allow_nan=False).encode())
    telemetry.observe("checkpoint_duration_seconds", time.perf_counter() - started)
    emit(
        "checkpoint_completed",
        run_id=summary["run_id"],
        checkpoint_id=checkpoint_id,
        step=summary["global_step"],
        shard_versions=summary["shard_versions"],
        duration_seconds=time.perf_counter() - started,
    )
    return manifest


def export_online_checkpoint(
    coordinator_address: str,
    store: ObjectStore,
    checkpoint_id: str,
    security: RpcSecurity,
    *,
    timeout: float = 120,
    initial_parameters: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    """Quiesce the configured workers, freeze shards and publish one live cut."""
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", checkpoint_id)
    ):
        raise ValueError("Checkpoint ID and timeout are invalid")
    started = time.perf_counter()
    with open_channel(coordinator_address, security, admin=True) as channel:
        coordinator = rpc.CoordinatorStub(channel)
        run = coordinator.GetStatus(pb.Empty(), timeout=timeout)
        request = pb.CheckpointRequest(run_id=run.config.run_id, checkpoint_id=checkpoint_id)
        status = coordinator.BeginCheckpoint(request, timeout=timeout)
        if status.control.checkpoint_id != checkpoint_id:
            raise ValueError("Checkpoint coordinator reserved a different ID")
        if status.committed and status.control.phase == pb.CHECKPOINT_RUNNING:
            return cast(
                dict[str, Any], json.loads(store.get(_manifest_key(checkpoint_id), 64 * 1024))
            )
        if status.control.phase in (pb.CHECKPOINT_ABORTING, pb.CHECKPOINT_RUNNING):
            raise RuntimeError("Checkpoint epoch is aborted or cannot be resumed; use a new ID")
        deadline = time.monotonic() + timeout
        while (
            status.control.phase == pb.CHECKPOINT_REQUESTED and not status.all_workers_acknowledged
        ):
            if time.monotonic() >= deadline:
                raise TimeoutError("Workers did not reach the checkpoint safe point before timeout")
            time.sleep(0.05)
            status = coordinator.GetCheckpointStatus(request, timeout=timeout)
        if status.control.phase == pb.CHECKPOINT_REQUESTED:
            for address in run.config.shard_endpoints:
                with open_channel(address, security, admin=True) as shard_channel:
                    rpc.ParameterShardStub(shard_channel).FreezeCheckpoint(
                        pb.ShardCheckpointRequest(
                            run_id=run.config.run_id, epoch=status.control.epoch
                        ),
                        timeout=timeout,
                    )
            status = coordinator.SetCheckpointPhase(
                pb.CheckpointPhaseRequest(
                    run_id=run.config.run_id,
                    epoch=status.control.epoch,
                    phase=pb.CHECKPOINT_FROZEN,
                ),
                timeout=timeout,
            )
        if status.control.phase == pb.CHECKPOINT_FROZEN:
            records: dict[str, bytes] = {}
            frozen = coordinator.GetCheckpointSnapshot(request, timeout=timeout)
            saved = json.loads(frozen.snapshot)
            saved["checkpoint"]["phase"] = pb.CHECKPOINT_RUNNING
            saved["checkpoint"]["committed"] = True
            records["coordinator"] = json.dumps(saved, allow_nan=False).encode()
            for worker in status.workers:
                records[worker.worker_id] = worker.worker_journal
            for index, address in enumerate(run.config.shard_endpoints):
                with open_channel(address, security, admin=True) as shard_channel:
                    snapshot = rpc.ParameterShardStub(shard_channel).ExportCheckpointSnapshot(
                        pb.ShardCheckpointRequest(
                            run_id=run.config.run_id, epoch=status.control.epoch
                        ),
                        timeout=timeout,
                    )
                shard_record = pb.ShardSnapshot.FromString(snapshot.snapshot)
                shard_record.checkpoint_frozen = False
                records[f"shard-{index}"] = shard_record.SerializeToString(deterministic=True)
            if sum(map(len, records.values())) > MAX_BUNDLE_BYTES:
                raise ValueError("Checkpoint bundle exceeds size limit")
            with tempfile.TemporaryDirectory() as temporary:
                summary = _validate(records, Path(temporary), initial_parameters)
            _publish_checkpoint(records, store, checkpoint_id, summary, started)
            status = coordinator.SetCheckpointPhase(
                pb.CheckpointPhaseRequest(
                    run_id=run.config.run_id,
                    epoch=status.control.epoch,
                    phase=pb.CHECKPOINT_COMMITTED,
                ),
                timeout=timeout,
            )
        if status.control.phase in (pb.CHECKPOINT_COMMITTED, pb.CHECKPOINT_RESUMING):
            for address in run.config.shard_endpoints:
                with open_channel(address, security, admin=True) as shard_channel:
                    rpc.ParameterShardStub(shard_channel).UnfreezeCheckpoint(
                        pb.ShardCheckpointRequest(
                            run_id=run.config.run_id, epoch=status.control.epoch
                        ),
                        timeout=timeout,
                    )
            if status.control.phase == pb.CHECKPOINT_COMMITTED:
                status = coordinator.SetCheckpointPhase(
                    pb.CheckpointPhaseRequest(
                        run_id=run.config.run_id,
                        epoch=status.control.epoch,
                        phase=pb.CHECKPOINT_RESUMING,
                    ),
                    timeout=timeout,
                )
            coordinator.SetCheckpointPhase(
                pb.CheckpointPhaseRequest(
                    run_id=run.config.run_id,
                    epoch=status.control.epoch,
                    phase=pb.CHECKPOINT_RUNNING,
                ),
                timeout=timeout,
            )
        return cast(dict[str, Any], json.loads(store.get(_manifest_key(checkpoint_id), 64 * 1024)))


def abort_online_checkpoint(
    coordinator_address: str,
    checkpoint_id: str,
    security: RpcSecurity,
    *,
    timeout: float = 120,
) -> None:
    """Release a failed pre-commit epoch only after every shard confirms unfreeze."""
    with open_channel(coordinator_address, security, admin=True) as channel:
        coordinator = rpc.CoordinatorStub(channel)
        run = coordinator.GetStatus(pb.Empty(), timeout=timeout)
        request = pb.CheckpointRequest(run_id=run.config.run_id, checkpoint_id=checkpoint_id)
        status = coordinator.GetCheckpointStatus(request, timeout=timeout)
        if status.control.checkpoint_id != checkpoint_id or status.control.epoch == 0:
            raise ValueError("Checkpoint ID does not identify an active or completed epoch")
        if status.committed:
            if status.control.phase == pb.CHECKPOINT_RUNNING:
                return
            raise ValueError("A committed checkpoint must be resumed, not aborted")
        if status.control.phase == pb.CHECKPOINT_RUNNING:
            return
        if status.control.phase != pb.CHECKPOINT_ABORTING:
            status = coordinator.SetCheckpointPhase(
                pb.CheckpointPhaseRequest(
                    run_id=run.config.run_id,
                    epoch=status.control.epoch,
                    phase=pb.CHECKPOINT_ABORTING,
                ),
                timeout=timeout,
            )
        for address in run.config.shard_endpoints:
            with open_channel(address, security, admin=True) as shard_channel:
                rpc.ParameterShardStub(shard_channel).UnfreezeCheckpoint(
                    pb.ShardCheckpointRequest(run_id=run.config.run_id, epoch=status.control.epoch),
                    timeout=timeout,
                )
        coordinator.SetCheckpointPhase(
            pb.CheckpointPhaseRequest(
                run_id=run.config.run_id,
                epoch=status.control.epoch,
                phase=pb.CHECKPOINT_RUNNING,
            ),
            timeout=timeout,
        )


def _read(store: ObjectStore, checkpoint_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest: dict[str, Any] = json.loads(store.get(_manifest_key(checkpoint_id), 64 * 1024))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format_version") != 1
        or manifest.get("checkpoint_id") != checkpoint_id
    ):
        raise ValueError("Unsupported checkpoint manifest")
    entries = manifest["records"]
    if not isinstance(entries, list) or not 3 <= len(entries) <= 81:
        raise ValueError("Invalid checkpoint record count")
    records = {}
    total = 0
    for entry in entries:
        digest, role = entry["sha256"], entry["role"]
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or entry["key"] != f"blobs/{digest}"
            or not isinstance(role, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", role)
            or role in records
        ):
            raise ValueError("Invalid checkpoint record")
        payload = store.get(entry["key"])
        total += len(payload)
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Checkpoint bundle exceeds size limit")
        if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("Checkpoint checksum or size mismatch")
        records[role] = payload
    if "coordinator" not in records:
        raise ValueError("Missing coordinator record")
    return manifest, records


def restore_checkpoint(
    store: ObjectStore,
    checkpoint_id: str,
    destination: Path,
    *,
    initial_parameters: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    manifest, records = _read(store, checkpoint_id)
    if destination.exists():
        raise FileExistsError(
            "Restore requires a fresh destination; existing state is never replaced"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".paramesh-restore-", dir=destination.parent
    ) as temporary:
        staging = Path(temporary) / "cluster"
        staging.mkdir()
        summary = _validate(records, staging, initial_parameters)
        if any(manifest.get(key) != value for key, value in summary.items()):
            raise ValueError("Manifest summary does not match checkpoint records")
        os.rename(staging, destination)
    return manifest


def install_checkpoint(
    store: ObjectStore,
    checkpoint_id: str,
    root: Path,
    *,
    initial_parameters: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    """Install into empty mounted volumes, keeping startup blocked until all roles are ready."""
    manifest, records = _read(store, checkpoint_id)
    with tempfile.TemporaryDirectory() as temporary:
        summary = _validate(records, Path(temporary), initial_parameters)
    if any(manifest.get(key) != value for key, value in summary.items()):
        raise ValueError("Manifest summary does not match checkpoint records")
    roles = _roles(_config(records["coordinator"]))
    for role in roles:
        directory = root / role
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError("Install requires empty volumes for every role")
    markers = []
    for role in roles:
        directory = root / role
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / ".restore-incomplete"
        with marker.open("xb") as stream:
            stream.write(checkpoint_id.encode())
            stream.flush()
            os.fsync(stream.fileno())
        markers.append(marker)
    with ExitStack() as stack:
        stores = {role: _open(stack, root, role) for role in roles}
        for role, record_key in roles.items():
            stores[role].put(record_key, records[role])
    # The coordinator cannot admit workers until every other role has been installed.
    for marker in reversed(markers):
        marker.unlink()
    return manifest

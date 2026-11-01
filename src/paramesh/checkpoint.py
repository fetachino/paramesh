"""Offline whole-run checkpoints, including journals for partially delivered steps."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToJson

from paramesh.config import validate_config
from paramesh.coordinator import Coordinator
from paramesh.journal import Journal
from paramesh.rpc import training_pb2 as pb
from paramesh.shard import ParameterShard
from paramesh.state import StateDB
from paramesh.storage import ObjectStore
from paramesh.tensors import partition

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


def _validate(records: dict[str, bytes], root: Path) -> dict[str, Any]:
    from paramesh.workload import parameters

    config = _config(records["coordinator"])
    roles = _roles(config)
    if records.keys() != roles.keys():
        raise ValueError("Checkpoint membership is incomplete or unexpected")
    initial = parameters()
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


def export_checkpoint(root: Path, store: ObjectStore, checkpoint_id: str) -> dict[str, Any]:
    key = _manifest_key(checkpoint_id)
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
            summary = _validate(records, Path(temporary))
    entries = []
    for role, payload in sorted(records.items()):
        digest = hashlib.sha256(payload).hexdigest()
        object_key = f"blobs/{digest}"
        store.put(object_key, payload)
        entries.append({"role": role, "key": object_key, "sha256": digest, "size": len(payload)})
    manifest = {"format_version": 1, "checkpoint_id": checkpoint_id, **summary, "records": entries}
    store.put(key, json.dumps(manifest, sort_keys=True, allow_nan=False).encode())
    return manifest


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


def restore_checkpoint(store: ObjectStore, checkpoint_id: str, destination: Path) -> dict[str, Any]:
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
        summary = _validate(records, staging)
        if any(manifest.get(key) != value for key, value in summary.items()):
            raise ValueError("Manifest summary does not match checkpoint records")
        os.rename(staging, destination)
    return manifest


def install_checkpoint(store: ObjectStore, checkpoint_id: str, root: Path) -> dict[str, Any]:
    """Install into empty mounted volumes, keeping startup blocked until all roles are ready."""
    manifest, records = _read(store, checkpoint_id)
    with tempfile.TemporaryDirectory() as temporary:
        summary = _validate(records, Path(temporary))
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

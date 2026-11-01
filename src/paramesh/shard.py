"""Atomic shard-local SGD with fixed-membership barriers and replay protection."""

import hashlib
import threading
import time
from dataclasses import dataclass

import numpy as np

from paramesh.config import copy_config, validate_config
from paramesh.rpc import training_pb2 as pb
from paramesh.state import StateDB
from paramesh.tensors import FloatArray, decode_many, encode


@dataclass(frozen=True)
class Receipt:
    step: int
    digest: bytes
    version: int
    staleness: int


class StaleGradientError(ValueError):
    """A worker must refresh and recompute before retrying this shard."""


class ParameterShard:
    def __init__(
        self,
        config: pb.RunConfig,
        parameters: dict[str, FloatArray],
        *,
        state: StateDB | None = None,
    ) -> None:
        validate_config(config)
        self.config = copy_config(config)
        # Validate initial state with exactly the same rules as the wire format.
        self.parameters = decode_many(encode(name, value) for name, value in parameters.items())
        self.version = 0
        self.receipts: dict[str, Receipt] = {}
        self.pending: dict[str, tuple[pb.GradientUpdate, bytes, dict[str, FloatArray]]] = {}
        self.condition = threading.Condition()
        self.barrier_generation = 0
        self.barrier_deadline = 0.0
        self.state = state
        self.worker_generations = {name: 0 for name in config.worker_ids}
        self.config_fingerprint = hashlib.sha256(
            config.SerializeToString(deterministic=True)
        ).digest()
        self.model_fingerprint = hashlib.sha256(
            b"".join(
                encode(name, value).SerializeToString(deterministic=True)
                for name, value in sorted(self.parameters.items())
            )
        ).digest()
        persisted = state.get("shard") if state is not None else None
        if persisted is not None:
            self._restore(persisted)
        else:
            self._save(self.parameters, self.receipts, self.version)

    def _snapshot(
        self, parameters: dict[str, FloatArray], receipts: dict[str, Receipt], version: int
    ) -> pb.ShardSnapshot:
        return pb.ShardSnapshot(
            format_version=1,
            config_fingerprint=self.config_fingerprint,
            model_fingerprint=self.model_fingerprint,
            optimizer="sgd",
            version=version,
            parameters=[encode(name, value) for name, value in sorted(parameters.items())],
            receipts=[
                pb.UpdateReceipt(
                    worker_id=name,
                    step=value.step,
                    digest=value.digest,
                    version=value.version,
                    staleness=value.staleness,
                )
                for name, value in sorted(receipts.items())
            ],
            worker_generations=self.worker_generations,
        )

    def _save(
        self, parameters: dict[str, FloatArray], receipts: dict[str, Receipt], version: int
    ) -> None:
        if self.state is not None:
            self.state.put(
                "shard",
                self._snapshot(parameters, receipts, version).SerializeToString(deterministic=True),
            )

    def _restore(self, payload: bytes) -> None:
        snapshot = pb.ShardSnapshot()
        snapshot.ParseFromString(payload)
        if snapshot.format_version != 1 or snapshot.optimizer != "sgd":
            raise ValueError("Unsupported shard snapshot format or optimizer")
        if snapshot.config_fingerprint != self.config_fingerprint:
            raise ValueError("Stored shard configuration does not match this run")
        if snapshot.model_fingerprint != self.model_fingerprint:
            raise ValueError("Stored shard model does not match initial manifest")
        restored = decode_many(snapshot.parameters)
        if restored.keys() != self.parameters.keys() or any(
            restored[name].shape != value.shape for name, value in self.parameters.items()
        ):
            raise ValueError("Stored parameter manifest is inconsistent")
        receipts: dict[str, Receipt] = {}
        for entry in snapshot.receipts:
            if (
                entry.worker_id not in self.config.worker_ids
                or entry.worker_id in receipts
                or len(entry.digest) != 32
                or entry.version > snapshot.version
            ):
                raise ValueError("Stored receipt is invalid")
            receipts[entry.worker_id] = Receipt(
                entry.step, entry.digest, entry.version, entry.staleness
            )
        if set(snapshot.worker_generations) != set(self.config.worker_ids):
            raise ValueError("Stored worker generations do not match membership")
        self.parameters = restored
        self.receipts = receipts
        self.version = snapshot.version
        self.worker_generations = dict(snapshot.worker_generations)

    def pull(self, run_id: str) -> pb.Parameters:
        if run_id != self.config.run_id:
            raise ValueError("Wrong run ID")
        with self.condition:
            return pb.Parameters(
                version=self.version,
                tensors=[encode(name, value) for name, value in sorted(self.parameters.items())],
            )

    def _validate(self, request: pb.GradientUpdate) -> dict[str, FloatArray]:
        if request.run_id != self.config.run_id:
            raise ValueError("Wrong run ID")
        if request.worker_id not in self.config.worker_ids:
            raise ValueError("Worker is outside configured membership")
        gradients = decode_many(request.tensors)
        if gradients.keys() != self.parameters.keys():
            raise ValueError("Gradient parameter identities do not match this shard")
        if any(gradients[name].shape != value.shape for name, value in self.parameters.items()):
            raise ValueError("Gradient tensor shape does not match parameter")
        return gradients

    def _apply(
        self,
        contributions: list[dict[str, FloatArray]],
        updates: list[tuple[pb.GradientUpdate, bytes, int]],
    ) -> None:
        with np.errstate(over="ignore", invalid="ignore"):
            # Float64 accumulation avoids overflowing otherwise valid float32 means.
            proposed = {
                name: (
                    value.astype(np.float64)
                    - self.config.learning_rate
                    * sum(gradient[name].astype(np.float64) for gradient in contributions)
                    / (len(contributions) if self.config.aggregation == pb.MEAN else 1)
                ).astype(np.float32)
                for name, value in self.parameters.items()
            }
        if any(not np.isfinite(value).all() for value in proposed.values()):
            raise ValueError("Optimizer result must remain finite")
        version = self.version + 1
        receipts = self.receipts.copy()
        for request, digest, staleness in updates:
            receipts[request.worker_id] = Receipt(request.step, digest, version, staleness)
        self._save(proposed, receipts, version)
        self.parameters, self.receipts, self.version = proposed, receipts, version

    def push(self, request: pb.GradientUpdate, *, timeout: float | None = None) -> pb.UpdateResult:
        gradients = self._validate(request)
        digest = hashlib.sha256(request.SerializeToString(deterministic=True)).digest()
        with self.condition:
            previous = self.receipts.get(request.worker_id)
            if previous and request.step == previous.step:
                if digest != previous.digest:
                    raise ValueError("Same worker step was retried with different contents")
                return pb.UpdateResult(
                    version=previous.version, staleness=previous.staleness, duplicate=True
                )
            expected_step = previous.step + 1 if previous else 0
            if request.step != expected_step:
                raise ValueError("Worker step violates the update sequence")
            if request.base_version > self.version:
                raise ValueError("Gradient references a future parameter version")
            staleness = self.version - request.base_version
            if self.config.mode == pb.SYNCHRONOUS and staleness != 0:
                raise ValueError("Synchronous gradient must reference the current version")
            if self.config.mode == pb.BOUNDED_STALENESS and staleness > self.config.max_staleness:
                raise StaleGradientError("Gradient is too stale; refresh parameters and recompute")
            if self.config.mode == pb.SYNCHRONOUS:
                return self._synchronize(request, digest, gradients, timeout)
            self._apply([gradients], [(request, digest, staleness)])
            return pb.UpdateResult(version=self.version, staleness=staleness)

    def _synchronize(
        self,
        request: pb.GradientUpdate,
        digest: bytes,
        gradients: dict[str, FloatArray],
        timeout: float | None,
    ) -> pb.UpdateResult:
        now = time.monotonic()
        limit = self.config.barrier_timeout_seconds
        incoming_deadline = now + (min(limit, timeout) if timeout is not None else limit)
        if not self.pending:
            self.barrier_deadline = incoming_deadline
        else:
            self.barrier_deadline = min(self.barrier_deadline, incoming_deadline)
        if now >= self.barrier_deadline:
            self._abort_barrier()
            raise TimeoutError("Synchronous barrier deadline expired before contribution")
        pending = self.pending.get(request.worker_id)
        if pending and digest != pending[1]:
            raise ValueError("Worker has already contributed different contents to this barrier")
        self.pending[request.worker_id] = (request, digest, gradients)
        generation = self.barrier_generation
        if len(self.pending) == len(self.config.worker_ids):
            try:
                self._apply(
                    [entry[2] for entry in self.pending.values()],
                    [(entry, fingerprint, 0) for entry, fingerprint, _ in self.pending.values()],
                )
            except Exception:
                self._abort_barrier()
                raise
            self.pending.clear()
            self.condition.notify_all()
        else:
            while self.version == request.base_version:
                if generation != self.barrier_generation:
                    raise TimeoutError("Synchronous barrier was aborted; no update committed")
                remaining = self.barrier_deadline - time.monotonic()
                if remaining <= 0:
                    self._abort_barrier()
                    raise TimeoutError("Missing worker at synchronous gradient barrier")
                self.condition.wait(timeout=remaining)
            if generation != self.barrier_generation:
                raise TimeoutError("Synchronous barrier was aborted; no update committed")
        return pb.UpdateResult(version=request.base_version + 1)

    def _abort_barrier(self) -> None:
        self.pending.clear()
        self.barrier_generation += 1
        self.condition.notify_all()

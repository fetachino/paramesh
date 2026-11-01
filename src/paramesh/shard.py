"""Atomic shard-local SGD with fixed-membership barriers and replay protection."""

import hashlib
import threading
import time
from dataclasses import dataclass

import numpy as np

from paramesh.config import copy_config, validate_config
from paramesh.rpc import training_pb2 as pb
from paramesh.tensors import FloatArray, decode_many, encode


@dataclass(frozen=True)
class Receipt:
    step: int
    digest: bytes
    version: int
    staleness: int


class ParameterShard:
    def __init__(self, config: pb.RunConfig, parameters: dict[str, FloatArray]) -> None:
        validate_config(config)
        self.config = copy_config(config)
        # Validate initial state with exactly the same rules as the wire format.
        self.parameters = decode_many(encode(name, value) for name, value in parameters.items())
        self.version = 0
        self.receipts: dict[str, Receipt] = {}
        self.pending: dict[str, tuple[pb.GradientUpdate, bytes, dict[str, FloatArray]]] = {}
        self.condition = threading.Condition()
        self.barrier_generation = 0

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

    def _apply(self, contributions: list[dict[str, FloatArray]]) -> None:
        with np.errstate(over="ignore", invalid="ignore"):
            # Float64 accumulation avoids overflowing otherwise valid float32 means.
            proposed = {
                name: (
                    value.astype(np.float64)
                    - self.config.learning_rate
                    * sum(gradient[name].astype(np.float64) for gradient in contributions)
                    / len(contributions)
                ).astype(np.float32)
                for name, value in self.parameters.items()
            }
        if any(not np.isfinite(value).all() for value in proposed.values()):
            raise ValueError("Optimizer result must remain finite")
        self.parameters = proposed
        self.version += 1

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
                raise ValueError("Gradient is too stale; refresh parameters and recompute")
            if self.config.mode == pb.SYNCHRONOUS:
                return self._synchronize(request, digest, gradients, timeout)
            self._apply([gradients])
            self.receipts[request.worker_id] = Receipt(
                request.step, digest, self.version, staleness
            )
            return pb.UpdateResult(version=self.version, staleness=staleness)

    def _synchronize(
        self,
        request: pb.GradientUpdate,
        digest: bytes,
        gradients: dict[str, FloatArray],
        timeout: float | None,
    ) -> pb.UpdateResult:
        pending = self.pending.get(request.worker_id)
        if pending and digest != pending[1]:
            raise ValueError("Worker has already contributed different contents to this barrier")
        self.pending[request.worker_id] = (request, digest, gradients)
        generation = self.barrier_generation
        if len(self.pending) == len(self.config.worker_ids):
            try:
                self._apply([entry[2] for entry in self.pending.values()])
            except ValueError:
                self._abort_barrier()
                raise
            for entry, fingerprint, _ in self.pending.values():
                self.receipts[entry.worker_id] = Receipt(entry.step, fingerprint, self.version, 0)
            self.pending.clear()
            self.condition.notify_all()
        else:
            limit = self.config.barrier_timeout_seconds
            deadline = time.monotonic() + (min(limit, timeout) if timeout is not None else limit)
            while self.version == request.base_version:
                if generation != self.barrier_generation:
                    raise TimeoutError("Synchronous barrier was aborted; no update committed")
                remaining = deadline - time.monotonic()
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

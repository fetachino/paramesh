"""One-run worker registry with monotonic heartbeat leases."""

import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from paramesh.config import copy_config, validate_config
from paramesh.events import emit
from paramesh.rpc import training_pb2 as pb
from paramesh.state import StateDB


@dataclass
class Worker:
    session_id: str
    last_seen: float
    step: int = 0
    version: int = 0
    acknowledged: bool = False
    completed: bool = False
    generation: int = 0


class WorkerAlreadyRegistered(ValueError):
    """A replacement must wait until the previous incarnation loses its lease."""


class Coordinator:
    def __init__(
        self,
        config: pb.RunConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        suspect_after: float = 5,
        unavailable_after: float = 15,
        state: StateDB | None = None,
        fence: Callable[[str, int], None] | None = None,
    ) -> None:
        validate_config(config)
        if not 0 < suspect_after < unavailable_after:
            raise ValueError("Lease thresholds must be positive and ordered")
        self.config = copy_config(config)
        self.clock = clock
        self.suspect_after = suspect_after
        self.unavailable_after = unavailable_after
        self.config_fingerprint = hashlib.sha256(
            config.SerializeToString(deterministic=True)
        ).digest()
        self.workers: dict[str, Worker] = {}
        self.lost_workers: set[str] = set()
        self.lock = threading.Lock()
        self.storage = state
        self.fence = fence
        self.generations = {name: 0 for name in config.worker_ids}
        self.created_at = time.time()
        self.checkpoint_epoch = 0
        self.checkpoint_id = ""
        self.checkpoint_phase: pb.CheckpointPhase = pb.CHECKPOINT_RUNNING
        self.checkpoint_committed = False
        self.checkpoint_acks: dict[str, dict[str, Any]] = {}
        payload = state.get("coordinator") if state is not None else None
        if payload is not None:
            saved = json.loads(payload)
            if saved.get("format_version") != 1 or saved.get("config") != (
                config.SerializeToString(deterministic=True).hex()
            ):
                raise ValueError("Stored coordinator configuration does not match this run")
            generations = saved["generations"]
            if set(generations) != set(config.worker_ids) or any(
                not isinstance(value, int) or not 0 <= value < 2**64
                for value in generations.values()
            ):
                raise ValueError("Stored worker generations are invalid")
            self.generations = generations
            self.created_at = saved["created_at"]
            checkpoint = saved.get("checkpoint", {})
            self.checkpoint_epoch = checkpoint.get("epoch", 0)
            self.checkpoint_id = checkpoint.get("checkpoint_id", "")
            self.checkpoint_phase = checkpoint.get("phase", pb.CHECKPOINT_RUNNING)
            self.checkpoint_committed = checkpoint.get("committed", False)
            if (
                type(self.checkpoint_epoch) is not int
                or self.checkpoint_epoch < 0
                or self.checkpoint_phase not in pb.CheckpointPhase.values()
                or (self.checkpoint_epoch == 0) != (not self.checkpoint_id)
                or type(self.checkpoint_committed) is not bool
            ):
                raise ValueError("Stored checkpoint epoch state is invalid")
            self.checkpoint_acks = checkpoint.get("workers", {})
            if set(self.checkpoint_acks) - set(config.worker_ids):
                raise ValueError("Stored checkpoint acknowledgment is outside membership")
            for name, worker in saved["workers"].items():
                if name not in self.generations:
                    raise ValueError("Stored worker is outside configured membership")
                self.workers[name] = Worker(
                    session_id="",
                    last_seen=self.clock() - unavailable_after,
                    step=worker["step"],
                    version=worker["version"],
                    completed=worker["completed"],
                    generation=self.generations[name],
                )
        else:
            self._save(self.workers, self.generations)
            emit("training_started", run_id=config.run_id, mode=pb.SyncMode.Name(config.mode))

    def _checkpoint_record(self) -> dict[str, Any]:
        return {
            "epoch": self.checkpoint_epoch,
            "checkpoint_id": self.checkpoint_id,
            "phase": self.checkpoint_phase,
            "committed": self.checkpoint_committed,
            "workers": self.checkpoint_acks,
        }

    def _save(
        self,
        workers: dict[str, Worker],
        generations: dict[str, int],
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        if self.storage is not None:
            self.storage.put(
                "coordinator",
                json.dumps(
                    {
                        "format_version": 1,
                        "config": self.config.SerializeToString(deterministic=True).hex(),
                        "created_at": self.created_at,
                        "generations": generations,
                        "workers": {
                            name: {
                                "step": item.step,
                                "version": item.version,
                                "completed": item.completed,
                            }
                            for name, item in workers.items()
                        },
                        "checkpoint": (
                            checkpoint if checkpoint is not None else self._checkpoint_record()
                        ),
                    },
                    allow_nan=False,
                ).encode(),
            )

    def _state(self, worker_id: str, worker: Worker) -> pb.WorkerState:
        age = max(0, self.clock() - worker.last_seen)
        if worker.completed:
            health = "completed"
        elif age >= self.unavailable_after:
            health = "unavailable"
        elif age >= self.suspect_after:
            health = "suspect"
        else:
            health = "healthy" if worker.acknowledged else "registered"
        return pb.WorkerState(
            worker_id=worker_id,
            health=health,
            step=worker.step,
            parameter_version=worker.version,
            heartbeat_age_seconds=age,
            generation=worker.generation,
            checkpoint_epoch=self.checkpoint_epoch,
            checkpoint_id=self.checkpoint_id,
            checkpoint_phase=pb.CheckpointPhase.Name(self.checkpoint_phase),
            checkpoint_committed=self.checkpoint_committed,
        )

    def begin_checkpoint(self, checkpoint_id: str) -> pb.CheckpointEpochStatus:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", checkpoint_id):
            raise ValueError("Checkpoint ID must be a safe identifier")
        with self.lock:
            if self.checkpoint_phase != pb.CHECKPOINT_RUNNING:
                if checkpoint_id == self.checkpoint_id:
                    return self._checkpoint_status()
                raise RuntimeError("A checkpoint epoch is already in progress")
            if checkpoint_id == self.checkpoint_id and self.checkpoint_epoch > 0:
                if self.checkpoint_committed:
                    return self._checkpoint_status()
                raise ValueError("An aborted checkpoint ID cannot be reused")
            if any(
                name not in self.workers
                or self.workers[name].completed
                or self._state(name, self.workers[name]).health != "healthy"
                for name in self.config.worker_ids
            ):
                raise RuntimeError("Every configured worker must be active with a healthy lease")
            proposed = {
                "epoch": self.checkpoint_epoch + 1,
                "checkpoint_id": checkpoint_id,
                "phase": pb.CHECKPOINT_REQUESTED,
                "workers": {},
            }
            self._save(self.workers, self.generations, proposed)
            self.checkpoint_epoch += 1
            self.checkpoint_id = checkpoint_id
            self.checkpoint_phase = pb.CHECKPOINT_REQUESTED
            self.checkpoint_committed = False
            self.checkpoint_acks = {}
            return self._checkpoint_status()

    def _checkpoint_status(self) -> pb.CheckpointEpochStatus:
        workers = [
            pb.CheckpointWorkerRecord(
                worker_id=name,
                generation=int(record["generation"]),
                step=int(record["step"]),
                worker_journal=bytes.fromhex(str(record["worker_journal"])),
            )
            for name, record in sorted(self.checkpoint_acks.items())
        ]
        return pb.CheckpointEpochStatus(
            control=pb.CheckpointControl(
                epoch=self.checkpoint_epoch,
                checkpoint_id=self.checkpoint_id,
                phase=self.checkpoint_phase,
                committed=self.checkpoint_committed,
            ),
            all_workers_acknowledged=(
                self.checkpoint_epoch > 0
                and set(self.checkpoint_acks) == set(self.config.worker_ids)
                and all(
                    int(self.checkpoint_acks[name]["generation"]) == self.generations[name]
                    for name in self.config.worker_ids
                )
            ),
            workers=workers,
            committed=self.checkpoint_committed,
        )

    def checkpoint_status(self) -> pb.CheckpointEpochStatus:
        with self.lock:
            return self._checkpoint_status()

    def checkpoint_control(self, worker_id: str) -> pb.CheckpointControl:
        if worker_id not in self.config.worker_ids:
            raise ValueError("Worker is outside configured membership")
        with self.lock:
            return pb.CheckpointControl(
                epoch=self.checkpoint_epoch,
                checkpoint_id=self.checkpoint_id,
                phase=self.checkpoint_phase,
                committed=self.checkpoint_committed,
            )

    def checkpoint_snapshot(self, checkpoint_id: str) -> pb.CheckpointSnapshot:
        with self.lock:
            if (
                checkpoint_id != self.checkpoint_id
                or self.checkpoint_phase != pb.CHECKPOINT_FROZEN
                or not self._checkpoint_status().all_workers_acknowledged
            ):
                raise RuntimeError("Coordinator is not frozen for this checkpoint")
            if self.storage is None:
                raise RuntimeError("Online checkpoint snapshots require durable coordinator state")
            payload = self.storage.get("coordinator")
            if payload is None:
                raise RuntimeError("Durable coordinator snapshot is missing")
            return pb.CheckpointSnapshot(snapshot=payload)

    def acknowledge_checkpoint(self, request: pb.CheckpointAck) -> pb.CheckpointEpochStatus:
        if request.run_id != self.config.run_id or request.worker_id not in self.config.worker_ids:
            raise ValueError("Wrong run or worker ID")
        journal = pb.WorkerJournal()
        try:
            journal.ParseFromString(request.worker_journal)
        except Exception as error:
            raise ValueError("Checkpoint worker journal is invalid") from error
        if (
            journal.format_version != 1
            or journal.config_fingerprint != self.config_fingerprint
            or journal.worker_id != request.worker_id
            or journal.next_step != request.step
            or journal.requests
        ):
            raise ValueError("Checkpoint acknowledgment requires an empty matching worker journal")
        with self.lock:
            if (
                self.checkpoint_phase != pb.CHECKPOINT_REQUESTED
                or request.epoch != self.checkpoint_epoch
            ):
                raise ValueError("Checkpoint epoch is not accepting worker acknowledgments")
            worker = self.workers.get(request.worker_id)
            if (
                worker is None
                or worker.session_id != request.session_id
                or worker.generation != self.generations[request.worker_id]
                or worker.completed
                or self._state(request.worker_id, worker).health == "unavailable"
            ):
                raise PermissionError("Checkpoint acknowledgment session is invalid or expired")
            if request.step < worker.step or request.parameter_version < worker.version:
                raise ValueError("Checkpoint progress cannot move backwards")
            record = {
                "generation": worker.generation,
                "step": request.step,
                "worker_journal": request.worker_journal.hex(),
            }
            previous = self.checkpoint_acks.get(request.worker_id)
            if previous is not None and previous != record:
                raise ValueError("Worker already acknowledged different checkpoint state")
            updated = replace(
                worker,
                last_seen=self.clock(),
                step=request.step,
                version=request.parameter_version,
                acknowledged=True,
            )
            workers = self.workers | {request.worker_id: updated}
            acknowledgments = self.checkpoint_acks | {request.worker_id: record}
            checkpoint = self._checkpoint_record() | {"workers": acknowledgments}
            self._save(workers, self.generations, checkpoint)
            self.workers = workers
            self.checkpoint_acks = acknowledgments
            return self._checkpoint_status()

    def set_checkpoint_phase(
        self, epoch: int, phase: pb.CheckpointPhase
    ) -> pb.CheckpointEpochStatus:
        transitions = {
            pb.CHECKPOINT_REQUESTED: {pb.CHECKPOINT_FROZEN, pb.CHECKPOINT_ABORTING},
            pb.CHECKPOINT_FROZEN: {pb.CHECKPOINT_COMMITTED, pb.CHECKPOINT_ABORTING},
            pb.CHECKPOINT_COMMITTED: {pb.CHECKPOINT_RESUMING},
            pb.CHECKPOINT_RESUMING: {pb.CHECKPOINT_RUNNING},
            pb.CHECKPOINT_ABORTING: {pb.CHECKPOINT_RUNNING},
        }
        if phase not in pb.CheckpointPhase.values():
            raise ValueError("Unknown checkpoint phase")
        with self.lock:
            if epoch != self.checkpoint_epoch:
                raise ValueError("Checkpoint epoch does not match the active epoch")
            if phase == self.checkpoint_phase:
                return self._checkpoint_status()
            if phase not in transitions.get(self.checkpoint_phase, set()):
                raise ValueError("Checkpoint phase transition is invalid")
            if (
                phase == pb.CHECKPOINT_FROZEN
                and not self._checkpoint_status().all_workers_acknowledged
            ):
                raise RuntimeError("All configured workers must acknowledge before shard freeze")
            checkpoint = self._checkpoint_record() | {"phase": phase}
            if phase == pb.CHECKPOINT_COMMITTED:
                checkpoint["committed"] = True
            self._save(self.workers, self.generations, checkpoint)
            self.checkpoint_phase = phase
            if phase == pb.CHECKPOINT_COMMITTED:
                self.checkpoint_committed = True
            return self._checkpoint_status()

    def register(self, worker_id: str, protocol_version: int) -> pb.WorkerSession:
        if protocol_version != 1:
            raise ValueError("Unsupported protocol version; expected 1")
        if worker_id not in self.config.worker_ids:
            raise ValueError("Worker is outside configured membership")
        with self.lock:
            if self.checkpoint_phase != pb.CHECKPOINT_RUNNING:
                raise RuntimeError("Worker registration is blocked by a checkpoint epoch")
            previous = self.workers.get(worker_id)
            if previous and self._state(worker_id, previous).health not in (
                "unavailable",
                "completed",
            ):
                raise WorkerAlreadyRegistered("Worker ID is already registered with a live lease")
            generation = self.generations[worker_id] + 1
            generations = self.generations | {worker_id: generation}
            # A partial fence must never reuse a durably reserved generation.
            self._save(self.workers, generations)
            self.generations = generations
            if self.fence is not None:
                self.fence(worker_id, generation)
            worker = Worker(
                session_id=uuid.uuid4().hex,
                last_seen=self.clock(),
                generation=generation,
                step=previous.step if previous else 0,
                version=previous.version if previous else 0,
            )
            workers = self.workers | {worker_id: worker}
            self._save(workers, self.generations)
            self.workers = workers
            self.lost_workers.discard(worker_id)
            emit(
                "worker_recovered" if generation > 1 else "worker_joined",
                run_id=self.config.run_id,
                worker_id=worker_id,
                generation=generation,
                step=worker.step,
            )
            return pb.WorkerSession(
                session_id=worker.session_id, config=self.config, generation=generation
            )

    def heartbeat(self, request: pb.HeartbeatRequest) -> pb.WorkerState:
        if request.run_id != self.config.run_id:
            raise ValueError("Wrong run ID")
        with self.lock:
            worker = self.workers.get(request.worker_id)
            if (
                worker is None
                or worker.session_id != request.session_id
                or self._state(request.worker_id, worker).health == "unavailable"
                or (worker.completed and not request.completed)
            ):
                raise PermissionError("Session is unknown, expired or superseded; re-register")
            if request.step < worker.step or request.parameter_version < worker.version:
                raise ValueError("Heartbeat progress cannot move backwards")
            updated = replace(
                worker,
                last_seen=self.clock(),
                step=request.step,
                version=request.parameter_version,
                acknowledged=True,
                completed=request.completed,
            )
            workers = self.workers | {request.worker_id: updated}
            self._save(workers, self.generations)
            self.workers = workers
            if (
                request.completed
                and not worker.completed
                and len(workers) == len(self.config.worker_ids)
                and all(item.completed for item in workers.values())
            ):
                emit(
                    "training_completed",
                    run_id=self.config.run_id,
                    step=min(item.step for item in workers.values()),
                )
            return self._state(request.worker_id, updated)

    def status(self) -> pb.RunStatus:
        with self.lock:
            for name, worker in self.workers.items():
                if (
                    self._state(name, worker).health == "unavailable"
                    and name not in self.lost_workers
                ):
                    self.lost_workers.add(name)
                    emit(
                        "worker_lost",
                        run_id=self.config.run_id,
                        worker_id=name,
                        step=worker.step,
                        generation=worker.generation,
                    )
            return pb.RunStatus(
                config=self.config,
                global_step=min(
                    (
                        self.workers[name].step if name in self.workers else 0
                        for name in self.config.worker_ids
                    ),
                    default=0,
                ),
                workers=[
                    self._state(name, worker) for name, worker in sorted(self.workers.items())
                ],
            )

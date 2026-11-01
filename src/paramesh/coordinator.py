"""One-run worker registry with monotonic heartbeat leases."""

import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

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
        self.workers: dict[str, Worker] = {}
        self.lost_workers: set[str] = set()
        self.lock = threading.Lock()
        self.storage = state
        self.fence = fence
        self.generations = {name: 0 for name in config.worker_ids}
        self.created_at = time.time()
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

    def _save(self, workers: dict[str, Worker], generations: dict[str, int]) -> None:
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
        )

    def register(self, worker_id: str, protocol_version: int) -> pb.WorkerSession:
        if protocol_version != 1:
            raise ValueError("Unsupported protocol version; expected 1")
        if worker_id not in self.config.worker_ids:
            raise ValueError("Worker is outside configured membership")
        with self.lock:
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

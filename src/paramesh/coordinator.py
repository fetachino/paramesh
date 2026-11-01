"""One-run worker registry with monotonic heartbeat leases."""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from paramesh.config import copy_config, validate_config
from paramesh.rpc import training_pb2 as pb


@dataclass
class Worker:
    session_id: str
    last_seen: float
    step: int = 0
    version: int = 0
    acknowledged: bool = False
    completed: bool = False


class Coordinator:
    def __init__(
        self,
        config: pb.RunConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        suspect_after: float = 5,
        unavailable_after: float = 15,
    ) -> None:
        validate_config(config)
        if not 0 < suspect_after < unavailable_after:
            raise ValueError("Lease thresholds must be positive and ordered")
        self.config = copy_config(config)
        self.clock = clock
        self.suspect_after = suspect_after
        self.unavailable_after = unavailable_after
        self.workers: dict[str, Worker] = {}
        self.lock = threading.Lock()

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
        )

    def register(self, worker_id: str, protocol_version: int) -> pb.WorkerSession:
        if protocol_version != 1:
            raise ValueError("Unsupported protocol version; expected 1")
        if worker_id not in self.config.worker_ids:
            raise ValueError("Worker is outside configured membership")
        with self.lock:
            previous = self.workers.get(worker_id)
            if previous and self._state(worker_id, previous).health != "unavailable":
                raise ValueError("Worker ID is already registered with a live lease")
            worker = Worker(session_id=uuid.uuid4().hex, last_seen=self.clock())
            self.workers[worker_id] = worker
            return pb.WorkerSession(session_id=worker.session_id, config=self.config)

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
            worker.last_seen = self.clock()
            worker.step = request.step
            worker.version = request.parameter_version
            worker.acknowledged = True
            worker.completed = request.completed
            return self._state(request.worker_id, worker)

    def status(self) -> pb.RunStatus:
        with self.lock:
            return pb.RunStatus(
                config=self.config,
                workers=[
                    self._state(name, worker) for name, worker in sorted(self.workers.items())
                ],
            )

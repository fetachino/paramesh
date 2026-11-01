"""Write-ahead worker gradients preserve exact unfinished steps across crashes."""

import hashlib
import math

from paramesh.rpc import training_pb2 as pb
from paramesh.state import StateDB
from paramesh.tensors import decode_many


class Journal:
    def __init__(
        self, config: pb.RunConfig, worker_id: str, storage: StateDB | None = None
    ) -> None:
        self.storage = storage
        self.config = config
        self.fingerprint = hashlib.sha256(config.SerializeToString(deterministic=True)).digest()
        self.record = pb.WorkerJournal(
            format_version=1, config_fingerprint=self.fingerprint, worker_id=worker_id
        )
        payload = storage.get("worker") if storage is not None else None
        if payload is not None:
            record = pb.WorkerJournal()
            record.ParseFromString(payload)
            if (
                record.format_version != 1
                or record.config_fingerprint != self.fingerprint
                or record.worker_id != worker_id
            ):
                raise ValueError("Stored worker journal identity does not match this run")
            self._validate(record)
            self.record = record
        else:
            self._write(self.record)

    def _validate(self, record: pb.WorkerJournal) -> None:
        if not math.isfinite(record.loss) or record.loss < 0:
            raise ValueError("Journal loss must be finite and nonnegative")
        if record.requests and len(record.requests) != len(self.config.shard_endpoints):
            raise ValueError("Journal must contain exactly one request per shard")
        for request in record.requests:
            if (
                request.run_id != self.config.run_id
                or request.worker_id != record.worker_id
                or request.step != record.next_step
            ):
                raise ValueError("Journal request run, worker or step is inconsistent")
            decode_many(request.tensors)

    def _write(self, record: pb.WorkerJournal) -> None:
        self._validate(record)
        if self.storage is not None:
            self.storage.put("worker", record.SerializeToString(deterministic=True))
        self.record = record

    def prepare(self, requests: list[pb.GradientUpdate], loss: float) -> None:
        record = pb.WorkerJournal()
        record.CopyFrom(self.record)
        del record.requests[:]
        record.requests.extend(requests)
        record.loss = loss
        self._write(record)

    def complete(self) -> None:
        if not self.record.requests:
            raise ValueError("Cannot complete a step without journaled gradients")
        record = pb.WorkerJournal()
        record.CopyFrom(self.record)
        del record.requests[:]
        record.next_step += 1
        self._write(record)

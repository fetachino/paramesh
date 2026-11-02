from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SyncMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SYNC_MODE_UNSPECIFIED: _ClassVar[SyncMode]
    SYNCHRONOUS: _ClassVar[SyncMode]
    ASYNCHRONOUS: _ClassVar[SyncMode]
    BOUNDED_STALENESS: _ClassVar[SyncMode]

class Aggregation(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MEAN: _ClassVar[Aggregation]
    SUM: _ClassVar[Aggregation]

class CheckpointPhase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHECKPOINT_RUNNING: _ClassVar[CheckpointPhase]
    CHECKPOINT_REQUESTED: _ClassVar[CheckpointPhase]
    CHECKPOINT_FROZEN: _ClassVar[CheckpointPhase]
    CHECKPOINT_COMMITTED: _ClassVar[CheckpointPhase]
    CHECKPOINT_RESUMING: _ClassVar[CheckpointPhase]
    CHECKPOINT_ABORTING: _ClassVar[CheckpointPhase]
SYNC_MODE_UNSPECIFIED: SyncMode
SYNCHRONOUS: SyncMode
ASYNCHRONOUS: SyncMode
BOUNDED_STALENESS: SyncMode
MEAN: Aggregation
SUM: Aggregation
CHECKPOINT_RUNNING: CheckpointPhase
CHECKPOINT_REQUESTED: CheckpointPhase
CHECKPOINT_FROZEN: CheckpointPhase
CHECKPOINT_COMMITTED: CheckpointPhase
CHECKPOINT_RESUMING: CheckpointPhase
CHECKPOINT_ABORTING: CheckpointPhase

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RunConfig(_message.Message):
    __slots__ = ("run_id", "mode", "shard_endpoints", "worker_ids", "max_staleness", "learning_rate", "barrier_timeout_seconds", "aggregation")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    SHARD_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    WORKER_IDS_FIELD_NUMBER: _ClassVar[int]
    MAX_STALENESS_FIELD_NUMBER: _ClassVar[int]
    LEARNING_RATE_FIELD_NUMBER: _ClassVar[int]
    BARRIER_TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    AGGREGATION_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    mode: SyncMode
    shard_endpoints: _containers.RepeatedScalarFieldContainer[str]
    worker_ids: _containers.RepeatedScalarFieldContainer[str]
    max_staleness: int
    learning_rate: float
    barrier_timeout_seconds: float
    aggregation: Aggregation
    def __init__(self, run_id: _Optional[str] = ..., mode: _Optional[_Union[SyncMode, str]] = ..., shard_endpoints: _Optional[_Iterable[str]] = ..., worker_ids: _Optional[_Iterable[str]] = ..., max_staleness: _Optional[int] = ..., learning_rate: _Optional[float] = ..., barrier_timeout_seconds: _Optional[float] = ..., aggregation: _Optional[_Union[Aggregation, str]] = ...) -> None: ...

class RegisterWorkerRequest(_message.Message):
    __slots__ = ("worker_id", "protocol_version")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    protocol_version: int
    def __init__(self, worker_id: _Optional[str] = ..., protocol_version: _Optional[int] = ...) -> None: ...

class WorkerSession(_message.Message):
    __slots__ = ("session_id", "config", "generation")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    config: RunConfig
    generation: int
    def __init__(self, session_id: _Optional[str] = ..., config: _Optional[_Union[RunConfig, _Mapping]] = ..., generation: _Optional[int] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("run_id", "worker_id", "session_id", "step", "parameter_version", "completed")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    PARAMETER_VERSION_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    worker_id: str
    session_id: str
    step: int
    parameter_version: int
    completed: bool
    def __init__(self, run_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., session_id: _Optional[str] = ..., step: _Optional[int] = ..., parameter_version: _Optional[int] = ..., completed: bool = ...) -> None: ...

class WorkerState(_message.Message):
    __slots__ = ("worker_id", "health", "step", "parameter_version", "heartbeat_age_seconds", "generation", "checkpoint_epoch", "checkpoint_id", "checkpoint_phase", "checkpoint_committed")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    PARAMETER_VERSION_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_AGE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_EPOCH_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_PHASE_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_COMMITTED_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    health: str
    step: int
    parameter_version: int
    heartbeat_age_seconds: float
    generation: int
    checkpoint_epoch: int
    checkpoint_id: str
    checkpoint_phase: str
    checkpoint_committed: bool
    def __init__(self, worker_id: _Optional[str] = ..., health: _Optional[str] = ..., step: _Optional[int] = ..., parameter_version: _Optional[int] = ..., heartbeat_age_seconds: _Optional[float] = ..., generation: _Optional[int] = ..., checkpoint_epoch: _Optional[int] = ..., checkpoint_id: _Optional[str] = ..., checkpoint_phase: _Optional[str] = ..., checkpoint_committed: bool = ...) -> None: ...

class RunStatus(_message.Message):
    __slots__ = ("config", "workers", "global_step")
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    WORKERS_FIELD_NUMBER: _ClassVar[int]
    GLOBAL_STEP_FIELD_NUMBER: _ClassVar[int]
    config: RunConfig
    workers: _containers.RepeatedCompositeFieldContainer[WorkerState]
    global_step: int
    def __init__(self, config: _Optional[_Union[RunConfig, _Mapping]] = ..., workers: _Optional[_Iterable[_Union[WorkerState, _Mapping]]] = ..., global_step: _Optional[int] = ...) -> None: ...

class Tensor(_message.Message):
    __slots__ = ("name", "shape", "dtype", "data")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    name: str
    shape: _containers.RepeatedScalarFieldContainer[int]
    dtype: str
    data: bytes
    def __init__(self, name: _Optional[str] = ..., shape: _Optional[_Iterable[int]] = ..., dtype: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class PullRequest(_message.Message):
    __slots__ = ("run_id",)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    def __init__(self, run_id: _Optional[str] = ...) -> None: ...

class Parameters(_message.Message):
    __slots__ = ("version", "tensors")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TENSORS_FIELD_NUMBER: _ClassVar[int]
    version: int
    tensors: _containers.RepeatedCompositeFieldContainer[Tensor]
    def __init__(self, version: _Optional[int] = ..., tensors: _Optional[_Iterable[_Union[Tensor, _Mapping]]] = ...) -> None: ...

class GradientUpdate(_message.Message):
    __slots__ = ("run_id", "worker_id", "step", "base_version", "tensors", "generation")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    BASE_VERSION_FIELD_NUMBER: _ClassVar[int]
    TENSORS_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    worker_id: str
    step: int
    base_version: int
    tensors: _containers.RepeatedCompositeFieldContainer[Tensor]
    generation: int
    def __init__(self, run_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., step: _Optional[int] = ..., base_version: _Optional[int] = ..., tensors: _Optional[_Iterable[_Union[Tensor, _Mapping]]] = ..., generation: _Optional[int] = ...) -> None: ...

class UpdateResult(_message.Message):
    __slots__ = ("version", "staleness", "duplicate")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    STALENESS_FIELD_NUMBER: _ClassVar[int]
    DUPLICATE_FIELD_NUMBER: _ClassVar[int]
    version: int
    staleness: int
    duplicate: bool
    def __init__(self, version: _Optional[int] = ..., staleness: _Optional[int] = ..., duplicate: bool = ...) -> None: ...

class UpdateReceipt(_message.Message):
    __slots__ = ("worker_id", "step", "digest", "version", "staleness")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    DIGEST_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    STALENESS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    step: int
    digest: bytes
    version: int
    staleness: int
    def __init__(self, worker_id: _Optional[str] = ..., step: _Optional[int] = ..., digest: _Optional[bytes] = ..., version: _Optional[int] = ..., staleness: _Optional[int] = ...) -> None: ...

class ShardSnapshot(_message.Message):
    __slots__ = ("format_version", "config_fingerprint", "model_fingerprint", "optimizer", "version", "parameters", "receipts", "worker_generations", "checkpoint_epoch", "checkpoint_frozen")
    class WorkerGenerationsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    FORMAT_VERSION_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    MODEL_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZER_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_FIELD_NUMBER: _ClassVar[int]
    RECEIPTS_FIELD_NUMBER: _ClassVar[int]
    WORKER_GENERATIONS_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_EPOCH_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_FROZEN_FIELD_NUMBER: _ClassVar[int]
    format_version: int
    config_fingerprint: bytes
    model_fingerprint: bytes
    optimizer: str
    version: int
    parameters: _containers.RepeatedCompositeFieldContainer[Tensor]
    receipts: _containers.RepeatedCompositeFieldContainer[UpdateReceipt]
    worker_generations: _containers.ScalarMap[str, int]
    checkpoint_epoch: int
    checkpoint_frozen: bool
    def __init__(self, format_version: _Optional[int] = ..., config_fingerprint: _Optional[bytes] = ..., model_fingerprint: _Optional[bytes] = ..., optimizer: _Optional[str] = ..., version: _Optional[int] = ..., parameters: _Optional[_Iterable[_Union[Tensor, _Mapping]]] = ..., receipts: _Optional[_Iterable[_Union[UpdateReceipt, _Mapping]]] = ..., worker_generations: _Optional[_Mapping[str, int]] = ..., checkpoint_epoch: _Optional[int] = ..., checkpoint_frozen: bool = ...) -> None: ...

class FenceRequest(_message.Message):
    __slots__ = ("run_id", "worker_id", "generation")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    worker_id: str
    generation: int
    def __init__(self, run_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., generation: _Optional[int] = ...) -> None: ...

class ShardProgress(_message.Message):
    __slots__ = ("version", "next_steps", "worker_generations", "pending_workers")
    class NextStepsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class WorkerGenerationsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    VERSION_FIELD_NUMBER: _ClassVar[int]
    NEXT_STEPS_FIELD_NUMBER: _ClassVar[int]
    WORKER_GENERATIONS_FIELD_NUMBER: _ClassVar[int]
    PENDING_WORKERS_FIELD_NUMBER: _ClassVar[int]
    version: int
    next_steps: _containers.ScalarMap[str, int]
    worker_generations: _containers.ScalarMap[str, int]
    pending_workers: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, version: _Optional[int] = ..., next_steps: _Optional[_Mapping[str, int]] = ..., worker_generations: _Optional[_Mapping[str, int]] = ..., pending_workers: _Optional[_Iterable[str]] = ...) -> None: ...

class WorkerJournal(_message.Message):
    __slots__ = ("format_version", "config_fingerprint", "worker_id", "next_step", "requests", "loss")
    FORMAT_VERSION_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    NEXT_STEP_FIELD_NUMBER: _ClassVar[int]
    REQUESTS_FIELD_NUMBER: _ClassVar[int]
    LOSS_FIELD_NUMBER: _ClassVar[int]
    format_version: int
    config_fingerprint: bytes
    worker_id: str
    next_step: int
    requests: _containers.RepeatedCompositeFieldContainer[GradientUpdate]
    loss: float
    def __init__(self, format_version: _Optional[int] = ..., config_fingerprint: _Optional[bytes] = ..., worker_id: _Optional[str] = ..., next_step: _Optional[int] = ..., requests: _Optional[_Iterable[_Union[GradientUpdate, _Mapping]]] = ..., loss: _Optional[float] = ...) -> None: ...

class CheckpointRequest(_message.Message):
    __slots__ = ("run_id", "checkpoint_id", "worker_id")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    checkpoint_id: str
    worker_id: str
    def __init__(self, run_id: _Optional[str] = ..., checkpoint_id: _Optional[str] = ..., worker_id: _Optional[str] = ...) -> None: ...

class CheckpointControl(_message.Message):
    __slots__ = ("epoch", "checkpoint_id", "phase", "committed")
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_ID_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_FIELD_NUMBER: _ClassVar[int]
    epoch: int
    checkpoint_id: str
    phase: CheckpointPhase
    committed: bool
    def __init__(self, epoch: _Optional[int] = ..., checkpoint_id: _Optional[str] = ..., phase: _Optional[_Union[CheckpointPhase, str]] = ..., committed: bool = ...) -> None: ...

class CheckpointAck(_message.Message):
    __slots__ = ("run_id", "worker_id", "session_id", "epoch", "step", "parameter_version", "worker_journal")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    PARAMETER_VERSION_FIELD_NUMBER: _ClassVar[int]
    WORKER_JOURNAL_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    worker_id: str
    session_id: str
    epoch: int
    step: int
    parameter_version: int
    worker_journal: bytes
    def __init__(self, run_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., session_id: _Optional[str] = ..., epoch: _Optional[int] = ..., step: _Optional[int] = ..., parameter_version: _Optional[int] = ..., worker_journal: _Optional[bytes] = ...) -> None: ...

class CheckpointWorkerRecord(_message.Message):
    __slots__ = ("worker_id", "generation", "step", "worker_journal")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    WORKER_JOURNAL_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    generation: int
    step: int
    worker_journal: bytes
    def __init__(self, worker_id: _Optional[str] = ..., generation: _Optional[int] = ..., step: _Optional[int] = ..., worker_journal: _Optional[bytes] = ...) -> None: ...

class CheckpointEpochStatus(_message.Message):
    __slots__ = ("control", "all_workers_acknowledged", "workers", "committed")
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    ALL_WORKERS_ACKNOWLEDGED_FIELD_NUMBER: _ClassVar[int]
    WORKERS_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_FIELD_NUMBER: _ClassVar[int]
    control: CheckpointControl
    all_workers_acknowledged: bool
    workers: _containers.RepeatedCompositeFieldContainer[CheckpointWorkerRecord]
    committed: bool
    def __init__(self, control: _Optional[_Union[CheckpointControl, _Mapping]] = ..., all_workers_acknowledged: bool = ..., workers: _Optional[_Iterable[_Union[CheckpointWorkerRecord, _Mapping]]] = ..., committed: bool = ...) -> None: ...

class CheckpointPhaseRequest(_message.Message):
    __slots__ = ("run_id", "epoch", "phase")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    epoch: int
    phase: CheckpointPhase
    def __init__(self, run_id: _Optional[str] = ..., epoch: _Optional[int] = ..., phase: _Optional[_Union[CheckpointPhase, str]] = ...) -> None: ...

class CheckpointSnapshot(_message.Message):
    __slots__ = ("snapshot",)
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    snapshot: bytes
    def __init__(self, snapshot: _Optional[bytes] = ...) -> None: ...

class ShardCheckpointRequest(_message.Message):
    __slots__ = ("run_id", "epoch")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    epoch: int
    def __init__(self, run_id: _Optional[str] = ..., epoch: _Optional[int] = ...) -> None: ...

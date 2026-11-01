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
SYNC_MODE_UNSPECIFIED: SyncMode
SYNCHRONOUS: SyncMode
ASYNCHRONOUS: SyncMode
BOUNDED_STALENESS: SyncMode
MEAN: Aggregation
SUM: Aggregation

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
    __slots__ = ("session_id", "config")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    config: RunConfig
    def __init__(self, session_id: _Optional[str] = ..., config: _Optional[_Union[RunConfig, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("worker_id", "health", "step", "parameter_version", "heartbeat_age_seconds")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    PARAMETER_VERSION_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_AGE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    health: str
    step: int
    parameter_version: int
    heartbeat_age_seconds: float
    def __init__(self, worker_id: _Optional[str] = ..., health: _Optional[str] = ..., step: _Optional[int] = ..., parameter_version: _Optional[int] = ..., heartbeat_age_seconds: _Optional[float] = ...) -> None: ...

class RunStatus(_message.Message):
    __slots__ = ("config", "workers")
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    WORKERS_FIELD_NUMBER: _ClassVar[int]
    config: RunConfig
    workers: _containers.RepeatedCompositeFieldContainer[WorkerState]
    def __init__(self, config: _Optional[_Union[RunConfig, _Mapping]] = ..., workers: _Optional[_Iterable[_Union[WorkerState, _Mapping]]] = ...) -> None: ...

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
    __slots__ = ("run_id", "worker_id", "step", "base_version", "tensors")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    BASE_VERSION_FIELD_NUMBER: _ClassVar[int]
    TENSORS_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    worker_id: str
    step: int
    base_version: int
    tensors: _containers.RepeatedCompositeFieldContainer[Tensor]
    def __init__(self, run_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., step: _Optional[int] = ..., base_version: _Optional[int] = ..., tensors: _Optional[_Iterable[_Union[Tensor, _Mapping]]] = ...) -> None: ...

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
    __slots__ = ("format_version", "config_fingerprint", "model_fingerprint", "optimizer", "version", "parameters", "receipts", "worker_generations")
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
    format_version: int
    config_fingerprint: bytes
    model_fingerprint: bytes
    optimizer: str
    version: int
    parameters: _containers.RepeatedCompositeFieldContainer[Tensor]
    receipts: _containers.RepeatedCompositeFieldContainer[UpdateReceipt]
    worker_generations: _containers.ScalarMap[str, int]
    def __init__(self, format_version: _Optional[int] = ..., config_fingerprint: _Optional[bytes] = ..., model_fingerprint: _Optional[bytes] = ..., optimizer: _Optional[str] = ..., version: _Optional[int] = ..., parameters: _Optional[_Iterable[_Union[Tensor, _Mapping]]] = ..., receipts: _Optional[_Iterable[_Union[UpdateReceipt, _Mapping]]] = ..., worker_generations: _Optional[_Mapping[str, int]] = ...) -> None: ...

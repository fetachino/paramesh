"""Bounded, non-executable tensor transport and stable parameter ownership."""

import hashlib
import math
from collections.abc import Iterable

import numpy as np
from numpy.typing import NDArray

from paramesh.rpc import training_pb2 as pb

MAX_TENSOR_BYTES = 4 * 1024 * 1024
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TENSORS = 1024
FloatArray = NDArray[np.float32]


def encode(name: str, values: FloatArray) -> pb.Tensor:
    if values.dtype != np.float32:
        raise ValueError("Only float32 dtype is supported")
    message = pb.Tensor(
        name=name, shape=values.shape, dtype="float32-le", data=values.astype("<f4").tobytes()
    )
    decode(message)
    return message


def decode(message: pb.Tensor) -> FloatArray:
    if not message.name or len(message.name) > 256:
        raise ValueError("Tensor name must contain 1 to 256 characters")
    if message.dtype != "float32-le":
        raise ValueError("Unsupported tensor dtype")
    count = math.prod(message.shape)
    if len(message.shape) > 8 or count < 1 or count * 4 > MAX_TENSOR_BYTES:
        raise ValueError("Tensor size is outside the supported limit")
    if len(message.data) != count * 4:
        raise ValueError("Tensor byte length does not match shape")
    values = np.frombuffer(message.data, dtype="<f4").reshape(tuple(message.shape)).copy()
    if not np.isfinite(values).all():
        raise ValueError("Tensor values must be finite")
    return values


def decode_many(messages: Iterable[pb.Tensor]) -> dict[str, FloatArray]:
    result: dict[str, FloatArray] = {}
    size = 0
    for message in messages:
        size += len(message.data)
        if len(result) >= MAX_TENSORS or size > MAX_MESSAGE_BYTES:
            raise ValueError("Tensor collection exceeds size limit")
        if message.name in result:
            raise ValueError("Duplicate tensor name")
        result[message.name] = decode(message)
    return result


def partition(names: Iterable[str], shard_count: int) -> dict[str, int]:
    if shard_count < 1:
        raise ValueError("At least one shard is required")
    return {
        name: int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % shard_count
        for name in sorted(names)
    }

"""Validation shared by the control plane and parameter shards."""

import math
import re

from paramesh.rpc import training_pb2 as pb


def validate_config(config: pb.RunConfig) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", config.run_id):
        raise ValueError("run_id must be a safe identifier of at most 64 characters")
    if config.mode not in (pb.SYNCHRONOUS, pb.ASYNCHRONOUS, pb.BOUNDED_STALENESS):
        raise ValueError("Unknown synchronization mode")
    if not 1 <= len(config.shard_endpoints) <= 16 or any(not x for x in config.shard_endpoints):
        raise ValueError("Configure between 1 and 16 shard endpoints")
    if len(set(config.shard_endpoints)) != len(config.shard_endpoints):
        raise ValueError("Shard endpoints must be distinct")
    if not 1 <= len(config.worker_ids) <= 64 or len(set(config.worker_ids)) != len(
        config.worker_ids
    ):
        raise ValueError("Configure between 1 and 64 distinct workers")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x) for x in config.worker_ids):
        raise ValueError("Worker IDs must be safe identifiers of at most 64 characters")
    if not math.isfinite(config.learning_rate) or config.learning_rate <= 0:
        raise ValueError("learning_rate must be finite and positive")
    if not math.isfinite(config.barrier_timeout_seconds) or config.barrier_timeout_seconds <= 0:
        raise ValueError("barrier_timeout_seconds must be finite and positive")


def copy_config(config: pb.RunConfig) -> pb.RunConfig:
    result = pb.RunConfig()
    result.CopyFrom(config)
    return result

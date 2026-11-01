"""Bounded operator event history and expiring single-operator sessions."""

import copy
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from paramesh.events import EVENT_NAMES, FIELDS
from paramesh.state import StateDB

EVENT_LIMIT = 200
BASE_FIELDS = frozenset(
    {"schema_version", "event_id", "event", "timestamp", "service", "entry_point"}
)
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _validate_event(record: Any) -> dict[str, Any]:
    if (
        not isinstance(record, dict)
        or not BASE_FIELDS <= record.keys()
        or record.keys() - BASE_FIELDS - FIELDS - {"trace_id", "span_id"}
        or type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or not isinstance(record["event"], str)
        or record["event"] not in EVENT_NAMES
        or record["entry_point"] != "cli"
        or not isinstance(record["event_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["event_id"])
    ):
        raise ValueError("Invalid lifecycle event schema")
    for key in ("service", "run_id", "worker_id", "checkpoint_id"):
        if key in record and (
            not isinstance(record[key], str) or not IDENTIFIER.fullmatch(record[key])
        ):
            raise ValueError("Invalid lifecycle identifier")
    for key in ("generation", "step", "version"):
        if key in record and (type(record[key]) is not int or not 0 <= record[key] < 2**64):
            raise ValueError("Invalid lifecycle counter")
    for key in ("timestamp", "duration_seconds"):
        if key in record and (
            type(record[key]) not in (int, float)
            or not 0 <= record[key] < 253402300800
            or not math.isfinite(record[key])
        ):
            raise ValueError("Invalid lifecycle time")
    if "shard_versions" in record and (
        not isinstance(record["shard_versions"], list)
        or not 1 <= len(record["shard_versions"]) <= 16
        or any(
            type(value) is not int or not 0 <= value < 2**64 for value in record["shard_versions"]
        )
    ):
        raise ValueError("Invalid checkpoint shard versions")
    for key, length in (("trace_id", 32), ("span_id", 16)):
        if key in record and (
            not isinstance(record[key], str)
            or not re.fullmatch(rf"[a-f0-9]{{{length}}}", record[key])
        ):
            raise ValueError("Invalid trace correlation")
    if "mode" in record and record["mode"] not in (
        "SYNCHRONOUS",
        "ASYNCHRONOUS",
        "BOUNDED_STALENESS",
    ):
        raise ValueError("Invalid lifecycle training mode")
    if (
        record["event"] == "checkpoint_completed"
        and not {
            "run_id",
            "checkpoint_id",
            "step",
            "shard_versions",
            "duration_seconds",
        }
        <= record.keys()
    ):
        raise ValueError("Checkpoint publication fields are required")
    return record


class EventLog:
    def __init__(self, storage: StateDB) -> None:
        self.storage, self.lock = storage, threading.Lock()
        self.records: list[dict[str, Any]] = []
        saved = storage.get("operator_events")
        if saved is not None:
            state = json.loads(saved)
            if (
                state["format_version"] != 1
                or not isinstance(state["events"], list)
                or len(state["events"]) > EVENT_LIMIT
            ):
                raise ValueError("Unsupported operator event history")
            self.records = [_validate_event(record) for record in state["events"]]

    def ingest(self, payload: bytes) -> bool:
        if len(payload) > 4096:
            raise ValueError("Lifecycle message exceeds size limit")
        try:
            parsed = json.loads(payload)
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("Invalid lifecycle JSON") from None
        record = _validate_event(parsed)
        with self.lock:
            if any(item["event_id"] == record["event_id"] for item in self.records):
                return False
            proposed = (self.records + [record])[-EVENT_LIMIT:]
            self.storage.put(
                "operator_events",
                json.dumps({"format_version": 1, "events": proposed}, allow_nan=False).encode(),
            )
            self.records = proposed
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return copy.deepcopy(self.records)


class Sessions:
    def __init__(self, password: str, *, clock: Callable[[], float] = time.time) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", password):
            raise ValueError("Dashboard requires a strong URL-safe operator password")
        self._password = password
        self._key = secrets.token_bytes(32)
        self.clock = clock

    def login(self, username: str, password: str) -> str | None:
        if (
            not username.isascii()
            or not password.isascii()
            or len(password) > 256
            or not hmac.compare_digest(username, "operator")
            or not hmac.compare_digest(password, self._password)
        ):
            return None
        message = f"{int(self.clock()) + 8 * 3600}:{secrets.token_hex(16)}"
        signature = hmac.new(self._key, message.encode(), hashlib.sha256).hexdigest()
        return f"{message}:{signature}"

    def valid(self, token: str) -> bool:
        if not re.fullmatch(r"[0-9]{1,12}:[a-f0-9]{32}:[a-f0-9]{64}", token):
            return False
        message, signature = token.rsplit(":", 1)
        expected = hmac.new(self._key, message.encode(), hashlib.sha256).hexdigest()
        return (
            hmac.compare_digest(signature, expected) and int(message.split(":")[0]) > self.clock()
        )

    def logout(self) -> None:
        self._key = secrets.token_bytes(32)

"""Best-effort lifecycle events: bounded memory and no broker calls on training threads."""

import asyncio
import json
import os
import queue
import re
import ssl
import sys
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

EVENT_NAMES = frozenset(
    {
        "training_started",
        "worker_joined",
        "worker_lost",
        "worker_recovered",
        "checkpoint_completed",
        "shard_restored",
        "training_completed",
    }
)
FIELDS = frozenset(
    {
        "run_id",
        "worker_id",
        "generation",
        "step",
        "version",
        "checkpoint_id",
        "shard_versions",
        "duration_seconds",
        "mode",
    }
)


def nats_tls_options(url: str) -> dict[str, ssl.SSLContext]:
    if not url:
        return {}
    if urlsplit(url).scheme != "tls":
        if any(
            os.environ.get(name)
            for name in (
                "PARAMESH_NATS_TLS_CA",
                "PARAMESH_NATS_TLS_CERT",
                "PARAMESH_NATS_TLS_KEY",
            )
        ):
            raise ValueError("NATS TLS files require a tls:// endpoint")
        return {}
    context = ssl.create_default_context()
    ca = os.environ.get("PARAMESH_NATS_TLS_CA")
    certificate = os.environ.get("PARAMESH_NATS_TLS_CERT")
    private_key = os.environ.get("PARAMESH_NATS_TLS_KEY")
    if ca:
        context.load_verify_locations(cafile=ca)
    if bool(certificate) != bool(private_key):
        raise ValueError("NATS TLS certificate and private key must be configured together")
    if certificate and private_key:
        context.load_cert_chain(certificate, private_key)
    return {"tls": context}


class EventBus:
    def __init__(self, service: str, url: str = "", token: str = "", capacity: int = 256) -> None:
        if not 1 <= capacity <= 4096:
            raise ValueError("Event queue capacity must be between 1 and 4096")
        parsed = urlsplit(url)
        if url and (
            parsed.scheme not in ("nats", "tls")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token)
        ):
            raise ValueError("NATS requires an explicit endpoint and separate token")
        self.service = service
        self.url, self._token = url, token
        self._tls_options = nats_tls_options(url)
        self.queue: queue.Queue[bytes] = queue.Queue(maxsize=capacity)
        self.stopped = threading.Event()
        self.connected = False
        self.published = 0
        self.dropped = 0
        self.log_failures = 0
        self.thread = None
        if url:
            self.thread = threading.Thread(target=self._run, name="lifecycle-events", daemon=True)
            self.thread.start()

    def emit(self, event: str, **fields: Any) -> None:
        from paramesh.telemetry import correlation

        if event not in EVENT_NAMES or fields.keys() - FIELDS:
            raise ValueError("Unknown lifecycle event or field")
        record = {
            "schema_version": 1,
            "event_id": uuid.uuid4().hex,
            "event": event,
            "timestamp": time.time(),
            "service": self.service,
            "entry_point": "cli",
            **fields,
        }
        record.update(correlation())
        payload = json.dumps(record, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > 4096:
            raise ValueError("Lifecycle event exceeds size limit")
        try:
            print(payload.decode(), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            self.log_failures += 1
        if self.url:
            try:
                self.queue.put_nowait(payload)
            except queue.Full:
                self.dropped += 1

    def _run(self) -> None:
        asyncio.run(self._publish())

    async def _publish(self) -> None:
        import nats
        from nats.errors import Error

        async def ignore_error(error: Exception) -> None:
            # Connection exceptions can contain endpoint details; counters are enough here.
            pass

        client = None
        try:
            while not self.stopped.is_set():
                try:
                    if client is not None and not client.is_connected:
                        await client.close()
                        client = None
                        self.connected = False
                    if client is None:
                        client = await nats.connect(
                            self.url,
                            token=self._token,
                            **self._tls_options,
                            connect_timeout=1,
                            allow_reconnect=False,
                            max_reconnect_attempts=0,
                            error_cb=ignore_error,
                        )
                        self.connected = True
                    try:
                        payload = self.queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue
                    try:
                        await client.publish("paramesh.lifecycle", payload)
                        await client.flush(timeout=1)
                        self.published += 1
                    except (Error, OSError, TimeoutError):
                        self.dropped += 1
                        raise
                except (Error, OSError, TimeoutError):
                    self.connected = False
                    if client is not None:
                        await client.close()
                    client = None
                    await asyncio.sleep(0.2)
        finally:
            self.connected = False
            if client is not None:
                await client.close()

    def close(self) -> None:
        if self.stopped.is_set():
            return
        deadline = time.monotonic() + 1
        while self.url and not self.queue.empty() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.dropped += self.queue.qsize()


bus: EventBus | None = None


def emit(event: str, **fields: Any) -> None:
    if bus is not None:
        bus.emit(event, **fields)

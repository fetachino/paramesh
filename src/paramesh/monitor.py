"""Read-only cluster sampling and a bounded NATS-to-operator/Loki event bridge."""

import asyncio
import copy
import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import grpc
from google.protobuf.json_format import MessageToDict

from paramesh import events, telemetry
from paramesh.operations import EventLog
from paramesh.rpc import training_pb2 as pb
from paramesh.rpc import training_pb2_grpc as rpc
from paramesh.security import RpcSecurity, open_channel

LATEST = {
    "loss": 'paramesh_loss{job="workers"}',
    "steps_per_second": 'rate(paramesh_worker_steps_total{job="workers"}[30s])',
    "examples_per_second": 'rate(paramesh_examples_total{job="workers"}[30s])',
    "staleness": 'paramesh_staleness{job="shards"}',
    "push_p95_seconds": (
        "histogram_quantile(0.95,sum by (le) "
        '(rate(paramesh_rpc_duration_seconds_bucket{direction="client",'
        'method="PushGradients",status="OK"}[1m])))'
    ),
    "pull_p95_seconds": (
        "histogram_quantile(0.95,sum by (le) "
        '(rate(paramesh_rpc_duration_seconds_bucket{direction="client",'
        'method="PullParameters",status="OK"}[1m])))'
    ),
    "bytes_per_second": 'sum(rate(paramesh_rpc_bytes_total{direction="client"}[30s]))',
    "event_drops": "sum(paramesh_events_dropped_total)",
}
HISTORY = {
    "loss": LATEST["loss"],
    "throughput": LATEST["steps_per_second"],
    "versions": 'paramesh_shard_version{job="shards"}',
    "staleness": LATEST["staleness"],
}


def _endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError(
            "Operational backend requires an explicit HTTP endpoint without credentials"
        )
    return url.rstrip("/")


def _fetch(endpoint: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
    data = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
    request = Request(
        endpoint + path,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urlopen(request, timeout=1) as response:
        result: bytes = response.read(4 * 1024 * 1024 + 1)
    if len(result) > 4 * 1024 * 1024:
        raise ValueError("Operational response exceeds size limit")
    return result


class EventSink:
    def __init__(self, log: EventLog, url: str, token: str, loki: str) -> None:
        self.log, self.url, self._token = log, url, token
        self._tls_options = events.nats_tls_options(url)
        self.loki = _endpoint(loki)
        self.stopped = threading.Event()
        self.connected = False
        self.thread = None
        if url:
            self.thread = threading.Thread(target=self._run, name="operator-events", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        asyncio.run(self._consume())

    async def _consume(self) -> None:
        import nats
        from nats.errors import Error

        async def ignore_error(error: Exception) -> None:
            pass

        async def receive(message: Any) -> None:
            try:
                accepted = self.log.ingest(message.data)
            except ValueError:
                telemetry.add("events_invalid")
                return
            except (OSError, sqlite3.Error):
                telemetry.add("event_storage_errors")
                return
            if not accepted:
                return
            telemetry.add("events_ingested")
            record = json.loads(message.data)
            if record["event"] == "checkpoint_completed":
                telemetry.observe("checkpoint_duration_seconds", record["duration_seconds"])
                telemetry.set_value("last_checkpoint_duration_seconds", record["duration_seconds"])
                telemetry.set_value("last_checkpoint_step", record["step"])
                telemetry.set_value("last_checkpoint_timestamp_seconds", record["timestamp"])
            payload = {
                "streams": [
                    {
                        "stream": {"app": "paramesh", "event": record["event"]},
                        "values": [[str(int(record["timestamp"] * 1e9)), message.data.decode()]],
                    }
                ]
            }
            try:
                await asyncio.to_thread(_fetch, self.loki, "/loki/api/v1/push", payload)
            except (URLError, OSError, ValueError):
                telemetry.add("loki_errors")

        while not self.stopped.is_set():
            client = None
            try:
                client = await nats.connect(
                    self.url,
                    token=self._token,
                    **self._tls_options,
                    connect_timeout=1,
                    allow_reconnect=False,
                    max_reconnect_attempts=0,
                    error_cb=ignore_error,
                )
                await client.subscribe(
                    "paramesh.lifecycle",
                    cb=receive,
                    pending_msgs_limit=512,
                    pending_bytes_limit=2 * 1024 * 1024,
                )
                await client.flush(timeout=1)
                self.connected = True
                telemetry.set_value("event_consumer_connected", 1)
                while client.is_connected and not self.stopped.is_set():
                    await asyncio.sleep(0.1)
            except (Error, OSError, TimeoutError):
                pass
            finally:
                self.connected = False
                telemetry.set_value("event_consumer_connected", 0)
                if client is not None:
                    await client.close()
            await asyncio.sleep(0.2)

    def close(self) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=3)


class ClusterView:
    def __init__(
        self,
        config: pb.RunConfig,
        coordinator: str,
        security: RpcSecurity,
        log: EventLog,
        sink: EventSink,
        prometheus: str,
        tempo: str,
        evidence: Path,
        external_artifacts: Path | None = None,
    ) -> None:
        self.config, self.coordinator, self.security = config, coordinator, security
        self.log, self.sink, self.evidence = log, sink, evidence
        self.external_artifacts = external_artifacts
        self.prometheus, self.tempo = _endpoint(prometheus), _endpoint(tempo)
        self.lock, self.stopped = threading.Lock(), threading.Event()
        self.current: dict[str, Any] = {
            "schema_version": 1,
            "run": MessageToDict(config, preserving_proto_field_name=True),
            "sampled_at": None,
            "coordinator": {"available": False},
            "shards": [],
            "metrics": {},
            "history": {},
            "traces": [],
            "backends": {},
        }
        self.thread = threading.Thread(target=self._poll, name="cluster-sampling", daemon=True)
        self.thread.start()

    def _prometheus(self, name: str, expression: str, now: float, history: bool) -> tuple[str, Any]:
        parameters: dict[str, Any] = {"query": expression}
        if history:
            parameters.update(start=now - 900, end=now, step=5)
        path = "/api/v1/query_range?" if history else "/api/v1/query?"
        result = json.loads(_fetch(self.prometheus, path + urlencode(parameters)))
        if (
            not isinstance(result, dict)
            or result.get("status") != "success"
            or not isinstance(result.get("data"), dict)
            or not isinstance(result["data"].get("result"), list)
        ):
            raise ValueError("Metrics query failed")
        return name, result["data"]["result"]

    def _poll(self) -> None:
        while not self.stopped.is_set():
            self.sample()
            self.stopped.wait(2)

    def sample(self) -> None:
        now = time.time()
        report: dict[str, Any] = {
            "schema_version": 1,
            "run": MessageToDict(self.config, preserving_proto_field_name=True),
            "sampled_at": now,
            "coordinator": {"available": False},
            "shards": [],
            "metrics": {},
            "history": {},
            "traces": [],
            "backends": {},
        }
        try:
            with open_channel(self.coordinator, self.security) as channel:
                status = rpc.CoordinatorStub(channel).GetStatus(pb.Empty(), timeout=1)
            if status.config.run_id != self.config.run_id:
                raise ValueError("Monitored coordinator run does not match configuration")
            report["coordinator"] = {
                "available": True,
                "status": MessageToDict(status, preserving_proto_field_name=True),
            }
        except (grpc.RpcError, ValueError):
            pass
        for index, endpoint in enumerate(self.config.shard_endpoints):
            state: dict[str, Any] = {"index": index, "endpoint": endpoint, "available": False}
            try:
                with open_channel(endpoint, self.security) as channel:
                    progress = rpc.ParameterShardStub(channel).GetProgress(
                        pb.PullRequest(run_id=self.config.run_id), timeout=1
                    )
                state.update(
                    available=True,
                    progress=MessageToDict(progress, preserving_proto_field_name=True),
                )
            except grpc.RpcError:
                pass
            report["shards"].append(state)
        with ThreadPoolExecutor(max_workers=4) as pool:
            current = [
                pool.submit(self._prometheus, key, expr, now, False) for key, expr in LATEST.items()
            ]
            history = [
                pool.submit(self._prometheus, key, expr, now, True) for key, expr in HISTORY.items()
            ]
            for futures, target in ((current, "metrics"), (history, "history")):
                for future in futures:
                    try:
                        name, values = future.result()
                        report[target][name] = values
                    except (URLError, OSError, ValueError, KeyError):
                        pass
        report["backends"]["prometheus"] = len(report["metrics"]) == len(LATEST)
        try:
            result = json.loads(
                _fetch(
                    self.tempo,
                    "/api/search?" + urlencode({"q": '{name="worker.training_step"}', "limit": 6}),
                )
            )
            if not isinstance(result, dict) or not isinstance(result.get("traces", []), list):
                raise ValueError("Invalid trace search response")
            # Tempo search may omit leading zeros; retain canonical W3C trace IDs.
            report["traces"] = [
                dict(trace, traceID=trace["traceID"].zfill(32))
                for trace in result.get("traces", [])
                if isinstance(trace, dict)
                and isinstance(trace.get("traceID"), str)
                and re.fullmatch(r"[a-f0-9]{1,32}", trace["traceID"])
            ]
            report["backends"]["tempo"] = True
        except (URLError, OSError, ValueError):
            report["backends"]["tempo"] = False
        try:
            _fetch(self.sink.loki, "/ready")
            report["backends"]["loki"] = True
        except (URLError, OSError, ValueError):
            report["backends"]["loki"] = False
        with self.lock:
            self.current = report

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            snapshot = copy.deepcopy(self.current)
        snapshot.update(
            events=self.log.snapshot(),
            event_sink={"enabled": bool(self.sink.url), "connected": self.sink.connected},
        )
        return snapshot

    def trace(self, trace_id: str) -> Any:
        return json.loads(_fetch(self.tempo, f"/api/traces/{trace_id}"))

    def benchmarks(self) -> list[Any]:
        reports = []
        for name in (
            "sync-cpu",
            "async-cpu",
            "bounded-cpu",
            "worker-recovery",
            "shard-recovery",
            "compose-checkpoint",
        ):
            path = self.evidence / f"{name}.json"
            if path.is_file():
                with path.open("rb") as stream:
                    payload = stream.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("Evidence artifact exceeds size limit")
                reports.append(json.loads(payload))
        if self.external_artifacts:
            manifest = self.external_artifacts / "manifest.json"
            if manifest.is_file():
                with manifest.open("rb") as stream:
                    payload = stream.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("External artifact exceeds size limit")
                document = json.loads(payload)
                for trial in document.get("trials", []):
                    if not isinstance(trial, dict):
                        continue
                    if trial.get("mode"):
                        reports.append(
                            dict(
                                trial,
                                initial_loss=trial.get("loss_after_warmup"),
                                environment={
                                    "commit": trial.get("commit"),
                                    "source_dirty": trial.get("source_dirty", False),
                                },
                                evidence_source="external workload",
                                evidence_manifest=manifest.name,
                                workload=document.get("workload"),
                            )
                        )
                    elif trial.get("failure"):
                        configuration = document.get("configuration", {})
                        steps = configuration.get("steps_per_worker")
                        reports.append(
                            dict(
                                trial,
                                mode="sync",
                                steps_per_worker=steps,
                                worker_count=configuration.get("workers"),
                                shard_versions=[steps] * configuration.get("shards", 2),
                                failure={
                                    "terminated_component": f"{trial['failure']}-0",
                                    "detection_seconds": trial.get("detection_seconds"),
                                    "recovery_seconds_until_progress": trial.get(
                                        "recovery_seconds_until_progress"
                                    ),
                                    "step_delay_seconds": configuration.get("step_delay_seconds"),
                                },
                                environment={
                                    "commit": trial.get("commit"),
                                    "source_dirty": trial.get("source_dirty", False),
                                },
                                evidence_source="external recovery",
                                evidence_manifest=manifest.name,
                            )
                        )
        return reports

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=8)

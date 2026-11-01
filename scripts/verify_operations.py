"""Verify a running operations profile against real private backends, without mutations."""

import argparse
import datetime
import http.cookiejar
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


def inside(ready_only: bool = False) -> dict:
    def get(base, path):
        with urlopen(Request(base + path, headers={"Accept": "application/json"}), timeout=5) as r:
            return json.load(r)

    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    form = urlencode(
        {"username": "operator", "password": os.environ["PARAMESH_DASHBOARD_PASSWORD"]}
    ).encode()
    client.open("http://127.0.0.1:8080/login", form, timeout=5).close()
    deadline = time.monotonic() + 120
    while True:
        with client.open("http://127.0.0.1:8080/api/state", timeout=5) as response:
            state = json.load(response)
        if (
            all(state["backends"].get(name) for name in ("prometheus", "tempo", "loki"))
            and state["event_sink"]["connected"]
            and (
                ready_only
                or (
                    state["coordinator"]["available"]
                    and all(item["available"] for item in state["shards"])
                    and state["traces"]
                )
            )
        ):
            break
        assert time.monotonic() < deadline, "Operational backends did not become observable"
        time.sleep(2)
    if ready_only:
        return {"ready": True}
    targets = get("http://prometheus:9090", "/api/v1/targets")["data"]["activeTargets"]
    required = {"coordinator", "shard-0", "shard-1", "dashboard"}
    healthy = {item["labels"]["component"] for item in targets if item["health"] == "up"}
    assert required <= healthy, "Persistent-service scrape targets are unhealthy"
    query = urlencode({"query": 'max_over_time(paramesh_worker_steps_total{job="workers"}[1h])'})
    workers = get("http://prometheus:9090", "/api/v1/query?" + query)["data"]["result"]
    assert len(workers) == 2 and all(float(item["value"][1]) > 0 for item in workers)
    logs = get(
        "http://loki:3100",
        "/loki/api/v1/query_range?" + urlencode({"query": '{app="paramesh"}', "limit": 20}),
    )["data"]["result"]
    records = [json.loads(value[1]) for stream in logs for value in stream["values"]]
    assert records and all(record["schema_version"] == 1 for record in records)
    search = get(
        "http://tempo:3200",
        "/api/search?" + urlencode({"q": '{name="worker.training_step"}', "limit": 30}),
    )
    matched = None
    for trace in search.get("traces", []):
        trace_id = trace["traceID"].zfill(32)
        data = get("http://tempo:3200", "/api/traces/" + trace_id)
        spans, services = [], set()
        for batch in data.get("batches", data.get("resourceSpans", [])):
            for attribute in batch.get("resource", {}).get("attributes", []):
                if attribute["key"] == "service.name":
                    services.add(attribute["value"]["stringValue"])
            for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
                spans.extend(scope.get("spans", []))
        names = {span["name"] for span in spans}
        if {"worker.training_step", "shard.aggregate_sgd_commit"} <= names and any(
            name.endswith("/PushGradients") for name in names
        ):
            ids = {span["spanId"] for span in spans}
            assert any(span.get("parentSpanId") in ids for span in spans)
            assert len(services) >= 2
            matched = {"trace_id": trace_id, "services": sorted(services), "spans": len(spans)}
            break
    assert matched, "No trace connects a worker step to a shard SGD commit"
    staleness = [
        float(point[1])
        for series in state["history"].get("staleness", [])
        for point in series["values"]
    ]
    if state["run"]["mode"] == "BOUNDED_STALENESS":
        bound = int(state["run"].get("max_staleness", 0))
        assert staleness and all(0 <= value <= bound for value in staleness)
    return {
        "run_id": state["run"]["run_id"],
        "mode": state["run"]["mode"],
        "global_step": state["coordinator"]["status"].get("global_step", "0"),
        "shard_versions": [int(item["progress"].get("version", 0)) for item in state["shards"]],
        "max_observed_accepted_staleness": max(staleness, default=None),
        "healthy_scrapes": sorted(healthy),
        "worker_counter_series": len(workers),
        "loki_records_checked": len(records),
        "event_names": sorted({item["event"] for item in records}),
        "trace": matched,
        "dashboard_authenticated": True,
        "backends": state["backends"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ready", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--isolated", action="store_true", help="Create and remove an owned test stack"
    )
    parser.add_argument("--project", default="paramesh")
    parser.add_argument("--output", type=Path, default=Path("artifacts/operations-stack.json"))
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside(args.ready)))
        return
    project = f"paramesh-ops-{uuid.uuid4().hex[:10]}" if args.isolated else args.project
    environment = os.environ | (
        {
            "PARAMESH_NATS_URL": "nats://nats:4222",
            "PARAMESH_OTLP_ENDPOINT": "http://tempo:4318/v1/traces",
            "PARAMESH_TRACE_SAMPLE_RATIO": "1",
            "PARAMESH_STEPS": "100",
            "PARAMESH_STEP_DELAY": "0.05",
            "PARAMESH_DASHBOARD_PORT": "0",
            "PARAMESH_GRAFANA_PORT": "0",
        }
        if args.isolated
        else {}
    )

    def compose(*arguments, source=None):
        result = subprocess.run(
            ["docker", "compose", "-p", project, "--profile", "operations", *arguments],
            input=source,
            text=True,
            capture_output=True,
            timeout=240,
            env=environment,
        )
        if result.returncode:
            raise SystemExit(result.stderr)
        return result.stdout.strip()

    def probe(*arguments):
        return json.loads(
            compose(
                "exec",
                "-T",
                "dashboard",
                "python",
                "-",
                "--inside",
                *arguments,
                source=Path(__file__).read_text(),
            )
        )

    try:
        if args.isolated:
            compose(
                "up",
                "-d",
                "--no-build",
                "--wait",
                "dashboard",
                "nats",
                "prometheus",
                "tempo",
                "loki",
                "grafana",
            )
            probe("--ready")
            compose(
                "up",
                "-d",
                "--no-build",
                "coordinator",
                "shard-0",
                "shard-1",
                "worker-0",
                "worker-1",
            )
            for worker in ("worker-0", "worker-1"):
                container = compose("ps", "-aq", worker)
                assert (
                    subprocess.check_output(
                        ["docker", "wait", container], text=True, timeout=120
                    ).strip()
                    == "0"
                )
        report = probe()
        report["image_id"] = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Image}}", compose("ps", "-q", "dashboard")],
            text=True,
        ).strip()
        if args.isolated:
            assert int(report["global_step"]) == 100
            for name in (
                "coordinator",
                "shard-0",
                "shard-1",
                "worker-0",
                "worker-1",
                "nats",
                "prometheus",
                "tempo",
                "loki",
            ):
                container = compose("ps", "-aq", name)
                bindings = subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{json .HostConfig.PortBindings}}",
                        container,
                    ],
                    text=True,
                )
                assert not json.loads(bindings), f"{name} exposes a private service port"
            report["private_ports_verified"] = True
    finally:
        if args.isolated:
            compose("down", "--volumes")
    report["environment"] = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        "verified_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "project": project,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

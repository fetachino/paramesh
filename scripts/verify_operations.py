"""Verify operations backends and an optional owned private-network simulation."""

import argparse
import datetime
import http.cookiejar
import json
import os
import secrets
import shutil
import subprocess
import tempfile
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


def create_multihost_simulation(directory: Path) -> dict[str, str]:
    openssl = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"
    if not Path(openssl).exists():
        raise SystemExit("OpenSSL is required for the mTLS simulation")
    tls = directory / "tls"
    tls.mkdir()
    nats_tls = directory / "nats-tls"
    nats_tls.mkdir()
    work = directory / "certificate-work"
    work.mkdir()
    ca_key, ca_cert = work / "ca.key", work / "ca.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-subj",
            "/CN=ParamMesh local simulation CA",
        ],
        check=True,
        capture_output=True,
    )
    for name, san, usages in (
        (
            "rpc",
            "DNS:localhost,IP:127.0.0.1,IP:10.254.240.10,IP:10.254.240.11,IP:10.254.240.12",
            "serverAuth,clientAuth",
        ),
        ("nats", "IP:10.254.240.16", "serverAuth"),
    ):
        certificate_dir = nats_tls if name == "nats" else tls
        key, cert = certificate_dir / f"{name}.key", certificate_dir / f"{name}.crt"
        csr, ext = work / f"{name}.csr", work / f"{name}.ext"
        ext.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={usages}\nsubjectAltName={san}\n",
            encoding="ascii",
        )
        subprocess.run(
            [
                openssl,
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(csr),
                "-subj",
                f"/CN=paramesh-{name}",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                openssl,
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(cert),
                "-days",
                "2",
                "-extfile",
                str(ext),
            ],
            check=True,
            capture_output=True,
        )
    shutil.copyfile(ca_cert, tls / "ca.pem")
    assert {path.name for path in tls.iterdir()} == {"ca.pem", "rpc.crt", "rpc.key"}
    assert {path.name for path in nats_tls.iterdir()} == {"nats.crt", "nats.key"}

    targets = directory / "targets"
    targets.mkdir()
    for name, entries in {
        "dashboard": [("10.254.240.15:9100", "dashboard")],
        "coordinator": [("10.254.240.10:9100", "coordinator")],
        "shards": [("10.254.240.11:9100", "shard-0"), ("10.254.240.12:9100", "shard-1")],
        "workers": [("10.254.240.13:9100", "worker-0"), ("10.254.240.14:9100", "worker-1")],
    }.items():
        targets.joinpath(f"{name}.json").write_text(
            json.dumps(
                [
                    {"targets": [target], "labels": {"component": component}}
                    for target, component in entries
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    config = directory / "run.json"
    config.write_text(
        json.dumps(
            {
                "run_id": "multihost-local-simulation",
                "mode": "SYNCHRONOUS",
                "shard_endpoints": ["10.254.240.11:50051", "10.254.240.12:50051"],
                "worker_ids": ["worker-0", "worker-1"],
                "learning_rate": 0.05,
                "barrier_timeout_seconds": 30,
                "aggregation": "MEAN",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "PARAMESH_TLS_DIR": str(tls),
        "PARAMESH_NATS_TLS_DIR": str(nats_tls),
        "PARAMESH_CONFIG_FILE": str(config),
        "PARAMESH_RUN_ID": "multihost-local-simulation",
        "PARAMESH_PROMETHEUS_TARGETS_DIR": str(targets),
        "PARAMESH_PRIVATE_BIND_IP": "10.254.240.30",
        "PARAMESH_COORDINATOR_ENDPOINT": "10.254.240.10:50050",
        "PARAMESH_NATS_URL": "tls://10.254.240.16:4222",
        "PARAMESH_OTLP_ENDPOINT": "http://10.254.240.17:4318/v1/traces",
        "PARAMESH_TRACE_SAMPLE_RATIO": "1",
        "PARAMESH_STEPS": "100",
        "PARAMESH_STEP_DELAY": "0.05",
        "PARAMESH_DASHBOARD_PORT": "0",
        "PARAMESH_GRAFANA_PORT": "0",
        "PARAMESH_RPC_TOKEN": secrets.token_urlsafe(32),
        "PARAMESH_ADMIN_TOKEN": secrets.token_urlsafe(32),
        "PARAMESH_NATS_TOKEN": secrets.token_urlsafe(32),
        "PARAMESH_DASHBOARD_PASSWORD": secrets.token_urlsafe(24),
        "PARAMESH_GRAFANA_PASSWORD": secrets.token_urlsafe(24),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ready", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--isolated", action="store_true", help="Create and remove an owned test stack"
    )
    parser.add_argument(
        "--multihost-simulation",
        action="store_true",
        help="Verify static private addressing and TLS across role containers on one Docker host",
    )
    parser.add_argument("--project", default="paramesh")
    parser.add_argument("--output", type=Path, default=Path("artifacts/operations-stack.json"))
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside(args.ready)))
        return
    if args.multihost_simulation:
        args.isolated = True
    project = f"paramesh-ops-{uuid.uuid4().hex[:10]}" if args.isolated else args.project
    temporary = (
        tempfile.TemporaryDirectory(prefix="paramesh-multihost-")
        if args.multihost_simulation
        else None
    )
    environment = os.environ | (
        create_multihost_simulation(Path(temporary.name))
        if temporary
        else (
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
    )
    project_files = (
        [
            "-f",
            "compose.yaml",
            "-f",
            "deploy/multihost/compose.yaml",
            "-f",
            "deploy/multihost/simulation.yaml",
        ]
        if args.multihost_simulation
        else []
    )

    def compose(*arguments, source=None, files=None):
        selected_files = project_files if files is None else files
        result = subprocess.run(
            [
                "docker",
                "compose",
                *selected_files,
                "-p",
                project,
                "--profile",
                "operations",
                *arguments,
            ],
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
            if args.multihost_simulation:
                overlay_model = json.loads(
                    compose(
                        "config",
                        "--format",
                        "json",
                        files=["-f", "compose.yaml", "-f", "deploy/multihost/compose.yaml"],
                    )
                )
                services = overlay_model["services"]
                assert not services["worker-0"].get("depends_on")
                assert not services["worker-1"].get("depends_on")
                assert "PARAMESH_ADMIN_TOKEN" not in services["worker-0"]["environment"]
                assert any(
                    volume["target"] == "/run/paramesh/nats-tls"
                    for volume in services["nats"]["volumes"]
                )
                assert all(
                    volume["target"] != "/run/paramesh/nats-tls"
                    for name in (
                        "coordinator",
                        "shard-0",
                        "shard-1",
                        "worker-0",
                        "worker-1",
                        "dashboard",
                    )
                    for volume in services[name]["volumes"]
                )
                assert any(
                    port["host_ip"] == environment["PARAMESH_PRIVATE_BIND_IP"]
                    and port["published"] == "50050"
                    for port in services["coordinator"]["ports"]
                )
                assert any(
                    port["host_ip"] == "127.0.0.1" and port["target"] == 8080
                    for port in services["dashboard"]["ports"]
                )
                assert any(
                    Path(volume["source"]).as_posix().endswith("deploy/multihost/prometheus.yaml")
                    for volume in services["prometheus"]["volumes"]
                )
                assert any(
                    volume.get("source", "").endswith("coordinator-state")
                    and volume["target"] == "/app/state"
                    for volume in services["coordinator"]["volumes"]
                )
                for name in (
                    "coordinator",
                    "shard-0",
                    "shard-1",
                    "worker-0",
                    "worker-1",
                    "dashboard",
                    "nats",
                    "tempo",
                ):
                    assert all(
                        port.get("host_ip") not in (None, "0.0.0.0", "::")
                        for port in services[name].get("ports", [])
                    ), f"{name} publishes a port on all interfaces"
                compose("config", "--quiet")
                compose("build")
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
        if args.multihost_simulation:
            report["production_overlay_model_verified"] = True
            report["private_host_bindings_verified"] = True
            before = (report["global_step"], report["shard_versions"])
            compose("stop", "coordinator", "shard-0", "shard-1")
            compose("up", "-d", "--no-build", "--wait", "coordinator", "shard-0", "shard-1")
            restarted = probe()
            assert (restarted["global_step"], restarted["shard_versions"]) == before
            report["role_restart_state_preserved"] = True
            report["network_simulation"] = {
                "type": "one Docker Desktop Linux engine with an internal user-defined bridge",
                "addresses": {
                    "coordinator": "10.254.240.10",
                    "shard-0": "10.254.240.11",
                    "shard-1": "10.254.240.12",
                    "worker-0": "10.254.240.13",
                    "worker-1": "10.254.240.14",
                    "dashboard": "10.254.240.15",
                    "nats": "10.254.240.16",
                    "tempo": "10.254.240.17",
                },
                "separate_hosts": False,
                "rpc_mtls": True,
                "nats_tls_and_token_auth": True,
                "prometheus_targets_by_private_ip": True,
                "otlp_uses_plain_http_on_the_internal_network": True,
            }
            report["global_step_after_role_restart"] = restarted["global_step"]
            report["shard_versions_after_role_restart"] = restarted["shard_versions"]
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
            if args.multihost_simulation:
                for name in ("dashboard", "grafana"):
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
                report["all_host_ports_private"] = True
    finally:
        if args.isolated:
            compose("down", "--volumes")
        if temporary:
            temporary.cleanup()
    report["environment"] = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
        "docker_platform": subprocess.check_output(
            ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"], text=True
        ).strip(),
        "verified_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "project": project,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

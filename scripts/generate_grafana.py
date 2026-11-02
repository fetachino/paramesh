"""Keep provisioned Grafana queries readable and reproducible."""

import json
from pathlib import Path

PANELS = [
    ("Completed-step lower watermark", 'paramesh_global_step{job="coordinator"}', "short"),
    ("Active workers", 'paramesh_active_workers{job="coordinator"}', "short"),
    ("Worker pre-update MSE", 'paramesh_loss{job="workers"}', "short"),
    ("Worker steps per second", 'rate(paramesh_worker_steps_total{job="workers"}[30s])', "ops"),
    ("Examples per second", 'rate(paramesh_examples_total{job="workers"}[30s])', "ops"),
    ("Authoritative shard versions", 'paramesh_shard_version{job="shards"}', "short"),
    ("Last accepted gradient staleness", 'paramesh_staleness{job="shards"}', "short"),
    (
        "Pull / push client p95",
        "histogram_quantile(0.95, sum by (le, method) "
        '(rate(paramesh_rpc_duration_seconds_bucket{direction="client",'
        'method=~"PushGradients|PullParameters",status="OK"}[1m])))',
        "s",
    ),
    (
        "Protobuf bytes per second",
        'sum by (component) (rate(paramesh_rpc_bytes_total{direction="client"}[30s]))',
        "Bps",
    ),
    ("Shard barrier participants", 'paramesh_pending_workers{job="shards"}', "short"),
    ("Lifecycle queue depth", "paramesh_event_queue_depth", "short"),
    ("Known lost / unconfirmed events", "paramesh_events_dropped_total", "short"),
]


def main() -> None:
    panels = []
    for index, (title, expression, unit) in enumerate(PANELS):
        panels.append(
            {
                "id": index + 1,
                "title": title,
                "type": "timeseries",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "gridPos": {"h": 7, "w": 8, "x": index % 3 * 8, "y": index // 3 * 7},
                "targets": [
                    {
                        "refId": "A",
                        "expr": expression,
                        "legendFormat": "{{component}} {{method}} {{worker_id}}",
                    }
                ],
                "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
            }
        )
    assert len({item["id"] for item in panels}) == len(PANELS)
    dashboard = {
        "uid": "paramesh-operations",
        "title": "ParamMesh · Training operations",
        "description": (
            "Real process and RPC measurements. Demo pacing and startup are included "
            "in observed rates; these are not scaling claims."
        ),
        "schemaVersion": 41,
        "version": 1,
        "editable": False,
        "tags": ["paramesh"],
        "refresh": "5s",
        "time": {"from": "now-15m", "to": "now"},
        "panels": panels,
    }
    path = Path(__file__).resolve().parents[1] / "ops/grafana/dashboards/paramesh.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

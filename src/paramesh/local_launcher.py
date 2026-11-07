"""Run a no-Docker ParamMesh demo and serve its sanitized local result."""

import argparse
import html
import json
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from paramesh.demo import run_demo


def _page(report: dict[str, Any]) -> bytes:
    summary = {
        "mode": report["mode"],
        "workers": report["worker_count"],
        "shards": report["shard_count"],
        "steps": report["steps_per_worker"],
        "initial_loss": report["initial_loss"],
        "final_loss": report["final_loss"],
        "shard_versions": report["shard_versions"],
        "max_parameter_error": report["max_parameter_error"],
    }
    text = html.escape(json.dumps(summary, indent=2))
    return (
        "<!doctype html><meta charset='utf-8'><title>ParamMesh local result</title>"
        "<style>body{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem}"
        "pre{background:#182536;color:#e7f1ff;padding:1rem;border-radius:8px}</style>"
        "<h1>ParamMesh local demo</h1><p>No Docker required. This is a disposable local run.</p>"
        f"<pre>{text}</pre><p><a href='/report.json'>Download report JSON</a></p>"
    ).encode()


class _Handler(BaseHTTPRequestHandler):
    report: dict[str, Any]

    def do_GET(self) -> None:
        if self.path == "/report.json":
            payload = json.dumps(self.report, indent=2, allow_nan=False).encode()
            content_type = "application/json"
        elif self.path in ("/", "/index.html"):
            payload, content_type = _page(self.report), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: Any) -> None:
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if type(args.steps) is not int or not 1 <= args.steps <= 5000:
        parser.error("--steps must be between 1 and 5000")
    output = args.output or Path.home() / ".paramesh" / "runs" / datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    report = run_demo(mode="sync", workers=2, shards=2, steps=args.steps, output=output)
    _Handler.report = report
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"ParamMesh local result: {url}")
    print(f"Report: {output}")
    if not args.no_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

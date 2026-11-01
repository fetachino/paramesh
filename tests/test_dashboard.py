import http.client
import json
import threading
from urllib.parse import urlencode

from paramesh.dashboard import DashboardServer


def test_operator_http_boundary_sessions_csrf_and_path_allowlist():
    class View:
        trace_requests = []

        def snapshot(self):
            return {"schema_version": 1, "coordinator": {"available": True}}

        def benchmarks(self):
            return []

        def trace(self, trace_id):
            self.trace_requests.append(trace_id)
            return {"batches": []}

    view = View()
    password = "testing_" * 8
    server = DashboardServer(("127.0.0.1", 0), view, password, secure_cookie=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)

    def request(method, path, body=None, **headers):
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    try:
        assert request("GET", "/healthz")[0] == 200
        assert request("GET", "/api/state")[0] == 401
        status, headers, _ = request("GET", "/")
        assert status == 303 and headers["Location"] == "/login"
        assert request("GET", "/login")[1]["Referrer-Policy"] == "same-origin"
        form = urlencode({"username": "operator", "password": password})
        assert request("POST", "/login", form, Origin="https://unrelated.example")[0] == 403
        assert request("POST", "/login", form, Origin="null")[0] == 403
        assert request("POST", "/login", form, Origin="http://[")[0] == 403
        assert request("POST", "/login", "username=operator&password=wrong")[0] == 401
        status, headers, _ = request(
            "POST", "/login", form, Origin=f"http://127.0.0.1:{server.server_port}"
        )
        assert status == 303
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert all(
            attribute in headers["Set-Cookie"]
            for attribute in ("HttpOnly", "SameSite=Strict", "Secure")
        )
        status, headers, body = request("GET", "/api/state", Cookie=cookie)
        assert status == 200 and json.loads(body)["coordinator"]["available"]
        assert password.encode() not in body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert request("GET", "/.env", Cookie=cookie)[0] == 404
        assert request("GET", "/assets/../../.env", Cookie=cookie)[0] == 404
        assert request("GET", "/api/trace/not-a-trace", Cookie=cookie)[0] == 404
        assert view.trace_requests == []
        trace_id = "b" * 32
        assert request("GET", f"/api/trace/{trace_id}", Cookie=cookie)[0] == 200
        assert view.trace_requests == [trace_id]
        assert request("POST", "/login", "x" * 5000)[0] == 413
        assert request("POST", "/logout", Cookie=cookie)[0] == 303
        assert request("GET", "/api/state", Cookie=cookie)[0] == 401
    finally:
        connection.close()
        server.shutdown()
        server.server_close()

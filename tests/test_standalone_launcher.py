import html

from scripts.standalone_launcher import _page


def test_standalone_result_page_contains_sanitized_summary() -> None:
    report = {
        "mode": "sync",
        "worker_count": 2,
        "shard_count": 2,
        "steps_per_worker": 3,
        "initial_loss": 1.0,
        "final_loss": 0.25,
        "shard_versions": [3, 3],
        "max_parameter_error": 0.0,
        "secret": "must-not-be-rendered",
    }
    page = html.unescape(_page(report).decode())
    assert "ParamMesh local demo" in page
    assert '"workers": 2' in page
    assert "must-not-be-rendered" not in page

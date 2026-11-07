import importlib.util
import subprocess
import sys
from pathlib import Path


def load_quickstart():
    source = Path(__file__).resolve().parents[1] / "scripts" / "quickstart.py"
    spec = importlib.util.spec_from_file_location("paramesh_quickstart", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quickstart_generates_env_before_starting_compose(monkeypatch):
    module = load_quickstart()
    commands = []

    def record(command, *, cwd, check, **options):
        commands.append((command, cwd, check, options))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", record)
    module.main(["--no-build"])

    root = Path(module.__file__).resolve().parents[1]
    assert commands[0][:3] == (
        [sys.executable, str(root / "scripts" / "create_dev_env.py"), "--operations"],
        root,
        True,
    )
    assert commands[1][:3] == (
        ["docker", "compose", "--profile", "operations", "up", "-d"],
        root,
        True,
    )


def test_quickstart_can_override_ui_ports(monkeypatch):
    module = load_quickstart()
    compose_options = []

    def record(command, **options):
        if command[0] == "docker":
            compose_options.append(options)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", record)
    module.main(["--no-build", "--dashboard-port", "18080", "--grafana-port", "13000"])

    assert compose_options[0]["env"]["PARAMESH_DASHBOARD_PORT"] == "18080"
    assert compose_options[0]["env"]["PARAMESH_GRAFANA_PORT"] == "13000"

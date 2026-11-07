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

    def record(command, *, cwd, check):
        commands.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", record)
    module.main(["--no-build"])

    root = Path(module.__file__).resolve().parents[1]
    assert commands == [
        ([sys.executable, str(root / "scripts" / "create_dev_env.py"), "--operations"], root, True),
        (["docker", "compose", "--profile", "operations", "up", "-d"], root, True),
    ]

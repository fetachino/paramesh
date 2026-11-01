import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_development_credentials_are_private_distinct_and_never_overwritten(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts" / "create_dev_env.py"
    script = tmp_path / "project" / "scripts" / source.name
    script.parent.mkdir(parents=True)
    shutil.copyfile(source, script)
    first = subprocess.run(
        [sys.executable, str(script)], check=True, capture_output=True, text=True
    )
    target = script.parent.parent / ".env"
    original = target.read_bytes()
    values = dict(line.split("=", 1) for line in original.decode().splitlines())
    assert set(values) == {"PARAMESH_RPC_TOKEN", "PARAMESH_ADMIN_TOKEN"}
    assert len(set(values.values())) == 2 and all(len(value) >= 43 for value in values.values())
    assert all(value not in first.stdout for value in values.values())
    if os.name != "nt":
        assert target.stat().st_mode & 0o077 == 0
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert target.read_bytes() == original

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
    assert set(values) == {
        "PARAMESH_RPC_TOKEN",
        "PARAMESH_ADMIN_TOKEN",
        "PARAMESH_S3_ACCESS_KEY",
        "PARAMESH_S3_SECRET_KEY",
    }
    assert len(set(values.values())) == 4 and all(len(value) >= 43 for value in values.values())
    assert all(value not in first.stdout for value in values.values())
    if os.name != "nt":
        assert target.stat().st_mode & 0o077 == 0
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    assert target.read_bytes() == original


def test_existing_credentials_without_final_newline_are_preserved_when_storage_is_added(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts" / "create_dev_env.py"
    script = tmp_path / "scripts" / source.name
    script.parent.mkdir()
    shutil.copyfile(source, script)
    target = tmp_path / ".env"
    original = "PARAMESH_RPC_TOKEN=keep-rpc\nPARAMESH_ADMIN_TOKEN=keep-admin"
    target.write_text(original)
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    values = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert values["PARAMESH_RPC_TOKEN"] == "keep-rpc"
    assert values["PARAMESH_ADMIN_TOKEN"] == "keep-admin"
    assert len(values["PARAMESH_S3_SECRET_KEY"]) >= 43

"""Real authenticated SeaweedFS contract checks; Docker must be running."""

import json
import os
import secrets
import subprocess
import time
import uuid

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from test_checkpoint import partial_run

from paramesh.checkpoint import export_checkpoint, restore_checkpoint
from paramesh.storage import S3Store


@pytest.fixture(scope="module")
def s3_store():
    name = f"paramesh-s3-check-{uuid.uuid4().hex[:10]}"
    access, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    environment = os.environ | {"AWS_ACCESS_KEY_ID": access, "AWS_SECRET_ACCESS_KEY": secret}
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::8333",
            "-e",
            "AWS_ACCESS_KEY_ID",
            "-e",
            "AWS_SECRET_ACCESS_KEY",
            "-e",
            "S3_BUCKET=paramesh-checkpoints",
            "chrislusf/seaweedfs:4.51",
            "mini",
            "-dir=/data",
            "-ip=127.0.0.1",
            "-volume.max=1",
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=300,
    )
    try:
        binding = subprocess.check_output(
            ["docker", "port", name, "8333"], text=True, timeout=10
        ).strip()
        store = S3Store(f"http://{binding}", "paramesh-checkpoints", access, secret)
        deadline = time.monotonic() + 90
        while True:
            try:
                store.client.head_bucket(Bucket=store.bucket)
                break
            except (BotoCoreError, ClientError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        yield store
    finally:
        # This invocation owns the disposable container; no shared volume is attached.
        subprocess.run(["docker", "rm", "-fv", name], check=True, capture_output=True, timeout=30)


def test_actual_s3_checkpoint_roundtrip_and_conditional_publication(s3_store, tmp_path):
    partial_run(tmp_path / "source")
    manifest = export_checkpoint(tmp_path / "source", s3_store, "s3-partial")
    assert export_checkpoint(tmp_path / "source", s3_store, "s3-partial") == manifest
    assert restore_checkpoint(s3_store, "s3-partial", tmp_path / "restored") == manifest
    assert manifest["shard_versions"] == [1, 0]
    assert (tmp_path / "restored" / "worker-0" / "worker-0.sqlite").is_file()
    report = {
        "backend": "SeaweedFS 4.51",
        "authenticated": True,
        "conditional_publication": True,
        "partial_step_roundtrip": True,
        "manifest": manifest,
    }
    output = tmp_path / "s3-verification.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_actual_s3_immutability_size_bounds_and_credentials(s3_store):
    key = "manifests/immutable.json"
    s3_store.put(key, b"first")
    s3_store.put(key, b"first")
    with pytest.raises(ValueError, match="different contents"):
        s3_store.put(key, b"other")
    with pytest.raises(ValueError, match="size limit"):
        s3_store.get(key, 4)
    wrong = S3Store(s3_store.client.meta.endpoint_url, s3_store.bucket, "wrong", "wrong")
    with pytest.raises(ClientError):
        wrong.get(key)
    with pytest.raises(ValueError, match="object key"):
        s3_store.put("../escape", b"bad")

"""Real Azure SDK contract checks against a disposable authenticated Azurite."""

import base64
import gzip
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from importlib.metadata import version

import pytest
from test_checkpoint import partial_run, resume_restored

from paramesh.checkpoint import export_checkpoint, restore_checkpoint
from paramesh.storage import AzureBlobCheckpointStore, AzureStore

IMAGE = (
    "mcr.microsoft.com/azure-storage/azurite:3.37.0@sha256:"
    "830430c1da1a2d537e08f3e6764dd1f5ae00cf0346bcaf625b968ec3f0971fd5"
)


@pytest.fixture(scope="module")
def azure_credential():
    from azure.core.credentials import AzureNamedKeyCredential

    return AzureNamedKeyCredential(
        "parameshdemo", base64.b64encode(secrets.token_bytes(64)).decode()
    )


@pytest.fixture(scope="module")
def azure_store(azure_credential):
    from azure.core.exceptions import AzureError

    name = f"paramesh-azure-check-{uuid.uuid4().hex[:10]}"
    account, key = azure_credential.named_key
    environment = os.environ | {"AZURITE_ACCOUNTS": f"{account}:{key}"}
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::10000",
            "-e",
            "AZURITE_ACCOUNTS",
            IMAGE,
            "azurite-blob",
            "--blobHost",
            "0.0.0.0",
            "--location",
            "/data",
            "--silent",
            "--disableTelemetry",
            "--disableProductStyleUrl",
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=300,
    )
    try:
        binding = subprocess.check_output(
            ["docker", "port", name, "10000"], text=True, timeout=10
        ).strip()
        store = AzureBlobCheckpointStore(
            f"http://{binding}/{account}", "paramesh-checkpoints", account, key
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                store.client.create_container(store.container)
                break
            except AzureError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        yield store
        store.client.close()
    finally:
        subprocess.run(["docker", "rm", "-fv", name], check=True, capture_output=True, timeout=30)


def test_azure_partial_checkpoint_resumes_through_real_rpcs(azure_store, tmp_path):
    settings = partial_run(tmp_path / "source")
    manifest = export_checkpoint(tmp_path / "source", azure_store, "azure-partial")
    assert manifest["shard_versions"] == [1, 0]
    assert export_checkpoint(tmp_path / "source", azure_store, "azure-partial") == manifest
    destination = tmp_path / "restored"
    assert restore_checkpoint(azure_store, "azure-partial", destination) == manifest
    error = resume_restored(settings, destination)
    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "backend": "Azurite 3.37.0 (emulator, not managed Azure)",
        "image": IMAGE,
        "sdk": version("azure-storage-blob"),
        "api_version": azure_store.client.api_version,
        "partial_step_manifest": manifest,
        "replayed_contributions": 1,
        "restored_final_global_step": 4,
        "max_parameter_error": error,
    }
    (tmp_path / "azure-verification.json").write_text(json.dumps(report, indent=2), encoding="utf8")


def test_azure_cli_export_restore_and_backend_arguments(azure_store, azure_credential, tmp_path):
    partial_run(tmp_path / "source")
    credential = azure_credential.named_key
    environment = os.environ | {
        "PARAMESH_AZURE_ACCOUNT": credential.name,
        "PARAMESH_AZURE_KEY": credential.key,
    }
    command = [sys.executable, "-m", "paramesh.cli", "checkpoint"]
    options = [
        "--id",
        "cli-roundtrip",
        "--azure-endpoint",
        azure_store.client.url,
        "--container",
        azure_store.container,
    ]
    for action, path in (("export", "source"), ("restore", "restored")):
        result = subprocess.run(
            [*command, action, "--state-dir", str(tmp_path / path), *options],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        assert json.loads(result.stdout)["shard_versions"] == [1, 0]
        assert credential.key not in result.stdout + result.stderr
    for arguments in (
        ["--container", "container"],
        ["--bucket", "bucket"],
        ["--s3-endpoint", "https://s3.example", "--azure-endpoint", "https://azure.example"],
    ):
        result = subprocess.run(
            [*command, "export", "--id", "invalid", "--state-dir", str(tmp_path), *arguments],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 2


def test_azure_immutable_bounded_authenticated_objects(azure_store):
    from azure.core.exceptions import HttpResponseError
    from azure.storage.blob import ContentSettings

    key = "manifests/immutable.json"
    azure_store.put(key, b"first")
    azure_store.put(key, b"first")
    with pytest.raises(ValueError, match="different contents"):
        azure_store.put(key, b"other")
    assert azure_store.get(key) == b"first"
    azure_store.put("manifests/empty.json", b"")
    assert azure_store.get("manifests/empty.json", 0) == b""
    assert azure_store.get("manifests/empty.json") == b""
    azure_store.put("manifests/empty.json", b"")
    compressed = gzip.compress(b"large" * 1000)
    encoded_key = "manifests/encoded.json"
    azure_store.client.get_blob_client(azure_store.container, encoded_key).upload_blob(
        compressed, content_settings=ContentSettings(content_encoding="gzip")
    )
    assert azure_store.get(encoded_key, len(compressed)) == compressed
    with pytest.raises(ValueError, match="size limit"):
        azure_store.get(key, 4)
    with pytest.raises(ValueError, match="size limit"):
        azure_store.get(key, -1)
    with pytest.raises(ValueError, match="object key"):
        azure_store.put("../escape", b"bad")
    wrong_store = AzureBlobCheckpointStore(
        azure_store.client.url,
        azure_store.container,
        "parameshdemo",
        base64.b64encode(bytes(64)).decode(),
    )
    try:
        with pytest.raises(HttpResponseError):
            wrong_store.get(key)
    finally:
        wrong_store.client.close()


def test_azure_corruption_and_failed_publication_do_not_restore(azure_store, tmp_path):
    from azure.core.exceptions import ResourceNotFoundError

    partial_run(tmp_path / "source")
    manifest = export_checkpoint(tmp_path / "source", azure_store, "corrupt")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        restore_checkpoint(azure_store, "corrupt", existing)
    assert (existing / "keep.txt").read_text() == "keep"
    blob = azure_store.client.get_blob_client(azure_store.container, manifest["records"][0]["key"])
    original = blob.download_blob().readall()
    blob.upload_blob(b"corrupt", overwrite=True)
    try:
        with pytest.raises(ValueError, match="checksum"):
            restore_checkpoint(azure_store, "corrupt", tmp_path / "fresh")
        assert not (tmp_path / "fresh").exists()
    finally:
        blob.upload_blob(original, overwrite=True)

    class InterruptedStore:
        calls = 0

        def put(self, key, payload):
            self.calls += 1
            if self.calls == 2:
                raise OSError("upload interrupted")
            azure_store.put(key, payload)

    with pytest.raises(OSError, match="interrupted"):
        export_checkpoint(tmp_path / "source", InterruptedStore(), "interrupted")
    with pytest.raises(ResourceNotFoundError):
        restore_checkpoint(azure_store, "interrupted", tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "endpoint,container,account,key",
    [
        ("https://user:secret@example.com", "container", "account", "valid"),
        ("https://example.com?sig=secret", "container", "account", "valid"),
        ("https://example.com/wrong", "container", "account", "valid"),
        ("https://example.com", "Bad-Container", "account", "valid"),
        ("https://example.com", "a--b", "account", "valid"),
        ("https://example.com", "container", "BadAccount", "valid"),
        ("https://example.com", "container", "account", "not base64"),
        ("https://example.com", "container", "account", "eA=="),
    ],
)
def test_azure_requires_explicit_valid_endpoint_and_credentials(endpoint, container, account, key):
    if key == "valid":
        key = base64.b64encode(bytes(64)).decode()
    with pytest.raises(ValueError, match="Explicit Azure"):
        AzureBlobCheckpointStore(endpoint, container, account, key)


def test_azure_store_name_remains_a_compatibility_alias():
    assert AzureStore is AzureBlobCheckpointStore

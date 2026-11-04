import json
from pathlib import Path

import pytest

from scripts.immutable_release import (
    COMPATIBILITY,
    _digest_image,
    checkpoint_compatible,
    validate_manifest,
)


def manifest(commit: str = "a" * 40, digest: str = "sha256:" + "b" * 64) -> dict:
    return {
        "schema_version": 1,
        "source_commit": commit,
        "image": f"ghcr.io/fetachino/paramesh@{digest}",
        "image_digest": digest,
        "created_at": "2026-11-04T00:00:00+00:00",
        "compose_sha256": "c" * 64,
        "immutable_compose_sha256": "d" * 64,
        "compatibility": COMPATIBILITY.copy(),
    }


def test_digest_qualified_image_strips_tag() -> None:
    assert _digest_image("ghcr.io/fetachino/paramesh:sha-a", "sha256:" + "a" * 64) == (
        "ghcr.io/fetachino/paramesh@sha256:" + "a" * 64
    )


def test_manifest_requires_digest_identity() -> None:
    value = manifest()
    validate_manifest(value)
    value["image"] = "ghcr.io/fetachino/paramesh:latest"
    with pytest.raises(ValueError, match="qualified"):
        validate_manifest(value)


def test_checkpoint_requires_equal_shard_versions(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "checkpoint_id": "run-1",
                "shard_versions": [4, 4],
                "records": [{"role": role} for role in ("coordinator", "shard-0", "shard-1")],
            }
        ),
        encoding="utf-8",
    )
    assert checkpoint_compatible(path)["checkpoint_id"] == "run-1"
    path.write_text(path.read_text(encoding="utf-8").replace("[4, 4]", "[4, 3]"), encoding="utf-8")
    with pytest.raises(ValueError, match="equal shard"):
        checkpoint_compatible(path)

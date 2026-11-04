"""Build, record and guard digest-qualified ParamMesh deployment artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMPATIBILITY = {
    "checkpoint_format_version": 1,
    "protocol_version": 1,
    "state_schema_version": 1,
}
REQUIRED_ROLES = {"coordinator", "shard-0", "shard-1"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit(value: str) -> str:
    if not COMMIT_RE.fullmatch(value):
        raise ValueError("source commit must be a 40-character lowercase Git SHA")
    return value


def _digest(value: str) -> str:
    if not DIGEST_RE.fullmatch(value):
        raise ValueError("image digest must be sha256:<64 lowercase hex characters>")
    return value


def _digest_image(image_ref: str, digest: str) -> str:
    _digest(digest)
    if "@" in image_ref:
        repository = image_ref.split("@", 1)[0]
    else:
        repository = (
            image_ref.rsplit(":", 1)[0] if ":" in image_ref.rsplit("/", 1)[-1] else image_ref
        )
    if not repository or repository.endswith("/"):
        raise ValueError("image reference must include a repository")
    return f"{repository}@{digest}"


def _run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "source_commit",
        "image",
        "image_digest",
        "created_at",
        "compose_sha256",
        "immutable_compose_sha256",
        "compatibility",
    }
    missing = required - manifest.keys()
    if missing:
        raise ValueError(f"release manifest missing fields: {', '.join(sorted(missing))}")
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported release manifest schema")
    _commit(manifest["source_commit"])
    image_digest = _digest(manifest["image_digest"])
    if not manifest["image"].endswith(f"@{image_digest}"):
        raise ValueError("image must be qualified by the recorded digest")
    for key in ("compose_sha256", "immutable_compose_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", manifest[key]):
            raise ValueError(f"{key} must be a lowercase SHA-256 value")
    if manifest["compatibility"] != COMPATIBILITY:
        raise ValueError("unsupported persistent-state compatibility contract")


def checkpoint_compatible(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format_version") != COMPATIBILITY["checkpoint_format_version"]:
        raise ValueError("checkpoint format is incompatible with this release")
    versions = raw.get("shard_versions")
    if not isinstance(versions, list) or not versions or len(set(versions)) != 1:
        raise ValueError("rollback requires a checkpoint with equal shard versions")
    roles = {record.get("role") for record in raw.get("records", [])}
    if not REQUIRED_ROLES <= roles:
        raise ValueError("checkpoint is missing coordinator or shard metadata")
    return raw


def _compose_hashes(compose_file: Path, immutable_file: Path) -> tuple[str, str]:
    return _sha256(compose_file), _sha256(immutable_file)


def _base_manifest(
    *,
    source_commit: str,
    image: str,
    image_digest: str,
    compose_file: Path,
    immutable_file: Path,
    build_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compose_sha, immutable_sha = _compose_hashes(compose_file, immutable_file)
    return {
        "schema_version": 1,
        "source_commit": _commit(source_commit),
        "image": _digest_image(image, image_digest),
        "image_digest": _digest(image_digest),
        "created_at": datetime.now(UTC).isoformat(),
        "compose_sha256": compose_sha,
        "immutable_compose_sha256": immutable_sha,
        "compatibility": COMPATIBILITY,
        "build_metadata": build_metadata or {},
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def _record(args: argparse.Namespace) -> None:
    metadata: dict[str, Any] = {}
    if args.metadata:
        metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    manifest = _base_manifest(
        source_commit=args.source_commit,
        image=args.image_ref,
        image_digest=args.digest,
        compose_file=args.compose_file,
        immutable_file=args.immutable_compose_file,
        build_metadata=metadata,
    )
    write_manifest(args.output, manifest)
    print(json.dumps({"image": manifest["image"], "source_commit": manifest["source_commit"]}))


def _build(args: argparse.Namespace) -> None:
    source = args.source_commit or _run("git", "rev-parse", "HEAD", capture=True)
    _commit(source)
    if not args.allow_dirty and _run("git", "status", "--porcelain", capture=True):
        raise ValueError("working tree is dirty; use --allow-dirty only for non-release builds")
    build_date = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory() as temporary:
        metadata_path = Path(temporary) / "metadata.json"
        command = [
            "docker",
            "buildx",
            "build",
            "--platform",
            args.platform,
            "--build-arg",
            f"SOURCE_COMMIT={source}",
            "--build-arg",
            f"BUILD_DATE={build_date}",
            "--build-arg",
            f"SOURCE_DIRTY={'true' if args.allow_dirty else 'false'}",
            "--tag",
            args.image_ref,
            "--metadata-file",
            str(metadata_path),
        ]
        command.append("--push" if args.push else "--load")
        command.append(".")
        _run(*command)
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        )
        digest = metadata.get("containerimage.digest")
        image_id = metadata.get("containerimage.config.digest")
        if not digest and not args.push:
            image_id = _run(
                "docker",
                "image",
                "inspect",
                args.image_ref,
                "--format",
                "{{.Id}}",
                capture=True,
            )
            digest = image_id
        if not digest:
            raise ValueError("build did not return an image digest")
        manifest_metadata = {
            "platform": args.platform,
            "config_digest": image_id,
            "build_args": {
                "SOURCE_COMMIT": source,
                "BUILD_DATE": build_date,
                "SOURCE_DIRTY": "true" if args.allow_dirty else "false",
            },
        }
        manifest = _base_manifest(
            source_commit=source,
            image=args.image_ref,
            image_digest=digest,
            compose_file=args.compose_file,
            immutable_file=args.immutable_compose_file,
            build_metadata=manifest_metadata,
        )
        if args.archive and not args.push:
            _run("docker", "save", "--output", str(args.archive), args.image_ref)
            manifest["artifact_archive"] = {
                "path": str(args.archive),
                "sha256": _sha256(args.archive),
                "bytes": args.archive.stat().st_size,
            }
        write_manifest(args.output, manifest)
    print(json.dumps({"image": manifest["image"], "source_commit": source}))


def _verify(args: argparse.Namespace) -> None:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    compose_sha, immutable_sha = _compose_hashes(args.compose_file, args.immutable_compose_file)
    if (
        compose_sha != manifest["compose_sha256"]
        or immutable_sha != manifest["immutable_compose_sha256"]
    ):
        raise ValueError("deployment Compose files differ from the recorded release")
    if args.image:
        inspect = _run(
            "docker",
            "image",
            "inspect",
            args.image,
            "--format",
            "{{json .RepoDigests}}",
            capture=True,
        )
        if manifest["image_digest"] not in inspect:
            image_id = _run(
                "docker",
                "image",
                "inspect",
                args.image,
                "--format",
                "{{.Id}}",
                capture=True,
            )
            if image_id != manifest["image_digest"]:
                raise ValueError("local image does not match the recorded digest")
    print(
        json.dumps(
            {
                "verified": True,
                "image": manifest["image"],
                "source_commit": manifest["source_commit"],
            }
        )
    )


def _rollback_check(args: argparse.Namespace) -> None:
    current = json.loads(args.current.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    validate_manifest(current)
    validate_manifest(candidate)
    if current["image_digest"] == candidate["image_digest"]:
        raise ValueError("rollback candidate must differ from the current image")
    if current["compatibility"] != candidate["compatibility"]:
        raise ValueError("rollback candidate has an incompatible state contract")
    checkpoint = (
        checkpoint_compatible(args.checkpoint_manifest) if args.checkpoint_manifest else None
    )
    result = {
        "approved": True,
        "current_image": current["image"],
        "candidate_image": candidate["image"],
        "candidate_source_commit": candidate["source_commit"],
        "checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
        "requires_explicit_operator_approval": True,
        "requires_volume_backup": True,
        "destructive_volume_reset": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def _rollback_apply(args: argparse.Namespace) -> None:
    current = json.loads(args.current.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    validate_manifest(current)
    validate_manifest(candidate)
    if current["image_digest"] == candidate["image_digest"]:
        raise ValueError("rollback candidate must differ from the current image")
    if current["compatibility"] != candidate["compatibility"]:
        raise ValueError("rollback candidate has an incompatible state contract")
    if args.checkpoint_manifest:
        checkpoint_compatible(args.checkpoint_manifest)
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "candidate_image": candidate["image"],
                    "project": args.project_name,
                    "requires_explicit_operator_approval": True,
                },
                sort_keys=True,
            )
        )
        return
    if not args.isolated and not args.production_approved:
        raise ValueError("execution requires --isolated or explicit --production-approved")
    if args.production_approved and not args.service:
        raise ValueError("production execution requires explicit --service selections")
    if not args.backup_marker or not args.backup_marker.is_file():
        raise ValueError("execution requires a verified backup marker file")
    command = [
        "docker",
        "compose",
        "--project-name",
        args.project_name,
        "--env-file",
        str(args.env_file),
        "-f",
        str(args.compose_file),
        "-f",
        str(args.immutable_compose_file),
        "--profile",
        "operations",
        "--profile",
        "storage",
    ]
    environment = os.environ.copy()
    environment["PARAMESH_IMAGE"] = candidate["image"]
    subprocess.run([*command, "config", "--quiet"], cwd=ROOT, env=environment, check=True)
    subprocess.run(
        [*command, "up", "-d", "--no-build", "--no-deps", "--force-recreate", *args.service],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    print(
        json.dumps(
            {
                "applied": True,
                "candidate_image": candidate["image"],
                "project": args.project_name,
                "volumes_reset": False,
            },
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--compose-file", type=Path, default=ROOT / "compose.yaml")
    common.add_argument(
        "--immutable-compose-file", type=Path, default=ROOT / "deploy/immutable/compose.yaml"
    )
    record = commands.add_parser("record", parents=[common])
    record.add_argument("--image-ref", required=True)
    record.add_argument("--digest", required=True)
    record.add_argument("--source-commit", required=True)
    record.add_argument("--metadata", type=Path)
    record.add_argument("--output", type=Path, required=True)
    record.set_defaults(function=_record)
    build = commands.add_parser("build", parents=[common])
    build.add_argument("--image-ref", required=True)
    build.add_argument("--source-commit")
    build.add_argument("--platform", default="linux/amd64")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--archive", type=Path)
    build.add_argument("--push", action="store_true")
    build.add_argument("--allow-dirty", action="store_true")
    build.set_defaults(function=_build)
    verify = commands.add_parser("verify", parents=[common])
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--image")
    verify.set_defaults(function=_verify)
    rollback = commands.add_parser("rollback-check")
    rollback.add_argument("--current", type=Path, required=True)
    rollback.add_argument("--candidate", type=Path, required=True)
    rollback.add_argument("--checkpoint-manifest", type=Path)
    rollback.set_defaults(function=_rollback_check)
    apply = commands.add_parser("rollback-apply", parents=[common])
    apply.add_argument("--current", type=Path, required=True)
    apply.add_argument("--candidate", type=Path, required=True)
    apply.add_argument("--checkpoint-manifest", type=Path)
    apply.add_argument("--project-name", required=True)
    apply.add_argument("--env-file", type=Path, required=True)
    apply.add_argument("--backup-marker", type=Path)
    apply.add_argument("--execute", action="store_true")
    apply.add_argument("--isolated", action="store_true")
    apply.add_argument("--production-approved", action="store_true")
    apply.add_argument(
        "--service",
        action="append",
        choices=(
            "dashboard",
            "checkpoint",
            "coordinator",
            "shard-0",
            "shard-1",
            "worker-0",
            "worker-1",
        ),
        default=[],
    )
    apply.set_defaults(function=_rollback_apply)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.function(args)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"immutable release check failed: {error}") from error


if __name__ == "__main__":
    main()

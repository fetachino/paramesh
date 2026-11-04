"""Verify that the checked-in immutable Compose override cannot rebuild ParamMesh."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

APPLICATION_SERVICES = frozenset(
    {"dashboard", "checkpoint", "coordinator", "shard-0", "shard-1", "worker-0", "worker-1"}
)
DIGEST_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


def _compose_config(files: tuple[Path, ...], profiles: tuple[str, ...], image: str | None) -> dict:
    command = ["docker", "compose"]
    for profile in profiles:
        command.extend(("--profile", profile))
    for compose_file in files:
        command.extend(("-f", str(compose_file)))
    command.extend(("config", "--format", "json"))
    environment = os.environ.copy()
    if image is not None:
        environment["PARAMESH_IMAGE"] = image
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(result.stdout)


def verify(base: Path, override: Path, image: str, profiles: tuple[str, ...]) -> None:
    if not DIGEST_PATTERN.fullmatch(image):
        raise ValueError("PARAMESH_IMAGE must be a complete sha256 digest reference")
    base_config = _compose_config((base,), profiles, None)
    merged_config = _compose_config((base, override), profiles, image)
    if set(base_config["services"]) != set(merged_config["services"]):
        raise ValueError("immutable override changed the service set")
    if set(base_config["volumes"]) != set(merged_config["volumes"]):
        raise ValueError("immutable override changed the named volume set")
    if set(base_config["networks"]) != set(merged_config["networks"]):
        raise ValueError("immutable override changed the network set")
    for name, service in base_config["services"].items():
        merged_service = merged_config["services"][name]
        if service.get("volumes") != merged_service.get("volumes"):
            raise ValueError(f"immutable override changed volume mappings for {name}")
        if name in APPLICATION_SERVICES:
            if merged_service.get("image") != image or "build" in merged_service:
                raise ValueError(f"{name} is not digest-only and build-free")
        elif service.get("image") != merged_service.get("image"):
            raise ValueError(f"immutable override changed infrastructure image for {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    parser.add_argument(
        "--immutable-file", type=Path, default=Path("deploy/immutable/compose.yaml")
    )
    parser.add_argument("--image", default=os.environ.get("PARAMESH_IMAGE", ""))
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        default=["operations", "storage", "maintenance"],
    )
    args = parser.parse_args()
    verify(args.compose_file, args.immutable_file, args.image, tuple(args.profiles))
    print(
        "immutable compose verified: digest-only application services, unchanged volumes/networks"
    )


if __name__ == "__main__":
    main()

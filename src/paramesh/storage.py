"""Immutable checkpoint objects; a manifest is published only after its blobs."""

import os
import re
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from paramesh.state import MAX_STATE_BYTES


class ObjectStore(Protocol):
    def put(self, key: str, payload: bytes) -> None: ...

    def get(self, key: str, limit: int = MAX_STATE_BYTES) -> bytes: ...


def _key(key: str) -> str:
    if not re.fullmatch(r"blobs/[a-f0-9]{64}|manifests/[A-Za-z0-9_-]{1,64}\.json", key):
        raise ValueError("Invalid checkpoint object key")
    return key


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Checkpoint path escapes storage root")
        return path

    def put(self, key: str, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.get(key, len(payload)) != payload:
                    raise ValueError(
                        "Checkpoint object already exists with different contents"
                    ) from None
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            os.unlink(temporary)

    def get(self, key: str, limit: int = MAX_STATE_BYTES) -> bytes:
        with self._path(key).open("rb") as stream:
            payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("Checkpoint object exceeds size limit")
        return payload


class S3Store:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        # Explicit credentials/endpoint prevent falling through to unrelated AWS profiles.
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
            or not access_key
            or not secret_key
        ):
            raise ValueError("Explicit S3 endpoint, bucket and credentials are required")
        import boto3
        from botocore.config import Config

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )
        self.bucket = bucket

    def put(self, key: str, payload: bytes) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.put_object(Bucket=self.bucket, Key=_key(key), Body=payload, IfNoneMatch="*")
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 412:
                raise
            if self.get(key, len(payload)) != payload:
                raise ValueError(
                    "Checkpoint object already exists with different contents"
                ) from error

    def get(self, key: str, limit: int = MAX_STATE_BYTES) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=_key(key))
        body = response["Body"]
        try:
            if response["ContentLength"] > limit:
                raise ValueError("Checkpoint object exceeds size limit")
            payload: bytes = body.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("Checkpoint object exceeds size limit")
            return payload
        finally:
            body.close()

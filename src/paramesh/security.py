"""Service credentials and optional TLS; training and administrative roles stay separate."""

import hmac
import os
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import grpc

from paramesh.tensors import MAX_MESSAGE_BYTES

CHANNEL_OPTIONS = [
    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
]
ADMIN_METHODS = {"/paramesh.v1.ParameterShard/FenceWorker"}


@dataclass(frozen=True)
class RpcSecurity:
    token: str = field(repr=False)
    admin_token: str | None = field(default=None, repr=False)
    ca: bytes | None = field(default=None, repr=False)
    certificate: bytes | None = field(default=None, repr=False)
    private_key: bytes | None = field(default=None, repr=False)
    require_client_certificate: bool = False

    def __post_init__(self) -> None:
        for token in (self.token, self.admin_token):
            if token is not None and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
                raise ValueError("Service credentials require 32..256 URL-safe characters")
        if self.admin_token == self.token:
            raise ValueError("Administrative and worker credentials must be distinct")
        if bool(self.certificate) != bool(self.private_key):
            raise ValueError("TLS certificate and private key must be configured together")
        if self.require_client_certificate and not self.ca:
            raise ValueError("Mutual TLS requires a trusted client CA")

    def require_admin(self) -> str:
        if self.admin_token is None:
            raise ValueError("PARAMESH_ADMIN_TOKEN is required for administrative operations")
        return self.admin_token

    @classmethod
    def ephemeral(cls) -> "RpcSecurity":
        return cls(secrets.token_urlsafe(32), secrets.token_urlsafe(32))

    @classmethod
    def from_environment(cls) -> "RpcSecurity":
        token = os.environ.get("PARAMESH_RPC_TOKEN")
        if not token:
            raise ValueError("PARAMESH_RPC_TOKEN must be configured")

        def read(name: str) -> bytes | None:
            value = os.environ.get(name)
            return Path(value).read_bytes() if value else None

        require = os.environ.get("PARAMESH_REQUIRE_CLIENT_CERT", "false").lower()
        if require not in ("true", "false", "1", "0"):
            raise ValueError("PARAMESH_REQUIRE_CLIENT_CERT must be true or false")
        return cls(
            token,
            os.environ.get("PARAMESH_ADMIN_TOKEN"),
            ca=read("PARAMESH_TLS_CA"),
            certificate=read("PARAMESH_TLS_CERT"),
            private_key=read("PARAMESH_TLS_KEY"),
            require_client_certificate=require in ("true", "1"),
        )


class ServerAuth:
    def __init__(self, security: RpcSecurity) -> None:
        self.security = security

    def intercept_service(self, continuation: Any, details: Any) -> Any:
        headers = [value for key, value in details.invocation_metadata if key == "authorization"]
        value = headers[0] if len(headers) == 1 and isinstance(headers[0], str) else ""
        if not value.isascii():
            value = ""
        data = hmac.compare_digest(value, f"Bearer {self.security.token}")
        admin = self.security.admin_token is not None and hmac.compare_digest(
            value, f"Bearer {self.security.admin_token}"
        )
        if admin or (data and details.method not in ADMIN_METHODS):
            return continuation(details)
        code = grpc.StatusCode.PERMISSION_DENIED if data else grpc.StatusCode.UNAUTHENTICATED

        def deny(request: Any, context: Any) -> None:
            context.abort(
                code,
                "Administrative credentials required" if data else "Invalid service credentials",
            )

        # Reject before protobuf decoding; denied payloads remain opaque bounded bytes.
        return grpc.unary_unary_rpc_method_handler(deny)


class _CallDetails(NamedTuple):
    method: str
    timeout: float | None
    metadata: Sequence[tuple[str, str | bytes]]
    credentials: Any
    wait_for_ready: bool | None
    compression: Any


class _ClientAuth(grpc.UnaryUnaryClientInterceptor):  # type: ignore[misc]
    def __init__(self, token: str) -> None:
        self.token = token

    def intercept_unary_unary(self, continuation: Any, details: Any, request: Any) -> Any:
        metadata = [
            (key, value) for key, value in (details.metadata or ()) if key != "authorization"
        ]
        metadata.append(("authorization", f"Bearer {self.token}"))
        updated = _CallDetails(
            details.method,
            details.timeout,
            metadata,
            details.credentials,
            details.wait_for_ready,
            details.compression,
        )
        return continuation(updated, request)


def open_channel(address: str, security: RpcSecurity | None = None, *, admin: bool = False) -> Any:
    if security is not None and security.ca:
        credentials = grpc.ssl_channel_credentials(
            root_certificates=security.ca,
            private_key=security.private_key,
            certificate_chain=security.certificate,
        )
        channel = grpc.secure_channel(address, credentials, options=CHANNEL_OPTIONS)
    else:
        channel = grpc.insecure_channel(address, options=CHANNEL_OPTIONS)
    if security is not None:
        token = security.require_admin() if admin else security.token
        return grpc.intercept_channel(channel, _ClientAuth(token))
    return channel

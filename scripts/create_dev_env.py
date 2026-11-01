"""Create local development credentials without printing or overwriting secrets."""

import os
import secrets
from pathlib import Path


def main() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Using existing .env; credentials were not overwritten.")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"PARAMESH_RPC_TOKEN={secrets.token_urlsafe(32)}\n")
        stream.write(f"PARAMESH_ADMIN_TOKEN={secrets.token_urlsafe(32)}\n")
    print("Created .env with distinct random service credentials.")


if __name__ == "__main__":
    main()

"""Generate protocol bindings, or check committed output without modifying it."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) if args.check else root / "src"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{root / 'proto'}",
                f"--python_out={output}",
                f"--pyi_out={output}",
                f"--grpc_python_out={output}",
                "paramesh/rpc/training.proto",
            ],
            cwd=root / "proto",
            check=True,
        )
        if args.check:
            for generated in output.rglob("training*"):
                target = root / "src" / generated.relative_to(output)
                if not target.exists() or target.read_bytes() != generated.read_bytes():
                    raise SystemExit(f"Generated protocol drift: {target.relative_to(root)}")


if __name__ == "__main__":
    main()

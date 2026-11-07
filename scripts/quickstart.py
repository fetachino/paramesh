"""Create local credentials and start the self-hosted operations stack."""

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-build", action="store_true", help="Reuse the existing local application image"
    )
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    generator = [sys.executable, str(root / "scripts" / "create_dev_env.py"), "--operations"]
    subprocess.run(generator, cwd=root, check=True)
    compose = ["docker", "compose", "--profile", "operations", "up"]
    if not arguments.no_build:
        compose.append("--build")
    compose.append("-d")
    subprocess.run(compose, cwd=root, check=True)
    print("ParamMesh operations stack started.")
    print("Dashboard: http://127.0.0.1:8080")
    print("Grafana:   http://127.0.0.1:3000")


if __name__ == "__main__":
    main()

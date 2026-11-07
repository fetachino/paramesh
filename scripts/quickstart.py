"""Create local credentials and start the self-hosted operations stack."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard-port", type=int, help="Override the local dashboard port")
    parser.add_argument("--grafana-port", type=int, help="Override the local Grafana port")
    parser.add_argument(
        "--no-build", action="store_true", help="Reuse the existing local application image"
    )
    arguments = parser.parse_args(argv)
    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    if getattr(sys, "frozen", False):
        from scripts.create_dev_env import main as create_dev_env

        create_dev_env(["--operations"])
    else:
        generator = [sys.executable, str(root / "scripts" / "create_dev_env.py"), "--operations"]
        subprocess.run(generator, cwd=root, check=True)
    compose = ["docker", "compose", "--profile", "operations", "up"]
    if not arguments.no_build:
        compose.append("--build")
    compose.append("-d")
    environment = os.environ.copy()
    if arguments.dashboard_port is not None:
        environment["PARAMESH_DASHBOARD_PORT"] = str(arguments.dashboard_port)
    if arguments.grafana_port is not None:
        environment["PARAMESH_GRAFANA_PORT"] = str(arguments.grafana_port)
    subprocess.run(compose, cwd=root, check=True, env=environment)
    dashboard_port = environment.get("PARAMESH_DASHBOARD_PORT", "8080")
    grafana_port = environment.get("PARAMESH_GRAFANA_PORT", "3000")
    print("ParamMesh operations stack started.")
    print(f"Dashboard: http://127.0.0.1:{dashboard_port}")
    print(f"Grafana:   http://127.0.0.1:{grafana_port}")


if __name__ == "__main__":
    main()

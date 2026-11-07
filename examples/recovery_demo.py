"""Run the real worker/shard recovery demonstration and save dashboard evidence."""

import argparse
import json
from pathlib import Path

from paramesh.recovery_benchmarks import run_recovery_benchmarks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    report = run_recovery_benchmarks(args.output, repetitions=args.repetitions)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

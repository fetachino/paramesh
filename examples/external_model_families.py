"""Run one of the supported external PyTorch model-family examples."""

import argparse
import json

from paramesh.demo import run_demo
from paramesh.workload import cnn_workload, linear_workload, transformer_workload

WORKLOADS = {
    "linear": linear_workload,
    "cnn": cnn_workload,
    "transformer": transformer_workload,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=sorted(WORKLOADS))
    parser.add_argument("--steps", type=int, default=8)
    args = parser.parse_args()
    result = run_demo(
        mode="sync",
        steps=args.steps,
        workers=2,
        shards=2,
        workload=WORKLOADS[args.model](),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

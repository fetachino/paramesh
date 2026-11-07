"""Measure ParamMesh against a deterministic single-process PyTorch reference."""

import argparse
import json
from pathlib import Path

from paramesh.scaling_benchmarks import run_scaling_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmup-steps", type=int, default=20)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--shards", type=int, default=2)
    args = parser.parse_args()
    report = run_scaling_matrix(
        args.output,
        workers=tuple(args.workers),
        repetitions=args.repetitions,
        warmup_steps=args.warmup_steps,
        measured_steps=args.steps,
        shards=args.shards,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

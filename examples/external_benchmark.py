"""Compare synchronization modes for an external PyTorch workload."""

import argparse
import json
from pathlib import Path

import torch

from paramesh.benchmarks import run_benchmarks
from paramesh.workload import TrainingWorkload


def make_model() -> torch.nn.Module:
    torch.manual_seed(11)
    return torch.nn.Linear(4, 1)


def make_batch(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(200 + worker_index)
    inputs = torch.randn(32, 4, generator=generator)
    weights = torch.tensor([[1.0], [-2.0], [0.5], [3.0]])
    return inputs, inputs @ weights + 0.25


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmup-steps", type=int, default=20)
    parser.add_argument("--steps", type=int, default=200)
    args = parser.parse_args()
    report = run_benchmarks(
        args.output,
        repetitions=args.repetitions,
        warmup_steps=args.warmup_steps,
        measured_steps=args.steps,
        workload=TrainingWorkload(make_model, make_batch),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

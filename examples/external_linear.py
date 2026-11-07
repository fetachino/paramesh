"""Run a small external PyTorch model through the ParamMesh process harness."""

import json

import torch

from paramesh.demo import run_demo
from paramesh.workload import TrainingWorkload


def make_model() -> torch.nn.Module:
    torch.manual_seed(11)
    return torch.nn.Linear(4, 1)


def make_batch(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(200 + worker_index)
    inputs = torch.randn(32, 4, generator=generator)
    weights = torch.tensor([[1.0], [-2.0], [0.5], [3.0]])
    return inputs, inputs @ weights + 0.25


if __name__ == "__main__":
    result = run_demo(
        mode="sync",
        steps=8,
        workers=2,
        shards=2,
        workload=TrainingWorkload(make_model, make_batch),
    )
    print(json.dumps(result, indent=2))

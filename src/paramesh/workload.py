"""Workload adapters for the model-independent distributed protocol."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import numpy as np
import torch
from torch import nn

from paramesh.tensors import FloatArray

ModelFactory = Callable[[], nn.Module]
DatasetFactory = Callable[[int], tuple[torch.Tensor, torch.Tensor]]


@dataclass(frozen=True)
class TrainingWorkload:
    """Model and per-worker batch factories used by a training worker."""

    model_factory: ModelFactory
    dataset_factory: DatasetFactory


def bundled_workload(hidden_width: int = 8) -> TrainingWorkload:
    """Return the deterministic bundled workload used by the reference tests."""

    return TrainingWorkload(
        model_factory=partial(model, hidden_width),
        dataset_factory=dataset,
    )


def linear_workload() -> TrainingWorkload:
    """Return the deterministic external linear-model example."""

    return TrainingWorkload(linear_model, linear_dataset)


def cnn_workload() -> TrainingWorkload:
    """Return the deterministic small image-classification-style example."""

    return TrainingWorkload(cnn_model, cnn_dataset)


def transformer_workload() -> TrainingWorkload:
    """Return the deterministic small sequence-model example."""

    return TrainingWorkload(transformer_model, transformer_dataset)


def model(hidden_width: int = 8) -> nn.Sequential:
    if type(hidden_width) is not int or not 1 <= hidden_width <= 32768:
        raise ValueError("Hidden width must be an integer in 1..32768")
    torch.manual_seed(7)
    return nn.Sequential(nn.Linear(4, hidden_width), nn.Tanh(), nn.Linear(hidden_width, 1))


def parameters(hidden_width: int = 8) -> dict[str, FloatArray]:
    return {
        name: value.detach().cpu().numpy().copy()
        for name, value in model(hidden_width).named_parameters()
    }


def parameters_for(workload: TrainingWorkload) -> dict[str, FloatArray]:
    """Export a workload's initial model state for shard and checkpoint setup."""

    return {
        name: value.detach().cpu().numpy().astype(np.float32, copy=True)
        for name, value in workload.model_factory().named_parameters()
    }


def load_parameters(network: nn.Module, values: dict[str, FloatArray]) -> None:
    expected = dict(network.named_parameters())
    if values.keys() != expected.keys():
        raise ValueError("Shard manifest must cover exactly the model parameters")
    for name, parameter in expected.items():
        if values[name].shape != tuple(parameter.shape) or values[name].dtype != np.float32:
            raise ValueError("Parameter shape and dtype must match the model exactly")
        if not np.isfinite(values[name]).all():
            raise ValueError("Parameter values must be finite")
    with torch.no_grad():
        for name, parameter in expected.items():
            parameter.copy_(torch.from_numpy(values[name]).to(parameter.device))


def dataset(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(100 + worker_index)
    inputs = torch.randn(32, 4, generator=generator)
    targets = inputs @ torch.tensor([[1.0], [-2.0], [0.5], [3.0]]) + 0.25
    return inputs, targets


def linear_model() -> nn.Linear:
    torch.manual_seed(11)
    return nn.Linear(4, 1)


def linear_dataset(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(200 + worker_index)
    inputs = torch.randn(32, 4, generator=generator)
    weights = torch.tensor([[1.0], [-2.0], [0.5], [3.0]])
    return inputs, inputs @ weights + 0.25


def cnn_model() -> nn.Sequential:
    torch.manual_seed(12)
    return nn.Sequential(
        nn.Conv2d(1, 4, kernel_size=3, padding=1),
        nn.ReLU(),
        nn.AdaptiveAvgPool2d((1, 1)),
        nn.Flatten(),
        nn.Linear(4, 1),
    )


def cnn_dataset(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(300 + worker_index)
    inputs = torch.randn(16, 1, 8, 8, generator=generator)
    return inputs, inputs.mean(dim=(1, 2, 3), keepdim=False).unsqueeze(1)


def transformer_model() -> nn.Sequential:
    torch.manual_seed(13)
    encoder = nn.TransformerEncoderLayer(
        d_model=8,
        nhead=2,
        dim_feedforward=16,
        dropout=0.0,
        batch_first=True,
    )
    return nn.Sequential(
        nn.TransformerEncoder(encoder, num_layers=1),
        nn.Flatten(start_dim=1),
        nn.Linear(6 * 8, 1),
    )


def transformer_dataset(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(400 + worker_index)
    inputs = torch.randn(16, 6, 8, generator=generator)
    return inputs, inputs.mean(dim=(1, 2), keepdim=False).unsqueeze(1)


def local_reference(
    workers: int,
    steps: int,
    learning_rate: float,
    hidden_width: int = 8,
    *,
    workload: TrainingWorkload | None = None,
) -> dict[str, FloatArray]:
    active = workload or bundled_workload(hidden_width)
    reference = active.model_factory()
    optimizer = torch.optim.SGD(reference.parameters(), lr=learning_rate)
    batches = [active.dataset_factory(index) for index in range(workers)]
    inputs = torch.cat([batch[0] for batch in batches])
    targets = torch.cat([batch[1] for batch in batches])
    for _ in range(steps):
        optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(reference(inputs), targets)
        torch.autograd.backward(loss)
        optimizer.step()
    return {
        name: value.detach().cpu().numpy().copy() for name, value in reference.named_parameters()
    }

"""Small deterministic CPU workload; the distributed protocol is model-independent."""

import numpy as np
import torch
from torch import nn

from paramesh.tensors import FloatArray


def model() -> nn.Sequential:
    torch.manual_seed(7)
    return nn.Sequential(nn.Linear(4, 8), nn.Tanh(), nn.Linear(8, 1))


def parameters() -> dict[str, FloatArray]:
    return {name: value.detach().numpy().copy() for name, value in model().named_parameters()}


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
            parameter.copy_(torch.from_numpy(values[name]))


def dataset(worker_index: int) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(100 + worker_index)
    inputs = torch.randn(32, 4, generator=generator)
    targets = inputs @ torch.tensor([[1.0], [-2.0], [0.5], [3.0]]) + 0.25
    return inputs, targets


def local_reference(workers: int, steps: int, learning_rate: float) -> dict[str, FloatArray]:
    reference = model()
    optimizer = torch.optim.SGD(reference.parameters(), lr=learning_rate)
    batches = [dataset(index) for index in range(workers)]
    inputs = torch.cat([batch[0] for batch in batches])
    targets = torch.cat([batch[1] for batch in batches])
    for _ in range(steps):
        optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(reference(inputs), targets)
        torch.autograd.backward(loss)
        optimizer.step()
    return {name: value.detach().numpy().copy() for name, value in reference.named_parameters()}

import grpc
import numpy as np
import pytest
from test_coordinator import config
from test_shard import update, weight

from paramesh.shard import ParameterShard
from paramesh.worker import _push
from paramesh.workload import load_parameters, model, parameters


def test_parameter_loading_rejects_broadcastable_shapes_before_mutating():
    network = model()
    values = parameters()
    values["0.weight"] = np.ones((1, 4), dtype=np.float32)
    with pytest.raises(ValueError, match="shape"):
        load_parameters(network, values)
    for name, value in network.named_parameters():
        np.testing.assert_array_equal(value.detach().numpy(), parameters()[name])


def test_retry_after_lost_response_preserves_exact_update_and_commits_once():
    shard = ParameterShard(config(), {"weight": np.ones(1, dtype=np.float32)})

    class LostResponse(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.DEADLINE_EXCEEDED

    class Transport:
        calls = 0

        def PushGradients(self, request, timeout):
            self.calls += 1
            result = shard.push(request)
            if self.calls == 1:
                raise LostResponse()
            return result

    client = Transport()
    assert _push(client, update(), 1).duplicate
    assert client.calls == 2
    assert weight(shard) == pytest.approx(0.8)

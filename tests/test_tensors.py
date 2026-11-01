import numpy as np
import pytest

from paramesh.tensors import decode, encode, partition


def test_wire_roundtrip_owns_memory_and_uses_float32():
    original = np.arange(6, dtype=np.float32).reshape(2, 3)
    result = decode(encode("weights", original))
    np.testing.assert_array_equal(result, original)
    result[0, 0] = 99
    assert original[0, 0] == 0


@pytest.mark.parametrize("values", [np.array([np.nan]), np.array([np.inf])])
def test_non_finite_values_are_rejected(values):
    with pytest.raises(ValueError, match="finite"):
        encode("weights", values.astype(np.float32))


def test_invalid_wire_metadata_is_rejected():
    message = encode("weights", np.ones((2, 3), dtype=np.float32))
    message.shape[:] = [2, 4]
    with pytest.raises(ValueError, match="byte length"):
        decode(message)
    message.shape[:] = [2**63]
    with pytest.raises(ValueError, match="size"):
        decode(message)
    message.shape[:] = [2, 3]
    message.dtype = "pickle"
    with pytest.raises(ValueError, match="dtype"):
        decode(message)


def test_sharding_is_deterministic_and_complete():
    names = [f"layer.{i}.weight" for i in range(32)]
    first = partition(names, 4)
    assert first == partition(reversed(names), 4)
    assert set(first) == set(names)
    assert set(first.values()) == {0, 1, 2, 3}
    with pytest.raises(ValueError):
        partition(names, 0)

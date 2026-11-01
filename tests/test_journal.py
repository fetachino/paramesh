import pytest
from test_coordinator import config
from test_shard import update

from paramesh.journal import Journal
from paramesh.state import StateDB


def test_gradient_requests_are_durable_before_delivery_and_completion(tmp_path):
    path = tmp_path / "worker.sqlite"
    store = StateDB(path)
    first = Journal(config(), "worker-0", store)
    first.prepare([update()], 2.5)
    store.close()
    reopened = StateDB(path)
    resumed = Journal(config(), "worker-0", reopened)
    assert resumed.record.next_step == 0
    assert resumed.record.requests[0] == update()
    assert resumed.record.loss == 2.5
    resumed.complete()
    assert resumed.record.next_step == 1 and not resumed.record.requests
    reopened.close()


def test_journal_rejects_changed_identity_and_nonfinite_loss(tmp_path):
    store = StateDB(tmp_path / "worker.sqlite")
    journal = Journal(config(), "worker-0", store)
    with pytest.raises(ValueError, match="identity"):
        Journal(config(), "worker-1", store)
    with pytest.raises(ValueError, match="finite"):
        journal.prepare([update()], float("nan"))
    changed = update(step=1)
    with pytest.raises(ValueError, match="step"):
        journal.prepare([changed], 1)
    assert journal.record.next_step == 0 and not journal.record.requests
    store.close()

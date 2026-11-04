# Windows synchronous checkpoint barrier fix

This record captures the intermittent high-rate two-shard checkpoint failure and
the focused fix. It is local Windows evidence; it does not change or validate the
Google Cloud production deployment.

## Failure and root cause

On source `9224217cba8c13b44fbdc2ab4df3fe17005909f6`, the full Windows suite
reported 138 passing tests and one failure at
`tests/test_checkpoint_epochs.py::test_sync_checkpoint_recovers_high_rate_two_shard_barrier`.
Five focused repetitions reproduced the failure twice. The failing run left the
coordinator in `CHECKPOINT_REQUESTED` with only `worker-0` acknowledged while
`worker-1` waited in shard 0's synchronous barrier.

The root cause was the generic worker `_rpc` retry policy. It retried
`DEADLINE_EXCEEDED` from `PushGradients` three times, so the outer synchronous
recovery path never saw the first barrier deadline and could not discard its
uncommitted journal before acknowledging the checkpoint. The server-side
barrier could also retain a canceled contribution until its condition deadline,
allowing checkpoint freeze to race a late abort.

## Fix

The fix in `c473f7e519488c5fb31cb1d7530815269b66f603` makes deadline retry
explicit and disables it only for `PushGradients`, preserving the existing
lost-response/idempotent retry behavior for other callers. A canceled shard
gradient RPC now aborts the uncommitted synchronous barrier and wakes waiters
before checkpoint freeze can proceed. No timeout was increased, no sleep was
added to production logic, and no assertion was weakened.

## Verification

- 10 repeated Windows high-rate runs: 10 passed, 0 failed.
- Full locked Windows suite: 141 passed, 0 failed, 91.42% coverage.
- Linux container regression suite: 3 passed, including the high-rate test,
  lost-response retry, and canceled-barrier recovery tests.
- Ruff and strict mypy: passed.

The raw measured summary and diagnostic timeline are in
[`results.json`](results.json). The full Linux suite was not repeated locally;
the Linux regression path above is supplemented by the required Ubuntu CI job.

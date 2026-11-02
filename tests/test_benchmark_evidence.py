"""Verify the immutable recorded baseline, independently of new measurements."""

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/evidence/benchmarks/uncompressed-local-2026-11-02"
WIDE = ROOT / "docs/evidence/benchmarks/uncompressed-wide-sync-local-2026-11-02"


def test_recorded_baseline_bytes_counts_and_provenance_are_consistent():
    for line in (BASELINE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert Path(name).name == name
        assert hashlib.sha256((BASELINE / name).read_bytes()).hexdigest() == digest
    manifest = json.loads((BASELINE / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert (
        manifest["lock_sha256"] == hashlib.sha256((BASELINE / "uv.lock").read_bytes()).hexdigest()
    )
    assert Counter(row["mode"] for row in manifest["trials"]) == {
        "sync": 3,
        "async": 3,
        "bounded": 3,
    }
    with (BASELINE / "rpc.csv").open(newline="") as stream:
        samples = list(csv.DictReader(stream))
    assert len(samples) == 21730 and all(item["status"] == "OK" for item in samples)
    for row in manifest["trials"]:
        assert row["commit"] == "7d9a946a3e51f40b06d21d1aad06350ac9f35c3c"
        assert row["source_dirty"] is False
        raw = json.loads((BASELINE / f"trial-{row['trial']:03d}-{row['mode']}.json").read_text())
        assert raw["workload"]["parameter_bytes"] == 196
        assert all(
            len(worker["losses"]) == 200
            and worker["resumed_from"] == 20
            and worker["measurement"]["sample_drops"] == 0
            for worker in raw["worker_results"]
        )
        observed = [item for item in samples if int(item["trial"]) == row["trial"]]
        assert len(observed) == row["rpc_calls"]
        assert (
            sum(int(item["request_bytes"]) + int(item["response_bytes"]) for item in observed)
            == row["protobuf_bytes"]
        )
        assert math.isclose(row["examples_per_second"], 12800 / row["window_seconds"])
        if row["mode"] == "sync":
            assert raw["max_parameter_error"] < 1e-6


def test_recorded_larger_payload_trials_preserve_real_rpc_and_reference_evidence():
    for line in (WIDE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert Path(name).name == name
        assert hashlib.sha256((WIDE / name).read_bytes()).hexdigest() == digest
    manifest = json.loads((WIDE / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert manifest["configuration"]["hidden_width"] == 256
    assert manifest["configuration"]["measured_steps"] == 50
    assert len(manifest["trials"]) == 3
    with (WIDE / "rpc.csv").open(newline="") as stream:
        samples = list(csv.DictReader(stream))
    assert len(samples) == 1832 and all(item["status"] == "OK" for item in samples)
    for row in manifest["trials"]:
        assert row["commit"] == "e08be5be8ec64d873093515179641fe54d78787d"
        assert row["source_dirty"] is False
        assert row["max_parameter_error"] < 1e-6
        raw = json.loads((WIDE / f"trial-{row['trial']:03d}-sync.json").read_text())
        assert raw["workload"]["parameter_bytes"] == 6148
        assert all(len(worker["losses"]) == 50 for worker in raw["worker_results"])
        observed = [item for item in samples if int(item["trial"]) == row["trial"]]
        assert len(observed) == row["rpc_calls"]
        assert (
            sum(int(item["request_bytes"]) + int(item["response_bytes"]) for item in observed)
            == row["protobuf_bytes"]
        )

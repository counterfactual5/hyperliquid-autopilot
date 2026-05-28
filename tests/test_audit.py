"""Schema-stability tests for the hyperliquid-autopilot audit emitter.

Downstream consumers (jq queries, the upcoming cross-project consolidator) depend
on the JSON-line schema staying byte-stable across releases. These tests pin:

  - The set of required keys.
  - The project tag for this repo.
  - That ``run_id`` is sourced from ``STAGEFORGE_RUN_ID`` by default.
  - That unknown events are rejected.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

from hyperliquid_autopilot import audit


REQUIRED_KEYS = {
    "ts",
    "ts_unix",
    "event",
    "project",
    "run_id",
    "chain",
    "wallet",
    "tx_hash",
    "error_code",
    "details",
}


def test_required_keys_present():
    record = audit.build_record(event=audit.EVENT_BROADCAST)
    assert set(record.keys()) == REQUIRED_KEYS


def test_project_tag_matches_repo():
    record = audit.build_record(event=audit.EVENT_QUOTE)
    assert record["project"] == "hyperliquid-autopilot"


def test_unknown_event_rejected():
    try:
        audit.build_record(event="zzz")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown event")


def test_run_id_pulled_from_stageforge_env():
    with mock.patch.dict(os.environ, {"STAGEFORGE_RUN_ID": "run-7"}, clear=True):
        record = audit.build_record(event=audit.EVENT_SIGN)
    assert record["run_id"] == "run-7"


def test_emit_to_file_one_record_per_line():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "audit.jsonl")
        with mock.patch.dict(os.environ, {"AUDIT_LOG_PATH": path}, clear=True):
            audit.log_event(event=audit.EVENT_BROADCAST, chain="hyperliquid", wallet="0xabc")
            audit.log_event(event=audit.EVENT_CANCEL, chain="hyperliquid", wallet="0xabc")
        with open(path, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        assert len(lines) == 2
        assert lines[0]["event"] == "broadcast"
        assert lines[1]["event"] == "cancel"

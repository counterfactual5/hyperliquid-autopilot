"""Tests for the trade execution state machine."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from hyperliquid_autopilot import state_machine


class TestStateMachineHappyPath(unittest.TestCase):
    """Happy path: init → preflight → signed → broadcast → confirmed."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "test-happy-path-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)

    def test_happy_path(self) -> None:
        s = state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT, payload={"chain": "ethereum"})
        self.assertEqual(s["current_state"], state_machine.STATE_PREFLIGHT)
        self.assertEqual(len(s["transition_log"]), 1)

        s = state_machine.transition(self.run_id, state_machine.STATE_SIGNED)
        self.assertEqual(s["current_state"], state_machine.STATE_SIGNED)
        self.assertEqual(len(s["transition_log"]), 2)

        s = state_machine.transition(self.run_id, state_machine.STATE_BROADCAST, payload={"tx_hash": "0xabc"})
        self.assertEqual(s["current_state"], state_machine.STATE_BROADCAST)
        self.assertEqual(s["payload"]["tx_hash"], "0xabc")

        s = state_machine.transition(self.run_id, state_machine.STATE_CONFIRMED)
        self.assertEqual(s["current_state"], state_machine.STATE_CONFIRMED)
        self.assertEqual(len(s["transition_log"]), 4)
        self.assertIn(self.run_id, s["run_id"])


class TestStateMachineIdempotent(unittest.TestCase):
    """Calling the same transition twice is a no-op."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "test-idempotent-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)

    def test_idempotent(self) -> None:
        s1 = state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT)
        self.assertEqual(s1["current_state"], state_machine.STATE_PREFLIGHT)
        log_len = len(s1["transition_log"])

        # Same transition again — must be no-op.
        s2 = state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT)
        self.assertEqual(s2["current_state"], state_machine.STATE_PREFLIGHT)
        self.assertEqual(len(s2["transition_log"]), log_len, "idempotent transition should not add to log")


class TestStateMachineInvalid(unittest.TestCase):
    """Skipping steps raises ValueError."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "test-invalid-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)

    def test_invalid_skip(self) -> None:
        state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT)
        with self.assertRaises(ValueError):
            state_machine.transition(self.run_id, state_machine.STATE_CONFIRMED)


class TestStateMachineTerminal(unittest.TestCase):
    """Terminal states reject further transitions."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "test-terminal-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)

    def test_terminal(self) -> None:
        state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT)
        state_machine.transition(self.run_id, state_machine.STATE_SIGNED)
        state_machine.transition(self.run_id, state_machine.STATE_BROADCAST)
        state_machine.transition(self.run_id, state_machine.STATE_CONFIRMED)

        with self.assertRaises(RuntimeError):
            state_machine.transition(self.run_id, state_machine.STATE_SIGNED)


class TestStateMachineResume(unittest.TestCase):
    """load_state / init_state resume from the correct checkpoint."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "test-resume-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)

    def test_resume(self) -> None:
        # Simulate a run that crashed half-way.
        state_machine.transition(self.run_id, state_machine.STATE_PREFLIGHT, payload={"chain": "base"})
        state_machine.transition(self.run_id, state_machine.STATE_SIGNED)
        state_machine.transition(self.run_id, state_machine.STATE_BROADCAST, payload={"tx_hash": "0xdef"})

        # New process: load state and check checkpoint.
        loaded = state_machine.load_state(self.run_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["current_state"], state_machine.STATE_BROADCAST)
        self.assertEqual(loaded["payload"]["tx_hash"], "0xdef")

        # Can continue from the checkpoint.
        s = state_machine.transition(self.run_id, state_machine.STATE_CONFIRMED)
        self.assertEqual(s["current_state"], state_machine.STATE_CONFIRMED)


class TestStateMachineEnvVars(unittest.TestCase):
    """run_id resolution respects STAGEFORGE_RUN_ID and AUDIT_RUN_ID env vars."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)
        os.environ.pop("STAGEFORGE_RUN_ID", None)
        os.environ.pop("AUDIT_RUN_ID", None)

    def test_stageforge_run_id(self) -> None:
        os.environ["STAGEFORGE_RUN_ID"] = "sf-run-42"
        s = state_machine.transition("sf-run-42", state_machine.STATE_PREFLIGHT)
        self.assertEqual(s["run_id"], "sf-run-42")

    def test_audit_run_id(self) -> None:
        os.environ["AUDIT_RUN_ID"] = "audit-run-99"
        s = state_machine.transition("audit-run-99", state_machine.STATE_PREFLIGHT)
        self.assertEqual(s["run_id"], "audit-run-99")


if __name__ == "__main__":
    unittest.main()

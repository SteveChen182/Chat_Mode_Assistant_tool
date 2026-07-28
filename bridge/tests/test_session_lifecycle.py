import os
import sys
import unittest
from unittest.mock import patch


BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

import bridge_server


class FakeSession:
    created = []

    def __init__(self, assistant=None, conversation_id=None):
        self.assistant = assistant
        self.conversation_id = conversation_id
        self.session_id = None
        self.is_waiting_input = False
        self.is_alive = True
        self.started = False
        self.stopped = False
        self.pid = 1234
        self.started_at = 100.0
        self.last_output_at = 101.0
        self.last_error = None
        self.__class__.created.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.is_alive = False


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.original_session = bridge_server._current_session
        bridge_server._current_session = None
        FakeSession.created = []

    def tearDown(self):
        bridge_server._current_session = self.original_session

    def _start(self, assistant="sighting_assistant", conversation_id=None, force_restart=False):
        with (
            patch.object(bridge_server, "ChatSession", FakeSession),
            patch.object(bridge_server, "_init_session_log"),
            patch.object(bridge_server, "_close_session_log"),
            patch.object(bridge_server, "_session_log"),
        ):
            return bridge_server._start_session(
                assistant,
                conversation_id,
                force_restart=force_restart,
            )

    def test_reuses_only_matching_assistant_and_conversation(self):
        existing = FakeSession("sighting_assistant", "cid-a")
        bridge_server._current_session = existing

        session, reused = self._start(conversation_id="cid-a")

        self.assertIs(session, existing)
        self.assertTrue(reused)
        self.assertFalse(existing.stopped)

    def test_different_conversation_replaces_existing_session(self):
        existing = FakeSession("sighting_assistant", "cid-a")
        bridge_server._current_session = existing

        session, reused = self._start(conversation_id="cid-b")

        self.assertFalse(reused)
        self.assertTrue(existing.stopped)
        self.assertTrue(session.started)
        self.assertEqual(session.conversation_id, "cid-b")

    def test_force_restart_replaces_matching_session(self):
        existing = FakeSession("sighting_assistant", "cid-a")
        bridge_server._current_session = existing

        session, reused = self._start(conversation_id="cid-a", force_restart=True)

        self.assertFalse(reused)
        self.assertTrue(existing.stopped)
        self.assertIsNot(session, existing)
        self.assertTrue(session.started)

    def test_tool_answer_does_not_restart_idle_ready_timer(self):
        session = bridge_server.ChatSession()
        with (
            patch.object(session, "_cancel_idle_timer") as cancel_timer,
            patch.object(session, "_reset_idle_timer") as reset_timer,
        ):
            tool_event = session._classify_event({
                "steps": [{"name": "read_article", "type": "tool", "args": {}}],
            })
            answer_event = session._classify_event({"answer": "working..."})

        self.assertEqual(tool_event["type"], "tool_start")
        self.assertEqual(answer_event["type"], "answer")
        cancel_timer.assert_called_once()
        reset_timer.assert_not_called()

    def test_health_reports_actual_gnai_conversation_id(self):
        session = FakeSession("sighting_assistant", "requested-cid")
        session.session_id = "actual-cid"
        bridge_server._current_session = session
        handler = object.__new__(bridge_server.BridgeHandler)
        captured = {}

        def capture_response(status, payload):
            captured.update({"status": status, "payload": payload})

        handler._json_response = capture_response
        handler._handle_health()

        self.assertEqual(captured["status"], 200)
        self.assertEqual(captured["payload"]["conversation_id"], "actual-cid")


if __name__ == "__main__":
    unittest.main()
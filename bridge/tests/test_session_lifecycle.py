import os
import sys
import unittest
from unittest.mock import MagicMock, patch


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
        bridge_server._cancel_scheduled_shutdown()
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

    def test_welcome_defers_cid_expiry_until_healthy_prompt(self):
        session = bridge_server.ChatSession(conversation_id="requested-cid")

        event = session._classify_event({"msg": "Welcome 👋. I'm GNAI"})

        self.assertEqual(event["type"], "info")
        self.assertTrue(session._pending_cid_expired)
        self.assertTrue(session.event_queue.empty())

        session._process_line("> ")

        self.assertEqual(session.event_queue.get_nowait()["type"], "cid_expired")
        self.assertEqual(session.event_queue.get_nowait()["type"], "ready")

    def test_config_repair_cancels_expiry_and_requests_same_session(self):
        session = bridge_server.ChatSession(
            assistant="sighting_assistant",
            conversation_id="requested-cid",
        )
        session._pending_cid_expired = True
        completed = type("Completed", (), {"returncode": 0, "stderr": ""})()

        with (
            patch.object(bridge_server.os.path, "exists", return_value=True),
            patch.object(bridge_server.subprocess, "run", return_value=completed),
        ):
            session._handle_config_error("unable to load configuration")

        event = session.event_queue.get_nowait()
        self.assertFalse(session._pending_cid_expired)
        self.assertEqual(event["type"], "config_repaired")
        self.assertEqual(event["assistant"], "sighting_assistant")
        self.assertEqual(event["conversation_id"], "requested-cid")

    def test_bridge_owned_shutdown_timer_stops_session_and_server(self):
        server = type("Server", (), {"shutdown": MagicMock()})()
        captured = {}

        class FakeTimer:
            daemon = False

            def __init__(self, delay, callback):
                captured.update({"delay": delay, "callback": callback, "cancelled": False})

            def start(self):
                captured["started"] = True

            def cancel(self):
                captured["cancelled"] = True

        with (
            patch.object(bridge_server.threading, "Timer", FakeTimer),
            patch.object(bridge_server, "_stop_session") as stop_session,
        ):
            bridge_server._schedule_shutdown(server, 10)
            self.assertEqual(captured["delay"], 10)
            self.assertTrue(captured["started"])
            captured["callback"]()

        stop_session.assert_called_once_with()
        server.shutdown.assert_called_once_with()

    def test_bridge_owned_shutdown_timer_can_be_cancelled(self):
        timer = MagicMock()
        bridge_server._shutdown_timer = timer

        bridge_server._cancel_scheduled_shutdown()

        timer.cancel.assert_called_once_with()
        self.assertIsNone(bridge_server._shutdown_timer)


if __name__ == "__main__":
    unittest.main()
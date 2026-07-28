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


if __name__ == "__main__":
    unittest.main()
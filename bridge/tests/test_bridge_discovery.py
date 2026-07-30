import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

import bridge_server
import native_host


class BridgeDiscoveryTests(unittest.TestCase):
    def test_discovery_write_contains_instance_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery_path = os.path.join(temp_dir, "bridge.discovery.json")
            with patch.object(bridge_server, "_DISCOVERY_FILE", discovery_path):
                bridge_server._write_discovery_file(49152)
                discovery = bridge_server._read_discovery_file()

            self.assertEqual(discovery["instance_id"], bridge_server.INSTANCE_ID)
            self.assertEqual(discovery["protocol_version"], bridge_server.PROTOCOL_VERSION)
            self.assertEqual(discovery["pid"], os.getpid())
            self.assertEqual(discovery["port"], 49152)

    def test_old_instance_does_not_remove_new_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery_path = os.path.join(temp_dir, "bridge.discovery.json")
            with open(discovery_path, "w", encoding="utf-8") as f:
                json.dump({"instance_id": "new-instance"}, f)

            with patch.object(bridge_server, "_DISCOVERY_FILE", discovery_path):
                removed = bridge_server._remove_discovery_file("old-instance")

            self.assertFalse(removed)
            self.assertTrue(os.path.exists(discovery_path))

    def test_old_instance_does_not_remove_new_legacy_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery_path = os.path.join(temp_dir, "bridge.discovery.json")
            pid_path = os.path.join(temp_dir, "bridge.pid")
            port_path = os.path.join(temp_dir, "bridge.port")
            with open(discovery_path, "w", encoding="utf-8") as f:
                json.dump({"instance_id": "new-instance"}, f)
            with open(pid_path, "w", encoding="ascii") as f:
                f.write("999")
            with open(port_path, "w", encoding="ascii") as f:
                f.write("49152")

            with (
                patch.object(bridge_server, "_DISCOVERY_FILE", discovery_path),
                patch.object(bridge_server, "_PID_FILE", pid_path),
                patch.object(bridge_server, "_PORT_FILE", port_path),
            ):
                removed = bridge_server._cleanup_discovery_files("old-instance")

            self.assertFalse(removed)
            self.assertTrue(os.path.exists(pid_path))
            self.assertTrue(os.path.exists(port_path))

    def test_native_host_accepts_matching_health_identity(self):
        identity = {
            "instance_id": "instance-a",
            "protocol_version": 2,
            "pid": 123,
            "port": 49152,
        }
        opener = self._health_opener({
            "status": "ok",
            "instance_id": "instance-a",
            "protocol_version": 2,
            "pid": 123,
        })

        with (
            patch.object(native_host, "_read_bridge_identity", return_value=identity.copy()),
            patch.object(native_host.urllib.request, "build_opener", return_value=opener),
        ):
            running, discovered = native_host.is_bridge_running()

        self.assertTrue(running)
        self.assertEqual(discovered["instance_id"], "instance-a")

    def test_native_host_rejects_mismatched_health_identity(self):
        identity = {
            "instance_id": "instance-a",
            "protocol_version": 2,
            "pid": 123,
            "port": 49152,
        }
        opener = self._health_opener({
            "status": "ok",
            "instance_id": "instance-b",
            "protocol_version": 2,
            "pid": 123,
        })

        with (
            patch.object(native_host, "_read_bridge_identity", return_value=identity.copy()),
            patch.object(native_host.urllib.request, "build_opener", return_value=opener),
        ):
            running, discovered = native_host.is_bridge_running()

        self.assertFalse(running)
        self.assertIsNone(discovered)

    def test_native_host_reset_terminates_process_tree_and_clears_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery_path = os.path.join(temp_dir, "bridge.discovery.json")
            pid_path = os.path.join(temp_dir, "bridge.pid")
            port_path = os.path.join(temp_dir, "bridge.port")
            for path in (discovery_path, pid_path, port_path):
                with open(path, "w", encoding="ascii") as f:
                    f.write("stale")

            result = MagicMock(returncode=0, stderr="")
            with (
                patch.object(native_host, "DISCOVERY_FILE", discovery_path),
                patch.object(native_host, "PID_FILE", pid_path),
                patch.object(native_host, "PORT_FILE", port_path),
                patch.object(native_host, "_read_bridge_identity", return_value={"pid": 4321}),
                patch.object(native_host, "_is_pid_alive", side_effect=[True, False, False]),
                patch.object(native_host.subprocess, "run", return_value=result) as taskkill,
            ):
                terminated_pid = native_host._terminate_bridge_process()

            self.assertEqual(terminated_pid, 4321)
            taskkill.assert_called_once_with(
                ["taskkill", "/PID", "4321", "/F", "/T"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertFalse(os.path.exists(discovery_path))
            self.assertFalse(os.path.exists(pid_path))
            self.assertFalse(os.path.exists(port_path))

    def test_native_host_shutdown_terminates_without_relaunch(self):
        with (
            patch.object(native_host, "read_message", return_value={"action": "shutdown"}),
            patch.object(native_host, "_terminate_bridge_process", return_value=4321) as terminate,
            patch.object(native_host, "launch_bridge") as launch,
            patch.object(native_host, "send_message") as send,
        ):
            native_host.main()

        terminate.assert_called_once_with()
        launch.assert_not_called()
        send.assert_called_once_with({"status": "stopped", "previous_pid": 4321})

    @staticmethod
    def _health_opener(payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode("utf-8")
        opener = MagicMock()
        opener.open.return_value = response
        return opener


if __name__ == "__main__":
    unittest.main()
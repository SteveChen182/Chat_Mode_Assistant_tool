import os
import sys
import tempfile
import unittest
from unittest.mock import patch


BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

import bridge_server


class ToolkitUpdateTests(unittest.TestCase):
    def test_reads_sighting_path_from_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write(
                    "toolkits:\n"
                    "- name: displaydebugger\n"
                    "  path: 'C:\\toolkits\\displaydebugger'\n"
                    "- name: sighting\n"
                    "  type: github\n"
                    "  path: 'C:\\custom\\SightingAssistantTool'\n"
                )

            self.assertEqual(
                bridge_server._read_sighting_toolkit_path(config_path),
                "C:\\custom\\SightingAssistantTool",
            )

    def test_resolver_prefers_configured_git_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            toolkit_dir = os.path.join(temp_dir, "custom-toolkit")
            os.makedirs(os.path.join(home_dir, ".gnai"))
            os.makedirs(os.path.join(toolkit_dir, ".git"))
            with open(os.path.join(home_dir, ".gnai", "config.yaml"), "w", encoding="utf-8") as config_file:
                config_file.write(f"toolkits:\n- name: sighting\n  path: '{toolkit_dir}'\n")

            with (
                patch.object(bridge_server.os.path, "expanduser", side_effect=lambda path: home_dir if path == "~" else path),
                patch.dict(os.environ, {"GNAI_TOOLKIT_DIRECTORY": ""}),
                patch.object(bridge_server.sys, "frozen", True, create=True),
            ):
                resolved, checked = bridge_server._resolve_sighting_toolkit_repo()

            self.assertEqual(resolved, os.path.abspath(toolkit_dir))
            self.assertIn(os.path.abspath(toolkit_dir), checked)

    def test_resolver_skips_invalid_environment_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = os.path.join(temp_dir, "home")
            fallback_dir = os.path.join(home_dir, ".gnai", "toolkits", "sighting")
            os.makedirs(os.path.join(fallback_dir, ".git"))

            with (
                patch.object(bridge_server.os.path, "expanduser", side_effect=lambda path: home_dir if path == "~" else path),
                patch.dict(os.environ, {"GNAI_TOOLKIT_DIRECTORY": os.path.join(temp_dir, "missing")}),
                patch.object(bridge_server.sys, "frozen", True, create=True),
            ):
                resolved, checked = bridge_server._resolve_sighting_toolkit_repo()

            self.assertEqual(resolved, os.path.abspath(fallback_dir))
            self.assertEqual(checked[0], os.path.abspath(os.path.join(temp_dir, "missing")))


if __name__ == "__main__":
    unittest.main()
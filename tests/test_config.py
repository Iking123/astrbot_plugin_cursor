from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from cursor_provider.config import (
    choose_model,
    parse_builtin_tools,
    parse_settings,
    resolve_api_key,
    resolve_workspace,
    workspace_block_reason,
)
from cursor_provider.errors import CursorPluginError, MissingApiKeyError


class ConfigTests(unittest.TestCase):
    def test_builtin_tool_modes(self) -> None:
        self.assertEqual(parse_builtin_tools(""), ("none", ()))
        self.assertEqual(parse_builtin_tools("default"), ("default", ()))
        self.assertEqual(parse_builtin_tools("read, grep"), ("allowlist", ("read", "grep")))
        with self.assertRaises(CursorPluginError):
            parse_builtin_tools("read, rm -rf")

    def test_api_key_prefers_plugin_config_and_skips_the_placeholder(self) -> None:
        configured = parse_settings({"runtime": {"api_key": " crsr_plugin "}})
        self.assertEqual(resolve_api_key(configured, {"key": ["crsr_other"]}), "crsr_plugin")

        empty = parse_settings({})
        self.assertEqual(
            resolve_api_key(empty, {"key": ["cursor-plugin", "crsr_provider"]}),
            "crsr_provider",
        )
        with mock.patch.dict(os.environ, {"CURSOR_API_KEY": "crsr_env"}):
            with self.assertRaises(MissingApiKeyError):
                resolve_api_key(empty, {"key": ["cursor-plugin"]})
            allowed = parse_settings({"runtime": {"allow_env_key": True}})
            self.assertEqual(resolve_api_key(allowed, {}), "crsr_env")

    def test_choose_model_uses_the_request_then_the_provider_then_the_list(self) -> None:
        self.assertEqual(choose_model("gpt", "composer-2.5", ("auto",)), "gpt")
        self.assertEqual(choose_model("", "composer-2.5", ("auto",)), "composer-2.5")
        self.assertEqual(choose_model(None, "", ("auto",)), "auto")

    def test_workspace_guard(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "astrbot"
            root.mkdir()
            sandbox = resolve_workspace("", root)
            self.assertIsNone(workspace_block_reason(sandbox, root))

            outside = Path(tmp) / "repo"
            self.assertEqual(resolve_workspace(str(outside), root).resolve(), outside.resolve())

            for blocked in (root, root / "data" / "config", root.parent):
                with self.assertRaises(CursorPluginError):
                    resolve_workspace(str(blocked), root)

    def test_rejects_unknown_runtime(self) -> None:
        with self.assertRaises(CursorPluginError):
            parse_settings({"runtime": {"runtime_mode": "remote"}})


if __name__ == "__main__":
    unittest.main()

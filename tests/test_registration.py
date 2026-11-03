from __future__ import annotations

import copy
import unittest

from astrbot.core.config.default import CONFIG_METADATA_2
from astrbot.core.provider.register import provider_cls_map, provider_registry

from cursor_provider.config import KEY_PLACEHOLDER, PROVIDER_TEMPLATE_NAME, PROVIDER_TYPE
from cursor_provider.registration import (
    register_provider_adapter,
    unregister_provider_adapter,
)


def _dashboard_templates() -> dict:
    return CONFIG_METADATA_2["provider_group"]["metadata"]["provider"]["config_template"]


class RegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.templates_before = copy.deepcopy(_dashboard_templates())

    def tearDown(self) -> None:
        unregister_provider_adapter()

    def test_registers_through_the_public_decorator(self) -> None:
        register_provider_adapter()

        self.assertIn(PROVIDER_TYPE, provider_cls_map)
        metadata = provider_cls_map[PROVIDER_TYPE]
        self.assertIs(metadata, next(m for m in provider_registry if m.type == PROVIDER_TYPE))
        self.assertEqual(metadata.provider_display_name, PROVIDER_TEMPLATE_NAME)
        template = metadata.default_config_tmpl
        self.assertIsInstance(template, dict)
        self.assertEqual(template["type"], PROVIDER_TYPE)
        self.assertEqual(template["id"], PROVIDER_TYPE)
        self.assertFalse(template["enable"])
        self.assertEqual(template["key"], [KEY_PLACEHOLDER])
        self.assertEqual(template["provider_type"], "chat_completion")

    def test_does_not_edit_astrbot_config_metadata(self) -> None:
        register_provider_adapter()
        self.assertEqual(_dashboard_templates(), self.templates_before)
        unregister_provider_adapter()
        self.assertEqual(_dashboard_templates(), self.templates_before)

    def test_register_twice_and_unregister(self) -> None:
        register_provider_adapter()
        register_provider_adapter()
        self.assertEqual(
            sum(1 for m in provider_registry if m.type == PROVIDER_TYPE),
            1,
        )

        unregister_provider_adapter()

        self.assertNotIn(PROVIDER_TYPE, provider_cls_map)
        self.assertFalse(any(m.type == PROVIDER_TYPE for m in provider_registry))


if __name__ == "__main__":
    unittest.main()

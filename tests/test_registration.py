from __future__ import annotations

import unittest

from astrbot.core.config.default import CONFIG_METADATA_2
from astrbot.core.provider.register import provider_cls_map

from cursor_provider.config import PROVIDER_TEMPLATE_NAME, PROVIDER_TYPE
from cursor_provider.registration import (
    register_provider_adapter,
    unregister_provider_adapter,
)


class RegistrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        unregister_provider_adapter()

    def test_registers_and_removes_the_dashboard_template(self) -> None:
        register_provider_adapter()

        self.assertIn(PROVIDER_TYPE, provider_cls_map)
        templates = CONFIG_METADATA_2["provider_group"]["metadata"]["provider"][
            "config_template"
        ]
        self.assertEqual(templates[PROVIDER_TEMPLATE_NAME]["type"], PROVIDER_TYPE)
        self.assertEqual(templates[PROVIDER_TEMPLATE_NAME]["key"], ["cursor-plugin"])
        self.assertNotIn(PROVIDER_TYPE, templates)
        self.assertIsNone(provider_cls_map[PROVIDER_TYPE].default_config_tmpl)

        unregister_provider_adapter()

        self.assertNotIn(PROVIDER_TYPE, provider_cls_map)
        self.assertNotIn(PROVIDER_TEMPLATE_NAME, templates)


if __name__ == "__main__":
    unittest.main()

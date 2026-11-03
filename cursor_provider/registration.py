from __future__ import annotations

import copy
from typing import Any

from .config import KEY_PLACEHOLDER, PROVIDER_TEMPLATE_NAME, PROVIDER_TYPE

DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "id": PROVIDER_TYPE,
    "type": PROVIDER_TYPE,
    "enable": False,
    "provider": "cursor",
    "provider_type": "chat_completion",
    "model": "composer-2.5",
    "key": [KEY_PLACEHOLDER],
    "api_base": "https://api.cursor.com",
    "proxy": "",
    "timeout": 180,
    "custom_headers": {},
    "custom_extra_body": {},
}


def register_provider_adapter() -> None:
    """Register the provider through AstrBot's public decorator.

    ``default_config_tmpl`` is what the dashboard reads when it lists provider
    templates, so no AstrBot-internal config structure needs to be edited.
    """
    from astrbot.core.provider.entities import ProviderType
    from astrbot.core.provider.register import (
        register_provider_adapter as astrbot_register_provider_adapter,
    )

    from .provider import ProviderCursor

    unregister_provider_adapter()
    astrbot_register_provider_adapter(
        PROVIDER_TYPE,
        desc="Cursor 插件：使用已配置的 Cursor API Key",
        provider_type=ProviderType.CHAT_COMPLETION,
        default_config_tmpl=copy.deepcopy(DEFAULT_PROVIDER_CONFIG),
        provider_display_name=PROVIDER_TEMPLATE_NAME,
    )(ProviderCursor)


def unregister_provider_adapter() -> None:
    """Drop this plugin's entry so that a plugin reload can register again.

    AstrBot has no public unregister call; only entries of this plugin's
    provider type are removed.
    """
    from astrbot.core.provider.register import provider_cls_map, provider_registry

    provider_cls_map.pop(PROVIDER_TYPE, None)
    provider_registry[:] = [
        metadata for metadata in provider_registry if metadata.type != PROVIDER_TYPE
    ]

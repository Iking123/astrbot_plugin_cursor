from __future__ import annotations

import copy
from typing import Any

from .config import KEY_PLACEHOLDER, PROVIDER_TEMPLATE_NAME, PROVIDER_TYPE

DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "id": "cursor_sdk",
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


def _dashboard_templates() -> dict[str, Any] | None:
    try:
        from astrbot.core.config.default import CONFIG_METADATA_2
    except Exception:
        return None
    try:
        templates = CONFIG_METADATA_2["provider_group"]["metadata"]["provider"][
            "config_template"
        ]
    except Exception:
        return None
    return templates if isinstance(templates, dict) else None


def _inject_dashboard_template() -> None:
    templates = _dashboard_templates()
    if templates is None:
        return
    templates[PROVIDER_TEMPLATE_NAME] = copy.deepcopy(DEFAULT_PROVIDER_CONFIG)


def _remove_dashboard_template() -> None:
    templates = _dashboard_templates()
    if templates is None:
        return
    template = templates.get(PROVIDER_TEMPLATE_NAME)
    if isinstance(template, dict) and template.get("type") == PROVIDER_TYPE:
        templates.pop(PROVIDER_TEMPLATE_NAME, None)


def register_provider_adapter() -> None:
    from astrbot.core.provider.entities import ProviderMetaData, ProviderType
    from astrbot.core.provider.register import provider_cls_map, provider_registry

    from .provider import ProviderCursor

    unregister_provider_adapter()
    _inject_dashboard_template()
    metadata = ProviderMetaData(
        id="default",
        model=None,
        type=PROVIDER_TYPE,
        desc="Cursor 插件：使用已配置的 Cursor API Key",
        provider_type=ProviderType.CHAT_COMPLETION,
        cls_type=ProviderCursor,
        default_config_tmpl=None,
        provider_display_name=PROVIDER_TEMPLATE_NAME,
    )
    provider_registry.append(metadata)
    provider_cls_map[PROVIDER_TYPE] = metadata


def unregister_provider_adapter() -> None:
    from astrbot.core.provider.register import provider_cls_map, provider_registry

    provider_cls_map.pop(PROVIDER_TYPE, None)
    provider_registry[:] = [
        metadata for metadata in provider_registry if metadata.type != PROVIDER_TYPE
    ]
    _remove_dashboard_template()

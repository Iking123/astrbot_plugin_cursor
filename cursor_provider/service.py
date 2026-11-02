from __future__ import annotations

from pathlib import Path

from .config import (
    astrbot_root,
    choose_model,
    default_workspace,
    parse_settings,
    resolve_api_key,
    resolve_timeout,
    resolve_workspace,
)
from .prompt import ImageInput, PreparedTurn
from .runtime import CursorRequest, CursorRuntime

_service: CursorPluginService | None = None


class CursorPluginService:
    def __init__(
        self,
        config: dict | None = None,
        runtime: CursorRuntime | None = None,
        root: Path | None = None,
    ) -> None:
        self.config = config if config is not None else {}
        self.runtime = runtime or CursorRuntime()
        self.root = root

    def settings(self):
        return parse_settings(self.config)

    def is_enabled(self) -> bool:
        return self.settings().enabled

    def root_path(self) -> Path:
        return self.root or astrbot_root()

    def bridge_target(self, provider_config: dict | None = None) -> tuple[str, str]:
        """Return ``(api_key, bridge_workspace)`` without starting a run."""
        settings = self.settings()
        root = self.root_path()
        if settings.runtime_mode == "local":
            workspace = resolve_workspace(settings.workspace, root)
        else:
            workspace = default_workspace(root)
        return resolve_api_key(settings, provider_config), str(workspace)

    def build_request(
        self,
        prepared: PreparedTurn,
        *,
        provider_config: dict,
        model: str | None = None,
        conversation_id: str = "",
    ) -> CursorRequest:
        settings = self.settings()
        root = self.root_path()
        if settings.runtime_mode == "local":
            workspace = resolve_workspace(settings.workspace, root)
            bridge_workspace = workspace
        else:
            workspace = default_workspace(root)
            bridge_workspace = workspace
        provider_model = str(provider_config.get("model") or "")
        return CursorRequest(
            api_key=resolve_api_key(settings, provider_config),
            model=choose_model(model, provider_model, settings.models),
            runtime_mode=settings.runtime_mode,
            workspace=str(workspace),
            bridge_workspace=str(bridge_workspace),
            prompt=prepared.text,
            images=prepared.images,
            builtin_tool_mode=settings.builtin_tool_mode,
            builtin_tools=settings.builtin_tools,
            repo_url=settings.repo_url,
            starting_ref=settings.starting_ref,
            auto_create_pr=settings.auto_create_pr,
            timeout_seconds=resolve_timeout(provider_config, settings),
            max_attempts=settings.max_attempts,
            conversation_id=conversation_id,
        )

    async def aclose(self) -> None:
        await self.runtime.aclose()


def set_service(service: CursorPluginService | None) -> None:
    global _service
    _service = service


def get_service() -> CursorPluginService | None:
    return _service

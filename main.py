from __future__ import annotations

from typing import Any

from quart import request

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:
    from .cursor_provider.provider import ProviderCursor
    from .cursor_provider.registration import (
        register_provider_adapter,
        unregister_provider_adapter,
    )
    from .cursor_provider.service import (
        CursorPluginService,
        get_service,
        set_service,
    )
except ImportError:
    from cursor_provider.provider import ProviderCursor
    from cursor_provider.registration import (
        register_provider_adapter,
        unregister_provider_adapter,
    )
    from cursor_provider.service import (
        CursorPluginService,
        get_service,
        set_service,
    )


class CursorPlugin(Star):
    """Cursor SDK chat provider."""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self.service = CursorPluginService(self.config)

    async def initialize(self) -> None:
        self._remove_owned_web_apis(include_previous_instances=True)
        set_service(self.service)
        if self.service.is_enabled():
            register_provider_adapter()
        self.context.register_web_api(
            "cursor-plugin/test",
            self.api_test,
            ["POST"],
            "测试 Cursor Agent 连接",
        )
        self.context.register_web_api(
            "cursor-plugin/models",
            self.api_models,
            ["GET"],
            "读取 Cursor 账号可用模型",
        )

    async def terminate(self) -> None:
        try:
            await self.service.aclose()
        finally:
            self._remove_owned_web_apis()
            if get_service() is self.service:
                set_service(None)
                unregister_provider_adapter()

    def _remove_owned_web_apis(self, *, include_previous_instances: bool = False) -> None:
        routes = getattr(self.context, "registered_web_apis", None)
        if not isinstance(routes, list):
            return

        def owned(item: Any) -> bool:
            route, handler = item[0], item[1]
            owner = getattr(handler, "__self__", None)
            return (
                isinstance(route, str)
                and route.startswith("cursor-plugin/")
                and owner is not None
                and (
                    owner is self
                    or (
                        include_previous_instances
                        and type(owner).__module__ == type(self).__module__
                        and type(owner).__name__ == type(self).__name__
                    )
                )
            )

        routes[:] = [item for item in routes if not owned(item)]

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("cursor_test")
    async def command_test(self, event: AstrMessageEvent, model: str = ""):
        """测试 Cursor Agent 是否能回复。会真实消耗一次运行额度。"""
        if not self.service.is_enabled():
            yield event.plain_result("Cursor 插件提供商还没有启用。")
            return
        try:
            result = await self._run_test(model)
        except Exception as exc:
            yield event.plain_result(f"Cursor 连接测试失败：{exc}")
            return
        yield event.plain_result(
            "Cursor 连接测试通过。\n"
            f"模型：{result['model']}\n"
            f"耗时：{result['latency_ms']} ms\n"
            f"run_id：{result['run_id']}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("cursor_models")
    async def command_models(self, event: AstrMessageEvent):
        """列出当前 API Key 可用的 Cursor 模型。"""
        if not self.service.is_enabled():
            yield event.plain_result("Cursor 插件提供商还没有启用。")
            return
        try:
            models = await self._provider().get_models()
        except Exception as exc:
            yield event.plain_result(f"读取 Cursor 模型失败：{exc}")
            return
        shown = models[:60]
        lines = "\n".join(shown) if shown else "（空）"
        if len(models) > len(shown):
            lines += f"\n……还有 {len(models) - len(shown)} 个"
        yield event.plain_result(f"Cursor 模型：\n{lines}")

    async def api_test(self) -> dict[str, Any]:
        data = await request.get_json(silent=True) or {}
        model = str(data.get("model") or "").strip()
        try:
            result = await self._run_test(model)
        except Exception as exc:
            return {"status": "error", "message": f"Cursor 测试失败: {exc}"}
        return {
            "status": "ok",
            "message": (
                f"Cursor 测试通过，模型 {result['model']}，耗时 {result['latency_ms']} ms"
            ),
            "data": result,
        }

    async def api_models(self) -> dict[str, Any]:
        try:
            models = await self._provider().get_models()
        except Exception as exc:
            return {"status": "error", "message": f"读取 Cursor 模型失败: {exc}"}
        return {"status": "ok", "message": "ok", "data": {"models": models}}

    async def _run_test(self, model: str) -> dict[str, Any]:
        import time

        provider = self._provider(model)
        started = time.perf_counter()
        response = await provider.text_chat(
            prompt="REPLY PONG ONLY",
            model=model.strip() or None,
        )
        return {
            "model": model.strip() or provider.get_model() or self.service.settings().models[0],
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "run_id": response.id or "",
            "reply": (response.completion_text or "")[:200],
        }

    def _provider(self, model: str = "") -> ProviderCursor:
        selected = model.strip() or (self.service.settings().models[0] if self.service.settings().models else "composer-2.5")
        return ProviderCursor(
            {
                "id": "cursor_plugin",
                "type": "cursor_sdk",
                "model": selected,
                "key": ["cursor-plugin"],
                "timeout": self.service.settings().timeout_seconds,
            },
            {},
        )

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from astrbot.api import logger
from astrbot.core.exceptions import EmptyModelOutputError
from astrbot.core.provider.entities import LLMResponse, TokenUsage
from astrbot.core.provider.provider import Provider

from .config import KEY_PLACEHOLDER
from .errors import (
    CursorPluginError,
    UnsupportedAudioError,
    exception_text,
    redact,
)
from .prompt import prepare_turn
from .service import get_service
from .usage import UsageNumbers


class ProviderCursor(Provider):
    """AstrBot chat provider backed by a Cursor agent."""

    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config, provider_settings or {})
        self.set_model(str(provider_config.get("model") or ""))

    def get_current_key(self) -> str:
        return KEY_PLACEHOLDER

    def set_key(self, key: str) -> None:
        self.provider_config["key"] = [key]

    async def get_models(self) -> list[str]:
        service = self._require_service()
        settings = service.settings()
        try:
            api_key, workspace = service.bridge_target(self.provider_config)
        except CursorPluginError:
            return list(settings.models)
        try:
            live = await service.runtime.list_models(api_key, workspace)
        except Exception as exc:
            logger.warning(
                "Cursor model list failed: %s",
                redact(exception_text(exc), api_key),
            )
            return list(settings.models)
        return live or list(settings.models)

    async def text_chat(self, **kwargs) -> LLMResponse:
        final = None
        async for response in self.text_chat_stream(**kwargs):
            if not response.is_chunk:
                final = response
        if final is None:
            raise CursorPluginError("Cursor 没有返回结果")
        return final

    async def text_chat_stream(self, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        # AstrBot function tools need the current message event, which this
        # provider call does not receive. Cursor therefore answers from the
        # transcript and its own local tools, when those tools are enabled.
        kwargs.pop("func_tool", None)
        request = None
        secret = ""
        try:
            request = self._build_request(**kwargs)
            secret = request.api_key
            async with asyncio.timeout(request.timeout_seconds):
                turn = await self._require_service().runtime.start(request)
                parts: list[str] = []
                try:
                    async for chunk in turn.iter_text():
                        if not chunk:
                            continue
                        parts.append(chunk)
                        yield LLMResponse(
                            "assistant",
                            completion_text=chunk,
                            is_chunk=True,
                        )
                    outcome = await turn.finish()
                finally:
                    await turn.aclose()
            text = outcome.text if outcome.text.strip() else "".join(parts)
            if not text.strip():
                raise EmptyModelOutputError("Cursor Agent 没有返回文本")
            yield LLMResponse(
                "assistant",
                completion_text=text,
                is_chunk=False,
                id=outcome.run_id or None,
                usage=_astr_usage(outcome.usage),
            )
        except EmptyModelOutputError:
            raise
        except CursorPluginError:
            raise
        except TimeoutError:
            raise CursorPluginError(
                f"Cursor 运行超过 {int(request.timeout_seconds if request else 0)} 秒"
            ) from None
        except Exception as exc:
            raise CursorPluginError(redact(exception_text(exc), secret)) from exc

    async def test(self, timeout: float = 180.0) -> None:
        await asyncio.wait_for(
            self.text_chat(prompt="REPLY PONG ONLY"),
            timeout=timeout,
        )

    def _build_request(self, **kwargs):
        service = self._require_service()
        prepared = prepare_turn(
            prompt=kwargs.get("prompt"),
            contexts=kwargs.get("contexts"),
            system_prompt=kwargs.get("system_prompt"),
            tool_calls_result=kwargs.get("tool_calls_result"),
            image_urls=kwargs.get("image_urls"),
            audio_urls=kwargs.get("audio_urls"),
            extra_user_content_parts=kwargs.get("extra_user_content_parts"),
        )
        if prepared.has_audio and not prepared.text.strip() and not prepared.images:
            raise UnsupportedAudioError(
                "Cursor Agent 不能接收音频。请先使用 AstrBot 的语音转文字。"
            )
        if not prepared.text.strip() and not prepared.images:
            raise CursorPluginError("没有可发送给 Cursor 的文本或图片")
        conversation_id = str(kwargs.get("conversation_id") or "")
        return service.build_request(
            prepared,
            provider_config=self.provider_config,
            model=kwargs.get("model") or self.get_model(),
            conversation_id=conversation_id,
        )

    def _require_service(self):
        service = get_service()
        if service is None or not service.is_enabled():
            raise CursorPluginError("Cursor 插件提供商还没有启用")
        return service


def _astr_usage(usage: UsageNumbers | None) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        input_other=usage.input_other,
        input_cached=usage.input_cached,
        output=usage.output,
    )

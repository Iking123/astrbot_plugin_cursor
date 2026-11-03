from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

from astrbot.api import logger

from .errors import CursorPluginError, CursorRunFailedError, exception_text, redact
from .prompt import ImageInput
from .usage import UsageNumbers, map_usage


@dataclass(frozen=True)
class CursorRequest:
    api_key: str
    model: str
    runtime_mode: str
    workspace: str
    bridge_workspace: str
    prompt: str
    images: tuple[ImageInput, ...]
    builtin_tool_mode: str
    builtin_tools: tuple[str, ...]
    repo_url: str
    starting_ref: str
    auto_create_pr: bool
    timeout_seconds: float
    max_attempts: int
    conversation_id: str = ""


@dataclass(frozen=True)
class CursorOutcome:
    text: str
    status: str
    run_id: str
    agent_id: str
    usage: UsageNumbers | None
    model: str = ""


class CursorRuntime:
    """Long-lived SDK bridge. Each AstrBot turn gets a new agent."""

    def __init__(self, client: Any | None = None, sdk_loader: Any | None = None) -> None:
        self._injected = client
        self._sdk_loader = sdk_loader or import_sdk
        self._lock = asyncio.Lock()
        self._client: Any | None = None
        self._bridge: Any | None = None
        self._workspace = ""

    async def start(self, request: CursorRequest) -> SdkCursorTurn:
        sdk = self._load_sdk()
        client = await self._client_for(request.bridge_workspace, sdk)
        attempts = max(1, request.max_attempts)
        idempotency_key = str(uuid.uuid4())
        error_type = getattr(sdk, "CursorAgentError", None)
        last_error: BaseException | None = None
        for attempt in range(attempts):
            agent = None
            agent_cm = None
            try:
                agent, agent_cm = await _open_agent(
                    client,
                    _create_options(sdk, request, idempotency_key),
                )
                run = agent.send(_user_message(sdk, request))
                if inspect.isawaitable(run):
                    run = await run
                logger.info(
                    "Cursor run started model=%s runtime=%s agent_id=%s run_id=%s",
                    request.model,
                    request.runtime_mode,
                    getattr(agent, "agent_id", ""),
                    getattr(run, "id", ""),
                )
                return SdkCursorTurn(agent, agent_cm, run, request.api_key)
            except asyncio.CancelledError:
                await _close_agent(agent, agent_cm)
                raise
            except Exception as exc:
                await _close_agent(agent, agent_cm)
                if error_type is None or not isinstance(exc, error_type):
                    raise
                last_error = exc
                if attempt + 1 >= attempts or not getattr(exc, "is_retryable", False):
                    raise CursorPluginError(
                        "Cursor 请求没有开始："
                        + redact(exception_text(exc), request.api_key)
                    ) from exc
                delay = retry_delay_seconds(exc, attempt)
                logger.info(
                    "Cursor startup failed, retrying in %.1fs (attempt %s/%s)",
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)
        raise CursorPluginError(
            "Cursor 请求没有开始："
            + redact(exception_text(last_error or RuntimeError("unknown")), request.api_key)
        )

    async def list_models(self, api_key: str, workspace: str) -> list[str]:
        sdk = self._load_sdk()
        client = await self._client_for(workspace, sdk)
        list_models = client.models.list
        try:
            listed = list_models(api_key=api_key)
        except TypeError:
            listed = list_models()
        if inspect.isawaitable(listed):
            listed = await listed
        return extract_model_ids(listed)

    async def aclose(self) -> None:
        async with self._lock:
            await self._close_locked()

    def _load_sdk(self) -> Any:
        return self._sdk_loader()

    async def _client_for(self, workspace: str, sdk: Any) -> Any:
        if self._injected is not None:
            return self._injected
        async with self._lock:
            if self._client is not None and self._workspace == workspace:
                return self._client
            await self._close_locked()
            bridge = sdk.AsyncClient.launch_bridge(workspace=workspace)
            if inspect.isawaitable(bridge):
                bridge = await bridge
            if hasattr(bridge, "__aenter__"):
                client = await bridge.__aenter__()
                self._bridge = bridge
            else:
                client = bridge
                self._bridge = None
            self._client = client
            self._workspace = workspace
            return client

    async def _close_locked(self) -> None:
        bridge = self._bridge
        client = self._client
        self._bridge = None
        self._client = None
        self._workspace = ""
        if bridge is not None and hasattr(bridge, "__aexit__"):
            await bridge.__aexit__(None, None, None)
            return
        if client is None:
            return
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


class SdkCursorTurn:
    def __init__(self, agent: Any, agent_cm: Any, run: Any, secret: str = "") -> None:
        self._agent = agent
        self._agent_cm = agent_cm
        self._run = run
        self._secret = secret
        self._parts: list[str] = []
        self._outcome: CursorOutcome | None = None
        self._finished = False
        self._closed = False

    async def iter_text(self):
        iterator = self._run.iter_text()
        if inspect.isawaitable(iterator):
            iterator = await iterator
        if hasattr(iterator, "__aiter__"):
            async for chunk in iterator:
                text = "" if chunk is None else str(chunk)
                self._parts.append(text)
                yield text
            return
        for chunk in iterator:
            text = "" if chunk is None else str(chunk)
            self._parts.append(text)
            yield text

    async def finish(self) -> CursorOutcome:
        if self._outcome is not None:
            return self._outcome
        try:
            result = self._run.wait()
            if inspect.isawaitable(result):
                result = await result
            status = str(
                getattr(result, "status", None) or getattr(self._run, "status", "") or ""
            )
            text = getattr(result, "result", None)
            if not isinstance(text, str):
                text = "".join(self._parts)
            run_id = str(
                getattr(self._run, "id", None) or getattr(result, "id", "") or ""
            )
            agent_id = str(
                getattr(self._agent, "agent_id", None)
                or getattr(self._run, "agent_id", "")
                or ""
            )
            self._finished = True
            logger.info(
                "Cursor run finished status=%s run_id=%s agent_id=%s",
                status,
                run_id,
                agent_id,
            )
            if status != "finished":
                detail = getattr(result, "error_message", None)
                extra = ""
                if isinstance(detail, str) and detail.strip():
                    extra = " " + redact(detail.strip(), self._secret)[:300]
                raise CursorRunFailedError(
                    "Cursor 运行没有完成，状态是 "
                    f"{status or 'unknown'}。run_id={run_id} agent_id={agent_id}{extra}",
                    run_id=run_id,
                    agent_id=agent_id,
                )
            model = getattr(result, "model", None)
            model_id = getattr(model, "id", "") if model is not None else ""
            self._outcome = CursorOutcome(
                text=text,
                status=status,
                run_id=run_id,
                agent_id=agent_id,
                usage=map_usage(
                    getattr(result, "usage", None) or getattr(self._run, "usage", None)
                ),
                model=str(model_id or ""),
            )
            return self._outcome
        finally:
            await self.aclose()

    async def cancel(self) -> None:
        supports = getattr(self._run, "supports", None)
        if callable(supports) and not supports("cancel"):
            return
        cancel = getattr(self._run, "cancel", None)
        if cancel is None:
            return
        result = cancel()
        if inspect.isawaitable(result):
            await result

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._finished:
            try:
                await self.cancel()
            except Exception:
                logger.debug("Cursor run cancel failed", exc_info=True)
        await _close_agent(self._agent, self._agent_cm)


def import_sdk() -> Any:
    try:
        import cursor_sdk
    except ImportError as exc:
        raise CursorPluginError(
            "还没有安装 cursor-sdk。重载插件后，AstrBot 会按 requirements.txt 安装它。"
        ) from exc
    return cursor_sdk


def extract_model_ids(listed: Any) -> list[str]:
    items = getattr(listed, "items", listed)
    if items is None:
        return []
    ids: list[str] = []
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
        if model_id:
            ids.append(str(model_id))
    return ids


def retry_delay_seconds(exc: BaseException, attempt: int) -> float:
    raw = getattr(exc, "retry_after", None)
    if raw not in (None, ""):
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            parsed = _http_date_delay(str(raw))
            if parsed is not None:
                return parsed
    return float(min(8, 2**attempt))


def _http_date_delay(value: str) -> float | None:
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, when.timestamp() - time.time())


def _create_options(sdk: Any, request: CursorRequest, idempotency_key: str) -> Any:
    # `agents.create()` only accepts tool restrictions inside AgentOptions.
    # tools=[] is text-only; omitting tools keeps Cursor's default toolset.
    fields: dict[str, Any] = {
        "model": request.model,
        "api_key": request.api_key,
        "name": _agent_name(request.conversation_id),
    }
    if request.runtime_mode == "cloud":
        repos = []
        if request.repo_url:
            repo_kwargs = {"url": request.repo_url}
            if request.starting_ref:
                repo_kwargs["starting_ref"] = request.starting_ref
            repos.append(sdk.CloudRepository(**repo_kwargs))
        fields["cloud"] = sdk.CloudAgentOptions(
            repos=repos,
            auto_create_pr=bool(request.auto_create_pr and request.repo_url),
            skip_reviewer_request=True,
        )
        fields["idempotency_key"] = idempotency_key
        return sdk.AgentOptions(**fields)

    fields["local"] = sdk.LocalAgentOptions(cwd=request.workspace)
    if request.builtin_tool_mode == "none":
        fields["tools"] = []
    elif request.builtin_tool_mode == "allowlist":
        fields["tools"] = list(request.builtin_tools)
    return sdk.AgentOptions(**fields)


def _user_message(sdk: Any, request: CursorRequest) -> Any:
    if not request.images:
        return request.prompt
    return sdk.UserMessage(text=request.prompt, images=_sdk_images(sdk, request.images))


def _sdk_images(sdk: Any, images: tuple[ImageInput, ...]) -> list[Any]:
    converted = []
    for image in images:
        if image.source == "url":
            converted.append(sdk.SDKImage.from_url(image.value))
        elif image.source == "data":
            converted.append(
                sdk.SDKImage.from_data(
                    image.value,
                    image.mime_type or "application/octet-stream",
                )
            )
        else:
            converted.append(sdk.SDKImage.from_file(image.value))
    return converted


def _agent_name(conversation_id: str) -> str:
    label = " ".join(str(conversation_id or "").split())[:60]
    if not label:
        return "AstrBot"
    return f"AstrBot {label}"


async def _open_agent(client: Any, options: Any) -> tuple[Any, Any]:
    created = client.agents.create(options)
    if inspect.isawaitable(created):
        created = await created
    if hasattr(created, "__aenter__"):
        agent = await created.__aenter__()
        return agent, created
    return created, None


async def _close_agent(agent: Any, agent_cm: Any) -> None:
    if agent_cm is not None and hasattr(agent_cm, "__aexit__"):
        await agent_cm.__aexit__(None, None, None)
        return
    if agent is None:
        return
    close = getattr(agent, "aclose", None) or getattr(agent, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import CursorPluginError, MissingApiKeyError

PROVIDER_TYPE = "cursor_sdk"
PROVIDER_TEMPLATE_NAME = "Cursor 插件"
KEY_PLACEHOLDER = "cursor-plugin"
PLUGIN_NAME = "astrbot_plugin_cursor"
DEFAULT_MODELS = ("composer-2.5", "auto")
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class CursorSettings:
    enabled: bool
    api_key: str
    allow_env_key: bool
    runtime_mode: str
    models: tuple[str, ...]
    workspace: str
    builtin_tool_mode: str
    builtin_tools: tuple[str, ...]
    timeout_seconds: int
    max_attempts: int
    repo_url: str
    starting_ref: str
    auto_create_pr: bool


def parse_model_list(text: str) -> tuple[str, ...]:
    models: list[str] = []
    for line in str(text or "").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            models.append(item)
    return tuple(models or DEFAULT_MODELS)


def parse_builtin_tools(text: str) -> tuple[str, tuple[str, ...]]:
    value = str(text or "").strip()
    if not value:
        return "none", ()
    if value.lower() == "default":
        return "default", ()
    names = [
        item.strip()
        for item in value.replace("\n", ",").split(",")
        if item.strip()
    ]
    invalid = [name for name in names if _TOOL_NAME.fullmatch(name) is None]
    if invalid:
        raise CursorPluginError(
            "本地内置工具名称无效：" + ", ".join(invalid)
        )
    if not names:
        return "none", ()
    return "allowlist", tuple(names)


def parse_settings(config: dict | None) -> CursorSettings:
    data = config or {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    cloud = data.get("cloud") if isinstance(data.get("cloud"), dict) else {}
    mode = str(runtime.get("runtime_mode") or "local").strip().lower()
    if mode not in {"local", "cloud"}:
        raise CursorPluginError("运行位置只能是 local 或 cloud")
    tool_mode, tool_names = parse_builtin_tools(str(runtime.get("builtin_tools") or ""))
    return CursorSettings(
        enabled=runtime.get("enabled", True) is not False,
        api_key=str(runtime.get("api_key") or "").strip(),
        allow_env_key=runtime.get("allow_env_key", False) is True,
        runtime_mode=mode,
        models=parse_model_list(str(runtime.get("models") or "")),
        workspace=str(runtime.get("workspace") or "").strip(),
        builtin_tool_mode=tool_mode,
        builtin_tools=tool_names,
        timeout_seconds=max(1, _as_int(runtime.get("timeout_seconds"), 180)),
        max_attempts=max(1, _as_int(runtime.get("max_attempts"), 2)),
        repo_url=str(cloud.get("repo_url") or "").strip(),
        starting_ref=str(cloud.get("starting_ref") or "").strip(),
        auto_create_pr=cloud.get("auto_create_pr", False) is True,
    )


def choose_model(
    requested: str | None,
    provider_model: str | None,
    configured: tuple[str, ...],
) -> str:
    for candidate in (requested, provider_model):
        text = str(candidate or "").strip()
        if text:
            return text
    return configured[0]


def resolve_api_key(settings: CursorSettings, provider_config: dict | None) -> str:
    if settings.api_key:
        return settings.api_key
    for key in (provider_config or {}).get("key") or []:
        text = str(key or "").strip()
        if text and text != KEY_PLACEHOLDER:
            return text
    if settings.allow_env_key:
        env_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if env_key:
            return env_key
    raise MissingApiKeyError(
        "还没有 Cursor API Key。请填写插件配置里的 API Key，"
        "使用 Dashboard 中的用户密钥或服务账号密钥。"
    )


def resolve_timeout(provider_config: dict | None, settings: CursorSettings) -> float:
    raw = (provider_config or {}).get("timeout")
    if raw not in (None, "", 0, "0"):
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass
    return float(settings.timeout_seconds)


def astrbot_root() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_root

        return Path(get_astrbot_root())
    except Exception:
        env = os.environ.get("ASTRBOT_ROOT", "").strip()
        if env:
            return Path(env)
        return Path.cwd()


def default_workspace(root: Path) -> Path:
    path = root / "data" / "plugin_data" / PLUGIN_NAME / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_workspace(configured: str, root: Path) -> Path:
    if not configured.strip():
        workspace = default_workspace(root)
    else:
        workspace = Path(configured.strip())
        if not workspace.is_absolute():
            workspace = root / workspace
    reason = workspace_block_reason(workspace, root)
    if reason:
        raise CursorPluginError(reason)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def workspace_block_reason(workspace: Path, astrbot_root_path: Path) -> str | None:
    """Reject workspaces that can see AstrBot secrets or private data."""
    candidate = workspace.resolve()
    root = astrbot_root_path.resolve()
    data = (root / "data").resolve()
    allowed = (data / "plugin_data" / PLUGIN_NAME).resolve()
    if _contains(allowed, candidate):
        return None
    protected = (
        root,
        data,
        (data / "config").resolve(),
        (data / "plugins").resolve(),
        (root / "tools").resolve(),
        (root / "bin").resolve(),
    )
    if any(_contains(candidate, item) or candidate == item for item in protected):
        return (
            "这个工作目录能碰到 AstrBot 的程序、配置或数据。"
            "请改到插件空目录以外的独立项目目录，或留空使用插件自带的空目录。"
        )
    if _contains(data, candidate):
        return (
            "工作目录不能放在 AstrBot 的 data 目录里，那里有令牌、聊天和记忆数据。"
        )
    return None


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

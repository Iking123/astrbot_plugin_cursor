from __future__ import annotations


class CursorPluginError(Exception):
    """User-facing plugin error."""


class MissingApiKeyError(CursorPluginError):
    """Raised when no Cursor API key is configured."""


class UnsupportedAudioError(CursorPluginError):
    """Raised when a turn contains audio and no text or image."""


class CursorRunFailedError(CursorPluginError):
    """Raised when a Cursor run starts and then finishes unsuccessfully."""

    def __init__(self, message: str, *, run_id: str = "", agent_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id
        self.agent_id = agent_id


def exception_text(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        text = message.strip()
    else:
        text = str(exc).strip() or exc.__class__.__name__
    request_id = getattr(exc, "request_id", None)
    if request_id and str(request_id) not in text:
        text = f"{text}（request_id={request_id}）"
    return text


def redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text

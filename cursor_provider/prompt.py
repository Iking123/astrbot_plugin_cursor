from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

ImageSource = Literal["url", "file", "data"]
_WINDOWS_FILE_PATH = re.compile(r"^/[A-Za-z]:")
_ROLE_LABELS = {
    "system": "System",
    "user": "User",
    "assistant": "Assistant",
    "tool": "Tool",
}


@dataclass(frozen=True)
class ImageInput:
    source: ImageSource
    value: str
    mime_type: str = ""


@dataclass(frozen=True)
class PreparedTurn:
    text: str
    images: tuple[ImageInput, ...]
    has_audio: bool


@dataclass
class _Piece:
    role: str
    text: str
    images: list[ImageInput]
    audio: bool


def prepare_turn(
    *,
    prompt: str | None = None,
    contexts: list | None = None,
    system_prompt: str | None = None,
    tool_calls_result: Any = None,
    image_urls: list[str] | None = None,
    audio_urls: list[str] | None = None,
    extra_user_content_parts: list | None = None,
) -> PreparedTurn:
    system_parts: list[str] = []
    if system_prompt and str(system_prompt).strip():
        system_parts.append(str(system_prompt).strip())

    pieces: list[_Piece] = []
    for message in _iter_messages(contexts, tool_calls_result):
        role = str(_get(message, "role") or "user")
        if role in {"_checkpoint", "checkpoint"}:
            continue
        text, images, audio = _split_content(_get(message, "content"))
        text = _with_tool_calls(text, _get(message, "tool_calls"))
        if role == "system":
            if text.strip():
                system_parts.append(text.strip())
            continue
        if text.strip() or images or audio:
            pieces.append(_Piece(role, text.strip(), images, audio))

    _merge_user_turn(
        pieces,
        prompt=prompt,
        image_urls=image_urls,
        audio_urls=audio_urls,
        extra_user_content_parts=extra_user_content_parts,
    )
    return _render(system_parts, pieces)


def classify_image(ref: str) -> ImageInput | None:
    value = str(ref or "").strip()
    if not value:
        return None
    if value.startswith("data:"):
        header, separator, data = value.partition(",")
        if separator != ",":
            return None
        mime = header[5:].split(";", 1)[0].strip() or "application/octet-stream"
        return ImageInput("data", data, mime)
    if value.startswith(("http://", "https://")):
        return ImageInput("url", value)
    if value.startswith("file://"):
        return ImageInput("file", _file_uri_to_path(value))
    return ImageInput("file", str(Path(value)))


def _iter_messages(contexts: list | None, tool_calls_result: Any) -> list[Any]:
    messages = list(contexts or [])
    if tool_calls_result is None:
        return messages
    items = (
        tool_calls_result
        if isinstance(tool_calls_result, list)
        else [tool_calls_result]
    )
    for item in items:
        if item is None:
            continue
        converter = getattr(item, "to_openai_messages", None)
        if callable(converter):
            messages.extend(converter())
        else:
            messages.append(item)
    return messages


def _merge_user_turn(
    pieces: list[_Piece],
    *,
    prompt: str | None,
    image_urls: list[str] | None,
    audio_urls: list[str] | None,
    extra_user_content_parts: list | None,
) -> None:
    content: list[Any] = []
    if prompt:
        content.append({"type": "text", "text": str(prompt)})
    content.extend(extra_user_content_parts or [])
    text, images, audio = _split_content(content)
    for ref in image_urls or []:
        image = classify_image(ref)
        if image is not None:
            images.append(image)
    audio = audio or bool(audio_urls)
    incoming = _Piece("user", text.strip(), images, audio)
    if (
        pieces
        and pieces[-1].role == "user"
        and pieces[-1].text.strip() == incoming.text.strip()
    ):
        pieces[-1].images.extend(incoming.images)
        pieces[-1].audio = pieces[-1].audio or incoming.audio
        return
    if incoming.text.strip() or incoming.images or incoming.audio:
        pieces.append(incoming)


def _render(system_parts: list[str], pieces: list[_Piece]) -> PreparedTurn:
    images: list[ImageInput] = []
    conversation: list[str] = []
    has_audio = False
    image_index = 1
    for piece in pieces:
        has_audio = has_audio or piece.audio
        markers: list[str] = []
        for image in piece.images:
            images.append(image)
            markers.append(f"[Image {image_index}]")
            image_index += 1
        body = piece.text.strip()
        if markers:
            marker_line = " ".join(markers)
            body = f"{body}\n{marker_line}".strip() if body else marker_line
        if not body:
            continue
        label = _ROLE_LABELS.get(piece.role, piece.role)
        conversation.append(f"{label}: {body}")

    sections: list[str] = []
    if system_parts:
        sections.append("System instructions:\n" + "\n\n".join(system_parts))
    if conversation:
        sections.append("Conversation:\n" + "\n".join(conversation))
    if has_audio and sections:
        sections.append(
            "Note: audio was attached and was not forwarded. "
            "Cursor agents cannot hear audio."
        )
    return PreparedTurn(
        "\n\n".join(sections).strip(),
        tuple(images),
        has_audio,
    )


def _split_content(content: Any) -> tuple[str, list[ImageInput], bool]:
    if content is None:
        return "", [], False
    if isinstance(content, str):
        return content, [], False
    if isinstance(content, list):
        texts: list[str] = []
        images: list[ImageInput] = []
        audio = False
        for part in content:
            part_type = str(_get(part, "type") or "")
            if part_type in {"", "text"} and not isinstance(part, (dict, list)):
                texts.append(str(part))
                continue
            if part_type == "text":
                texts.append(str(_get(part, "text") or ""))
            elif part_type == "image_url":
                image = classify_image(_image_ref(part))
                if image is not None:
                    images.append(image)
            elif part_type == "audio_url":
                audio = True
        return "\n".join(item for item in texts if item), images, audio
    return str(content), [], False


def _with_tool_calls(text: str, tool_calls: Any) -> str:
    if not isinstance(tool_calls, list):
        return text
    names: list[str] = []
    for call in tool_calls:
        function = _get(call, "function")
        name = _get(function, "name") if function is not None else _get(call, "name")
        if name:
            names.append(str(name))
    if not names:
        return text
    suffix = " ".join(f"[tool call {name}]" for name in names)
    return f"{text}\n{suffix}".strip() if text else suffix


def _image_ref(part: Any) -> str:
    image_url = _get(part, "image_url")
    if isinstance(image_url, str):
        return image_url
    if image_url is not None:
        url = _get(image_url, "url")
        if isinstance(url, str):
            return url
    return ""


def _file_uri_to_path(uri: str) -> str:
    path = unquote(urlparse(uri).path)
    if _WINDOWS_FILE_PATH.match(path):
        path = path[1:]
    return path


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

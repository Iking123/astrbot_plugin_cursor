from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageNumbers:
    input_other: int
    input_cached: int
    output: int


def map_usage(usage: Any) -> UsageNumbers | None:
    """Map Cursor TokenUsage onto AstrBot's input/cache/output fields.

    Cursor includes cache reads in ``input_tokens``. Those reads are reported
    separately as cached input, and the remainder stays in the uncached input.
    """
    if usage is None:
        return None
    input_tokens = _field(usage, "input_tokens")
    cache_read = _field(usage, "cache_read_tokens")
    return UsageNumbers(
        input_other=max(0, input_tokens - cache_read),
        input_cached=cache_read,
        output=_field(usage, "output_tokens"),
    )


def _field(usage: Any, name: str) -> int:
    if isinstance(usage, dict):
        value = usage.get(name)
    else:
        value = getattr(usage, name, None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

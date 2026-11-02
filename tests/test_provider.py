from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from astrbot.core.provider.entities import TokenUsage

from cursor_provider.errors import CursorPluginError, UnsupportedAudioError
from cursor_provider.provider import ProviderCursor
from cursor_provider.runtime import CursorOutcome
from cursor_provider.service import CursorPluginService, set_service
from cursor_provider.usage import UsageNumbers


class FakeTurn:
    def __init__(self, chunks: list[str], outcome: CursorOutcome) -> None:
        self.chunks = chunks
        self.outcome = outcome
        self.closed = False

    async def iter_text(self):
        for chunk in self.chunks:
            yield chunk

    async def finish(self) -> CursorOutcome:
        return self.outcome

    async def aclose(self) -> None:
        self.closed = True


class FakeRuntime:
    def __init__(self, turn: FakeTurn | None = None, error: Exception | None = None) -> None:
        self.turn = turn
        self.error = error
        self.requests = []

    async def start(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.turn

    async def list_models(self, api_key: str, workspace: str) -> list[str]:
        del api_key, workspace
        return ["composer-2.5", "auto"]

    async def aclose(self) -> None:
        return None


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.turn = FakeTurn(
            ["你", "好"],
            CursorOutcome(
                text="你好",
                status="finished",
                run_id="run-9",
                agent_id="agent-9",
                usage=UsageNumbers(input_other=1, input_cached=2, output=3),
            ),
        )
        self.runtime = FakeRuntime(self.turn)
        self.service = CursorPluginService(
            {"runtime": {"api_key": "crsr_secret", "models": "composer-2.5\nauto"}},
            runtime=self.runtime,
            root=__import__("pathlib").Path(self.tmp.name),
        )
        set_service(self.service)

    def tearDown(self) -> None:
        set_service(None)
        self.tmp.cleanup()

    def provider(self) -> ProviderCursor:
        return ProviderCursor(
            {"id": "cursor", "type": "cursor_sdk", "model": "composer-2.5", "key": ["cursor-plugin"]},
            {},
        )

    async def test_stream_yields_deltas_then_the_full_reply(self) -> None:
        responses = [item async for item in self.provider().text_chat_stream(prompt="hi")]

        self.assertEqual([item.completion_text for item in responses], ["你", "好", "你好"])
        self.assertTrue(responses[0].is_chunk)
        self.assertFalse(responses[-1].is_chunk)
        self.assertEqual(responses[-1].id, "run-9")
        self.assertIsInstance(responses[-1].usage, TokenUsage)
        self.assertEqual(responses[-1].usage.output, 3)
        self.assertTrue(self.turn.closed)
        self.assertEqual(self.runtime.requests[0].prompt.count("User: hi"), 1)
        self.assertEqual(self.runtime.requests[0].builtin_tool_mode, "none")

    async def test_redacts_unexpected_errors(self) -> None:
        self.runtime.error = RuntimeError("upstream said crsr_secret")
        with self.assertRaises(CursorPluginError) as caught:
            await self.provider().text_chat(prompt="hi")

        self.assertNotIn("crsr_secret", str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))

    async def test_rejects_audio_without_calling_cursor(self) -> None:
        with self.assertRaises(UnsupportedAudioError):
            await self.provider().text_chat(audio_urls=["voice.wav"])
        self.assertEqual(self.runtime.requests, [])

    async def test_reports_a_missing_plugin(self) -> None:
        set_service(None)
        with self.assertRaises(CursorPluginError):
            await self.provider().get_models()


if __name__ == "__main__":
    unittest.main()

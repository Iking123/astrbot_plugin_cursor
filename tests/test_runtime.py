from __future__ import annotations

import unittest
from types import SimpleNamespace

from cursor_provider.errors import CursorPluginError, CursorRunFailedError
from cursor_provider.prompt import ImageInput
from cursor_provider.runtime import (
    CursorRequest,
    CursorRuntime,
    extract_model_ids,
    retry_delay_seconds,
)
from cursor_provider.usage import map_usage


class CursorAgentError(Exception):
    def __init__(
        self,
        message: str,
        *,
        is_retryable: bool = False,
        retry_after: object = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable
        self.retry_after = retry_after
        self.request_id = request_id


class LocalAgentOptions:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd


class CloudAgentOptions:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class CloudRepository:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class UserMessage:
    def __init__(self, text: str, images: list) -> None:
        self.text = text
        self.images = images


class AgentOptions:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class SDKImage:
    @classmethod
    def from_url(cls, url: str) -> str:
        return f"url:{url}"

    @classmethod
    def from_file(cls, path: str) -> str:
        return f"file:{path}"

    @classmethod
    def from_data(cls, data: str, mime_type: str) -> str:
        return f"data:{mime_type}:{data}"


class FakeSDK:
    CursorAgentError = CursorAgentError
    LocalAgentOptions = LocalAgentOptions
    CloudAgentOptions = CloudAgentOptions
    CloudRepository = CloudRepository
    UserMessage = UserMessage
    SDKImage = SDKImage
    AgentOptions = AgentOptions


class AgentCM:
    def __init__(self, agent: "FakeAgent") -> None:
        self.agent = agent

    async def __aenter__(self) -> "FakeAgent":
        return self.agent

    async def __aexit__(self, *args: object) -> None:
        self.agent.closed = True


class FakeRun:
    def __init__(
        self,
        chunks: list[str],
        status: str = "finished",
        usage: object | None = None,
    ) -> None:
        self.chunks = chunks
        self.status = "running"
        self._status = status
        self.usage = usage
        self.id = "run-1"
        self.agent_id = "agent-1"
        self.cancelled = False

    def supports(self, operation: str) -> bool:
        return operation == "cancel"

    async def cancel(self) -> None:
        self.cancelled = True

    async def iter_text(self):
        for chunk in self.chunks:
            yield chunk

    async def wait(self) -> SimpleNamespace:
        self.status = self._status
        return SimpleNamespace(
            status=self._status,
            result="".join(self.chunks),
            usage=self.usage,
            id=self.id,
            model=SimpleNamespace(id="composer-2.5"),
        )


class FakeAgent:
    def __init__(self, run: FakeRun | None = None) -> None:
        self.run = run or FakeRun(["pong"])
        self.agent_id = "agent-1"
        self.closed = False
        self.sent = None

    async def send(self, message: object) -> FakeRun:
        self.sent = message
        return self.run


class FakeAgents:
    def __init__(self, failures: int = 0, run: FakeRun | None = None) -> None:
        self.failures = failures
        self.run = run
        self.created: list[AgentOptions] = []
        self.opened: list[FakeAgent] = []

    async def create(self, options: AgentOptions | None = None, **kwargs: object) -> AgentCM:
        del kwargs
        assert options is not None
        self.created.append(options)
        if len(self.created) <= self.failures:
            raise CursorAgentError(
                "rate limit for crsr_test_secret",
                is_retryable=True,
                retry_after="0",
                request_id="req-1",
            )
        agent = FakeAgent(self.run)
        self.opened.append(agent)
        return AgentCM(agent)


class FakeModels:
    def __init__(self) -> None:
        self.api_key = ""

    async def list(self, api_key: str = "") -> list[SimpleNamespace]:
        self.api_key = api_key
        return [SimpleNamespace(id="composer-2.5"), SimpleNamespace(id="auto")]


class FakeClient:
    def __init__(self, agents: FakeAgents) -> None:
        self.agents = agents
        self.models = FakeModels()


def request(**overrides: object) -> CursorRequest:
    data: dict = {
        "api_key": "crsr_test_secret",
        "model": "composer-2.5",
        "runtime_mode": "local",
        "workspace": "E:/sandbox",
        "bridge_workspace": "E:/sandbox",
        "prompt": "hello",
        "images": (),
        "builtin_tool_mode": "none",
        "builtin_tools": (),
        "repo_url": "",
        "starting_ref": "",
        "auto_create_pr": False,
        "timeout_seconds": 5,
        "max_attempts": 2,
        "conversation_id": "qq:1",
    }
    data.update(overrides)
    return CursorRequest(**data)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_chat_sends_text_only_and_closes_the_agent(self) -> None:
        agents = FakeAgents(
            run=FakeRun(
                ["you", " win"],
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=4,
                    cache_read_tokens=3,
                ),
            )
        )
        runtime = CursorRuntime(client=FakeClient(agents), sdk_loader=lambda: FakeSDK)
        turn = await runtime.start(request())
        chunks = [chunk async for chunk in turn.iter_text()]
        outcome = await turn.finish()

        self.assertEqual(chunks, ["you", " win"])
        self.assertEqual(outcome.text, "you win")
        self.assertEqual(outcome.usage.input_other, 7)  # type: ignore[union-attr]
        self.assertEqual(outcome.usage.input_cached, 3)  # type: ignore[union-attr]
        created = agents.created[0]
        self.assertEqual(created.tools, [])
        self.assertEqual(created.local.cwd, "E:/sandbox")
        self.assertEqual(created.name, "AstrBot qq:1")
        self.assertFalse(hasattr(created, "cloud"))
        self.assertTrue(agents.opened[0].closed)
        self.assertEqual(agents.opened[0].sent, "hello")

    async def test_retries_a_retryable_startup_error_once(self) -> None:
        agents = FakeAgents(failures=1)
        runtime = CursorRuntime(client=FakeClient(agents), sdk_loader=lambda: FakeSDK)
        turn = await runtime.start(request())
        await turn.aclose()

        self.assertEqual(len(agents.created), 2)
        self.assertEqual(agents.created[1].model, "composer-2.5")

    async def test_redacts_the_key_when_startup_cannot_retry(self) -> None:
        agents = FakeAgents(failures=1)
        runtime = CursorRuntime(client=FakeClient(agents), sdk_loader=lambda: FakeSDK)
        with self.assertRaises(CursorPluginError) as caught:
            await runtime.start(request(max_attempts=1))

        message = str(caught.exception)
        self.assertNotIn("crsr_test_secret", message)
        self.assertIn("[redacted]", message)
        self.assertIn("req-1", message)

    async def test_run_error_is_not_retried(self) -> None:
        agents = FakeAgents(run=FakeRun(["x"], status="error"))
        runtime = CursorRuntime(client=FakeClient(agents), sdk_loader=lambda: FakeSDK)
        turn = await runtime.start(request())
        with self.assertRaises(CursorRunFailedError):
            async for _chunk in turn.iter_text():
                pass
            await turn.finish()

        self.assertEqual(len(agents.created), 1)

    async def test_cloud_options_do_not_enable_local_file_tools(self) -> None:
        agents = FakeAgents()
        runtime = CursorRuntime(client=FakeClient(agents), sdk_loader=lambda: FakeSDK)
        turn = await runtime.start(
            request(
                runtime_mode="cloud",
                repo_url="https://github.com/example/repo",
                starting_ref="main",
                auto_create_pr=True,
                builtin_tool_mode="none",
                images=(ImageInput("url", "https://example.com/a.png"),),
            )
        )
        await turn.aclose()

        created = agents.created[0]
        self.assertFalse(hasattr(created, "tools"))
        self.assertFalse(hasattr(created, "local"))
        self.assertTrue(created.cloud.kwargs["skip_reviewer_request"])
        self.assertTrue(created.cloud.kwargs["auto_create_pr"])
        self.assertTrue(created.idempotency_key)
        self.assertEqual(
            created.cloud.kwargs["repos"][0].kwargs["url"],
            "https://github.com/example/repo",
        )
        self.assertIsInstance(agents, FakeAgents)

    def test_usage_and_model_catalog_helpers(self) -> None:
        mapped = map_usage(
            {"input_tokens": 5, "cache_read_tokens": 8, "output_tokens": 2}
        )
        self.assertIsNotNone(mapped)
        assert mapped is not None
        self.assertEqual(mapped.input_other, 0)
        self.assertEqual(mapped.input_cached, 8)
        self.assertEqual(
            extract_model_ids([{"id": "composer-2.5"}, SimpleNamespace(id="auto")]),
            ["composer-2.5", "auto"],
        )
        self.assertEqual(retry_delay_seconds(SimpleNamespace(retry_after="1.5"), 0), 1.5)


if __name__ == "__main__":
    unittest.main()

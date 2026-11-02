from __future__ import annotations

import unittest

from cursor_provider.prompt import classify_image, prepare_turn


class PromptTests(unittest.TestCase):
    def test_renders_system_history_and_new_message(self) -> None:
        prepared = prepare_turn(
            system_prompt="Be brief",
            contexts=[
                {"role": "system", "content": "Use Chinese"},
                {"role": "_checkpoint", "content": "skip-me"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hey"},
            ],
            prompt="next",
        )

        self.assertTrue(prepared.text.startswith("System instructions:"))
        self.assertIn("Be brief", prepared.text)
        self.assertIn("Use Chinese", prepared.text)
        self.assertNotIn("skip-me", prepared.text)
        self.assertLess(prepared.text.index("User: hi"), prepared.text.index("User: next"))
        self.assertIn("Assistant: hey", prepared.text)

    def test_does_not_duplicate_the_same_user_text_when_adding_an_image(self) -> None:
        prepared = prepare_turn(
            contexts=[{"role": "user", "content": "hi"}],
            prompt="hi",
            image_urls=["https://example.com/a.png"],
        )

        self.assertEqual(prepared.text.count("User:"), 1)
        self.assertIn("[Image 1]", prepared.text)
        self.assertEqual(prepared.images[0].source, "url")

    def test_includes_tool_results(self) -> None:
        class Result:
            def to_openai_messages(self):
                return [{"role": "tool", "content": "42"}]

        prepared = prepare_turn(tool_calls_result=Result(), prompt="thanks")

        self.assertIn("Tool: 42", prepared.text)
        self.assertIn("User: thanks", prepared.text)

    def test_audio_only_stays_empty_so_the_provider_can_reject_it(self) -> None:
        prepared = prepare_turn(audio_urls=["C:/voice.wav"])

        self.assertTrue(prepared.has_audio)
        self.assertEqual(prepared.text, "")

    def test_audio_with_text_adds_a_note(self) -> None:
        prepared = prepare_turn(prompt="hello", audio_urls=["voice.wav"])

        self.assertIn("hello", prepared.text)
        self.assertIn("cannot hear audio", prepared.text)

    def test_classifies_data_and_file_images(self) -> None:
        data = classify_image("data:image/png;base64,aaaa")
        file_image = classify_image("file:///E:/pics/a.png")

        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data.source, "data")
        self.assertEqual(data.mime_type, "image/png")
        self.assertEqual(data.value, "aaaa")
        self.assertIsNotNone(file_image)
        assert file_image is not None
        self.assertEqual(file_image.source, "file")
        self.assertTrue(file_image.value.replace("\\", "/").endswith("E:/pics/a.png"))


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import services.chat_service as chat_module


def text_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))],
        usage=None,
    )


def empty_chunk():
    return SimpleNamespace(choices=[], usage=None)


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class ChatServiceTests(unittest.TestCase):
    def test_streams_text_and_persists_history(self):
        fake_client = FakeClient([[text_chunk("你好"), text_chunk("，读者")]])
        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("one", "请介绍一下"))

        self.assertEqual([event.event for event in events], ["message_start", "token", "token", "done"])
        self.assertEqual([event.data["content"] for event in events if event.event == "token"], ["你好", "，读者"])
        messages = service.get_messages("one")
        self.assertEqual(messages[-2]["role"], "user")
        self.assertEqual(messages[-1], {"role": "assistant", "content": "你好，读者"})

    def test_provider_error_does_not_emit_done_or_incomplete_assistant(self):
        def broken_response():
            yield text_chunk("部分内容")
            raise RuntimeError("connection lost")

        fake_client = FakeClient([broken_response()])
        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("broken", "继续"))

        self.assertEqual(events[-1].event, "error")
        self.assertNotIn("done", [event.event for event in events])
        self.assertEqual(service.get_messages("broken")[-1]["role"], "user")

    def test_tool_result_is_added_before_follow_up_request(self):
        tool_delta = SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                index=0,
                id="call-1",
                function=SimpleNamespace(name="get_chapter_list", arguments="{}"),
            )],
        )
        first_response = [SimpleNamespace(choices=[SimpleNamespace(delta=tool_delta)], usage=None), empty_chunk()]
        fake_client = FakeClient([first_response, [text_chunk("完成")]])
        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("tool", "列出章节"))

        self.assertIn("tool_start", [event.event for event in events])
        self.assertIn("tool_result", [event.event for event in events])
        self.assertEqual(events[-1].event, "done")
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertEqual(fake_client.chat.completions.calls[1]["messages"][-1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()

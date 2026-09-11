import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import services.chat_service as chat_module


def text_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content, tool_calls=None),
        )],
        usage=None,
    )


def empty_chunk():
    return SimpleNamespace(choices=[], usage=None)


def tool_chunk(call_id, name, arguments):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    index=0,
                    id=call_id,
                    function=SimpleNamespace(
                        name=name,
                        arguments=arguments,
                    ),
                )],
            ),
        )],
        usage=None,
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(responses),
        )


class BlockingResponse:
    def __init__(self, started):
        self.started = started

    def __iter__(self):
        self.started.set()
        while True:
            yield text_chunk("继续")
            time.sleep(0.005)


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.storage_patcher = patch.object(
            chat_module,
            "MESSAGE_STORAGE_FILE",
            Path(self.temp_dir.name) / "test.db",
        )
        self.storage_patcher.start()
        self.addCleanup(self.storage_patcher.stop)

    @staticmethod
    def print_success(message):
        print(f"[OK] {message}", flush=True)

    def test_normal_response_streams_tokens_and_persists_messages(self):
        fake_client = FakeClient([
            [text_chunk("你好"), text_chunk("，读者")],
        ])

        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("normal", "请打招呼"))

        self.assertEqual(
            [event.event for event in events],
            ["message_start", "token", "token", "done"],
        )
        self.assertEqual(
            [event.data["content"] for event in events if event.event == "token"],
            ["你好", "，读者"],
        )

        conversation = service._store.load_conversation("normal")
        self.assertIsNotNone(conversation)
        self.assertEqual(conversation.messages[-2].role, "user")
        self.assertEqual(conversation.messages[-2].content, "请打招呼")
        self.assertEqual(conversation.messages[-1].role, "assistant")
        self.assertEqual(conversation.messages[-1].content, "你好，读者")
        self.print_success("普通回答的事件顺序和消息保存正常")

    def test_provider_error_does_not_emit_done(self):
        fake_client = FakeClient([RuntimeError("connection lost")])

        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("provider-error", "继续"))

        self.assertEqual(events[-1].event, "error")
        self.assertEqual(events[-1].data["code"], "provider_error")
        self.assertNotIn("done", [event.event for event in events])
        self.assertEqual(service._store.load_conversation("provider-error").messages[-1].role, "user")
        self.print_success("模型请求失败时会返回 error 且不会发送 done")

    def test_tool_call_can_continue_to_final_answer(self):
        fake_client = FakeClient([
            [tool_chunk("call-1", "get_chapter_list", "{}"), empty_chunk()],
            [text_chunk("这是章节列表")],
        ])

        with patch.object(
            chat_module,
            "AVAILABLE_TOOLS",
            {"get_chapter_list": lambda book_path: "第一章"},
        ), patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("tool", "列出章节"))

        self.assertEqual(
            [event.event for event in events],
            ["message_start", "tool_start", "tool_result", "token", "done"],
        )
        tool_result = next(event for event in events if event.event == "tool_result")
        self.assertFalse(tool_result.data["error"])
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertEqual(
            fake_client.chat.completions.calls[1]["messages"][-1]["role"],
            "tool",
        )
        self.print_success("工具调用完成后可以继续生成最终回答")

    def test_invalid_tool_arguments_return_tool_error_and_continue(self):
        fake_client = FakeClient([
            [tool_chunk("bad-call", "missing_tool", "不是 JSON"), empty_chunk()],
            [text_chunk("我无法执行这个工具")],
        ])

        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()
            events = list(service.stream_message("tool-error", "执行工具"))

        tool_result = next(event for event in events if event.event == "tool_result")
        self.assertTrue(tool_result.data["error"])
        self.assertIn("Tool execution failed", tool_result.data["result"])
        self.assertEqual(events[-1].event, "done")
        self.print_success("工具参数错误会返回 tool error，并允许流程继续")

    def test_busy_conversation_is_rejected(self):
        started = threading.Event()
        fake_client = FakeClient([BlockingResponse(started)])
        first_events = []

        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()

            worker = threading.Thread(
                target=lambda: first_events.extend(
                    service.stream_message("busy", "第一条消息")
                ),
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            second_events = list(service.stream_message("busy", "第二条消息"))
            service.cancel_conversation("busy")
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(second_events), 1)
        self.assertEqual(second_events[0].event, "error")
        self.assertEqual(second_events[0].data["code"], "conversation_busy")
        self.print_success("同一会话正在处理时会拒绝第二次请求")

    def test_cancelled_conversation_emits_error_without_done(self):
        started = threading.Event()
        fake_client = FakeClient([BlockingResponse(started)])
        events = []

        with patch.object(chat_module, "client", fake_client):
            service = chat_module.ChatService()

            worker = threading.Thread(
                target=lambda: events.extend(
                    service.stream_message("cancel", "请生成长回答")
                ),
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            service.cancel_conversation("cancel")
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertIn("error", [event.event for event in events])
        self.assertNotIn("done", [event.event for event in events])
        self.assertEqual(
            next(event for event in events if event.event == "error").data["code"],
            "user_interreption",
        )
        self.print_success("取消会话会返回 error 且不会发送 done")


if __name__ == "__main__":
    unittest.main()

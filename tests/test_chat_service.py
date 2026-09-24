import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config
import services.chat_service as chat_module


TEST_BOOK_ID = "test-book"


def text_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content, tool_calls=None),
        )],
        usage=None,
    )


def empty_chunk():
    return SimpleNamespace(choices=[], usage=None)


def usage_chunk():
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cached_tokens=60,
            prompt_cache_miss_tokens=40,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )


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


def model_connection(client):
    return SimpleNamespace(client=client, model_name="test-model")


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
        books_dir = Path(self.temp_dir.name) / "books"
        book_root = books_dir / TEST_BOOK_ID
        chapter_dir = book_root / "chapters"
        chapter_dir.mkdir(parents=True)
        (book_root / "name.txt").write_text("测试小说\n", encoding="utf-8")
        (book_root / "info.txt").write_text("测试用简介\n", encoding="utf-8")
        (book_root / "chapters.txt").write_text(
            "1，第一章\n2，第二章\n3，第三章",
            encoding="utf-8",
        )
        for chapter_id in range(1, 4):
            (chapter_dir / f"{chapter_id}.txt").write_text(
                f"第 {chapter_id} 章正文",
                encoding="utf-8",
            )
        books_patcher = patch.object(config, "BOOKS_DIR", books_dir)
        books_patcher.start()
        self.addCleanup(books_patcher.stop)
        self.storage_patcher = patch.object(
            chat_module,
            "MESSAGE_STORAGE_FILE",
            Path(self.temp_dir.name) / "test.db",
        )
        self.storage_patcher.start()
        self.addCleanup(self.storage_patcher.stop)
        self.app_settings_patcher = patch.object(
            chat_module,
            "get_app_settings",
            return_value={
                "tool_round_limit": 100,
                "show_usage": True,
                "model_provider": "siliconflow",
            },
        )
        self.app_settings_patcher.start()
        self.addCleanup(self.app_settings_patcher.stop)

    @staticmethod
    def print_success(message):
        print(f"[OK] {message}", flush=True)

    def test_normal_response_streams_tokens_and_persists_messages(self):
        fake_client = FakeClient([
            [text_chunk("你好"), text_chunk("，读者")],
        ])

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "normal", "请打招呼"))

        self.assertEqual(
            [event.event for event in events],
            ["message_start", "token", "token", "done"],
        )
        self.assertEqual(
            [event.data["content"] for event in events if event.event == "token"],
            ["你好", "，读者"],
        )
        self.assertEqual(events[0].data["title"], "请打招呼")
        self.assertEqual(fake_client.chat.completions.calls[0]["model"], "test-model")

        conversation = service._store.load_conversation("normal", TEST_BOOK_ID)
        self.assertIsNotNone(conversation)
        self.assertEqual(conversation.title, "请打招呼")
        self.assertEqual(conversation.messages[-2].role, "user")
        self.assertEqual(conversation.messages[-2].content, "请打招呼")
        self.assertEqual(conversation.messages[-1].role, "assistant")
        self.assertEqual(conversation.messages[-1].content, "你好，读者")
        self.print_success("普通回答的事件顺序和消息保存正常")

    def test_usage_setting_controls_usage_request_and_event(self):
        enabled_client = FakeClient([[
            text_chunk("开启"),
            usage_chunk(),
        ]])
        with patch.object(chat_module, "get_model_connection", return_value=model_connection(enabled_client)):
            enabled_service = chat_module.ChatService()
            enabled_events = list(enabled_service.stream_message(
                TEST_BOOK_ID,
                "usage-enabled",
                "显示用量",
            ))

        usage = next(event for event in enabled_events if event.event == "usage")
        self.assertEqual(usage.data, {
            "input": 100,
            "output": 20,
            "total": 120,
            "cached_input": 60,
            "cache_miss_input": 40,
            "reasoning": 5,
        })
        self.assertEqual(
            enabled_client.chat.completions.calls[0]["stream_options"],
            {"include_usage": True},
        )

        disabled_client = FakeClient([[
            text_chunk("关闭"),
            usage_chunk(),
        ]])
        with (
            patch.object(
                chat_module,
                "get_app_settings",
                return_value={
                    "tool_round_limit": 100,
                    "show_usage": False,
                    "model_provider": "siliconflow",
                },
            ),
            patch.object(chat_module, "get_model_connection", return_value=model_connection(disabled_client)),
        ):
            disabled_service = chat_module.ChatService()
            disabled_events = list(disabled_service.stream_message(
                TEST_BOOK_ID,
                "usage-disabled",
                "隐藏用量",
            ))

        self.assertNotIn("usage", [event.event for event in disabled_events])
        self.assertNotIn("stream_options", disabled_client.chat.completions.calls[0])
        self.print_success("用量设置同时控制 API 请求和前端事件")

    def test_summary_setting_replaces_prompt_and_tools_for_existing_conversation(self):
        fake_client = FakeClient([
            [text_chunk("第一次回答")],
            [text_chunk("第二次回答")],
        ])

        def tools_for_setting(enabled):
            names = ["semantic_search"] + (["get_summary"] if enabled else [])
            return [{"type": "function", "function": {"name": name}} for name in names]

        with (
            patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)),
            patch.object(chat_module, "summary_enabled", side_effect=[False, True]),
            patch.object(
                chat_module,
                "get_system_prompt",
                side_effect=lambda enabled, max_chapter: f"prompt:{enabled}:{max_chapter}",
            ),
            patch.object(chat_module, "build_tools", side_effect=tools_for_setting),
        ):
            service = chat_module.ChatService()
            list(service.stream_message(TEST_BOOK_ID, "summary-toggle", "第一次"))
            list(service.stream_message(TEST_BOOK_ID, "summary-toggle", "第二次"))

        first_request, second_request = fake_client.chat.completions.calls
        self.assertEqual(first_request["messages"][0]["content"], "prompt:False:None")
        self.assertEqual(second_request["messages"][0]["content"], "prompt:True:None")
        self.assertEqual(
            [tool["function"]["name"] for tool in first_request["tools"]],
            ["semantic_search"],
        )
        self.assertEqual(
            [tool["function"]["name"] for tool in second_request["tools"]],
            ["semantic_search", "get_summary"],
        )
        self.print_success("旧对话会在下一次请求同步切换总结提示词和工具")

    def test_spoiler_limit_is_fixed_for_the_whole_request(self):
        fake_client = FakeClient([
            [tool_chunk("call-1", "get_chapter", '{"chapter_id":3}'), empty_chunk()],
            [text_chunk("当前阅读进度不足")],
        ])
        received_limits = []

        def get_chapter(chapter_id, context):
            received_limits.append(context.max_chapter)
            return {"kind": "error", "message": "防剧透模式已开启"}

        with (
            patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)),
            patch.object(chat_module, "spoiler_chapter_limit", return_value=2),
            patch.object(
                chat_module,
                "get_system_prompt",
                side_effect=lambda enabled, max_chapter: f"limit:{max_chapter}",
            ),
            patch.object(
                chat_module,
                "build_tools",
                return_value=[{"type": "function", "function": {"name": "get_chapter"}}],
            ),
            patch.object(chat_module, "AVAILABLE_TOOLS", {"get_chapter": get_chapter}),
        ):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "spoiler", "第三章发生了什么"))

        self.assertEqual(received_limits, [2])
        self.assertEqual(fake_client.chat.completions.calls[0]["messages"][0]["content"], "limit:2")
        tool_result = next(event for event in events if event.event == "tool_result")
        self.assertTrue(tool_result.data["error"])
        self.print_success("同一条回答的提示词和所有工具共用同一个防剧透上限")

    def test_provider_error_does_not_emit_done(self):
        fake_client = FakeClient([RuntimeError("connection lost")])

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "provider-error", "继续"))

        self.assertEqual(events[-1].event, "error")
        self.assertEqual(events[-1].data["code"], "provider_error")
        self.assertNotIn("done", [event.event for event in events])
        self.assertEqual(service._store.load_conversation("provider-error", TEST_BOOK_ID).messages[-1].role, "user")
        self.print_success("模型请求失败时会返回 error 且不会发送 done")

    def test_stream_error_keeps_answer_already_shown_to_user(self):
        def broken_response():
            yield text_chunk("已经生成的回答")
            raise RuntimeError("stream disconnected")

        fake_client = FakeClient([broken_response()])
        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "partial-answer", "请回答"))

        self.assertEqual([event.event for event in events], ["message_start", "token", "error"])
        self.assertEqual(events[-1].data["code"], "provider_stream_error")
        stored = service._store.load_conversation("partial-answer", TEST_BOOK_ID)
        self.assertEqual(stored.messages[-1].role, "assistant")
        self.assertEqual(stored.messages[-1].content, "已经生成的回答")

    def test_conversations_stay_bound_to_their_book(self):
        service = chat_module.ChatService()
        with patch.object(service, "_create_initial_messages", return_value=[]):
            service.create_conversation("book-1", "conversation-1", "书一会话", False)
            service.create_conversation("book-2", "conversation-2", "书二会话", False)

        self.assertEqual(
            [conversation.id for conversation in service.get_conversations("book-1")],
            ["conversation-1"],
        )
        fake_client = FakeClient([])
        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            events = list(service.stream_message("book-2", "conversation-1", "不会发送"))
        self.assertEqual(events[0].event, "error")
        self.assertEqual(events[0].data["code"], "conversation_book_mismatch")
        self.print_success("会话创建后始终绑定原书籍")

    def test_title_comes_from_the_first_user_message_and_is_not_replaced(self):
        fake_client = FakeClient([
            [text_chunk("第一次回答")],
            [text_chunk("第二次回答")],
        ])

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            first_events = list(service.stream_message(
                TEST_BOOK_ID,
                "title",
                "  请帮我分析\n这一段里发生了什么事情以及人物关系  ",
            ))
            second_events = list(service.stream_message(
                TEST_BOOK_ID,
                "title",
                "这句话不应该成为新标题",
            ))

        expected = "请帮我分析 这一段里发生了什么事情以及…"
        self.assertEqual(first_events[0].data["title"], expected)
        self.assertEqual(second_events[0].data["title"], expected)
        self.assertEqual(
            service._store.load_conversation("title", TEST_BOOK_ID).title,
            expected,
        )
        self.print_success("会话标题取首条用户消息并按长度截断")

    def test_tool_call_can_continue_to_final_answer(self):
        fake_client = FakeClient([
            [tool_chunk("call-1", "get_chapter_list", "{}"), empty_chunk()],
            [text_chunk("这是章节列表")],
        ])

        with patch.object(
            chat_module,
            "AVAILABLE_TOOLS",
            {"get_chapter_list": lambda context: {
                "kind": "chapter_list",
                "chapters": [{"chapter_id": 1, "title": "第一章"}],
            }},
        ), patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "tool", "列出章节"))

        self.assertEqual(
            [event.event for event in events],
            ["message_start", "tool_start", "tool_result", "token", "done"],
        )
        tool_result = next(event for event in events if event.event == "tool_result")
        self.assertFalse(tool_result.data["error"])
        self.assertEqual(tool_result.data["result"]["data"]["kind"], "chapter_list")
        self.assertEqual(tool_result.data["result"]["display"], "第 1 章：第一章")
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertEqual(
            fake_client.chat.completions.calls[1]["messages"][-1]["role"],
            "tool",
        )
        self.assertEqual(
            fake_client.chat.completions.calls[1]["messages"][-1]["content"],
            "第 1 章：第一章",
        )
        stored = service._store.load_conversation("tool", TEST_BOOK_ID)
        stored_result = json.loads(stored.messages[-2].content)
        self.assertEqual(stored_result["kind"], "chapter_list")
        self.assertEqual(stored.messages[-2].tool_status, "completed")
        self.assertNotIn("display", stored_result)
        self.print_success("工具调用完成后可以继续生成最终回答")

    def test_tool_round_limit_forces_a_final_answer_without_tools(self):
        fake_client = FakeClient([
            [
                text_chunk("先说明已经找到的部分。"),
                tool_chunk("call-limit", "get_chapter_list", "{}"),
                empty_chunk(),
            ],
            [text_chunk("根据目前查到的内容，这是最终回答。")],
        ])

        with (
            patch.object(
                chat_module,
                "get_app_settings",
                return_value={
                    "tool_round_limit": 1,
                    "show_usage": True,
                    "model_provider": "siliconflow",
                },
            ),
            patch.object(
                chat_module,
                "AVAILABLE_TOOLS",
                {"get_chapter_list": lambda context: {
                    "kind": "chapter_list",
                    "chapters": [{"chapter_id": 1, "title": "第一章"}],
                }},
            ),
            patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)),
        ):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "tool-limit", "继续查找"))

        self.assertEqual(
            [event.event for event in events],
            ["message_start", "token", "tool_start", "tool_result", "token", "done"],
        )
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertIn("tools", fake_client.chat.completions.calls[0])
        self.assertNotIn("tools", fake_client.chat.completions.calls[1])
        self.assertEqual(
            fake_client.chat.completions.calls[1]["messages"][-2]["role"],
            "tool",
        )
        self.assertEqual(
            fake_client.chat.completions.calls[1]["messages"][-1],
            {
                "role": "system",
                "content": "本轮回答已达工具调用次数上限：1 次。请根据已有信息直接回答用户。",
            },
        )

        stored = service._store.load_conversation("tool-limit", TEST_BOOK_ID)
        self.assertIsNotNone(stored)
        assistant_contents = [
            message.content
            for message in stored.messages
            if message.role == "assistant" and message.content
        ]
        tool_result = next(message for message in stored.messages if message.role == "tool")
        self.assertEqual(assistant_contents, [
            "先说明已经找到的部分。",
            "根据目前查到的内容，这是最终回答。",
        ])
        self.assertEqual(tool_result.tool_status, "completed")
        self.print_success("达到工具轮数上限后禁用工具并生成最终回答")

    def test_invalid_tool_arguments_return_tool_error_and_continue(self):
        fake_client = FakeClient([
            [tool_chunk("bad-call", "missing_tool", "不是 JSON"), empty_chunk()],
            [text_chunk("我无法执行这个工具")],
        ])

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            events = list(service.stream_message(TEST_BOOK_ID, "tool-error", "执行工具"))

        tool_result = next(event for event in events if event.event == "tool_result")
        self.assertTrue(tool_result.data["error"])
        self.assertEqual(tool_result.data["result"]["data"]["kind"], "error")
        self.assertTrue(tool_result.data["result"]["display"].startswith("工具执行失败："))
        stored = service._store.load_conversation("tool-error", TEST_BOOK_ID)
        self.assertEqual(stored.messages[-2].tool_status, "error")
        self.assertEqual(events[-1].event, "done")
        self.print_success("工具参数错误会返回 tool error，并允许流程继续")

    def test_busy_conversation_is_rejected(self):
        started = threading.Event()
        fake_client = FakeClient([BlockingResponse(started)])
        first_events = []

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()

            worker = threading.Thread(
                target=lambda: first_events.extend(
                    service.stream_message(TEST_BOOK_ID, "busy", "第一条消息")
                ),
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            second_events = list(service.stream_message(TEST_BOOK_ID, "busy", "第二条消息"))
            service.cancel_conversation(TEST_BOOK_ID, "busy")
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

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()

            worker = threading.Thread(
                target=lambda: events.extend(
                    service.stream_message(TEST_BOOK_ID, "cancel", "请生成长回答")
                ),
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            service.cancel_conversation(TEST_BOOK_ID, "cancel")
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertIn("error", [event.event for event in events])
        self.assertNotIn("done", [event.event for event in events])
        self.assertEqual(
            next(event for event in events if event.event == "error").data["code"],
            "user_interreption",
        )
        self.print_success("取消会话会返回 error 且不会发送 done")

    def test_busy_conversation_cannot_be_deleted(self):
        started = threading.Event()
        fake_client = FakeClient([BlockingResponse(started)])

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            worker = threading.Thread(
                target=lambda: list(
                    service.stream_message(TEST_BOOK_ID, "busy-delete", "请生成长回答")
                ),
            )
            worker.start()
            self.assertTrue(started.wait(timeout=2))

            with self.assertRaisesRegex(ValueError, "正在生成回复"):
                service.delete_conversation(TEST_BOOK_ID, "busy-delete")

            service.cancel_conversation(TEST_BOOK_ID, "busy-delete")
            worker.join(timeout=2)
            service.delete_conversation(TEST_BOOK_ID, "busy-delete")

        self.assertFalse(worker.is_alive())
        self.assertIsNone(service._store.load_conversation("busy-delete", TEST_BOOK_ID))
        self.print_success("正在生成回复的会话不能被删除，停止后可以删除")

    def test_cancelling_one_conversation_does_not_stop_another(self):
        first_started = threading.Event()
        second_started = threading.Event()
        fake_client = FakeClient([
            BlockingResponse(first_started),
            BlockingResponse(second_started),
        ])
        first_events = []
        second_events = []

        with patch.object(chat_module, "get_model_connection", return_value=model_connection(fake_client)):
            service = chat_module.ChatService()
            first_worker = threading.Thread(
                target=lambda: first_events.extend(
                    service.stream_message(TEST_BOOK_ID, "parallel-1", "第一条消息")
                ),
            )
            second_worker = threading.Thread(
                target=lambda: second_events.extend(
                    service.stream_message(TEST_BOOK_ID, "parallel-2", "第二条消息")
                ),
            )

            first_worker.start()
            self.assertTrue(first_started.wait(timeout=2))
            second_worker.start()
            self.assertTrue(second_started.wait(timeout=2))

            service.cancel_conversation(TEST_BOOK_ID, "parallel-1")
            first_worker.join(timeout=2)

            self.assertFalse(first_worker.is_alive())
            self.assertTrue(second_worker.is_alive())
            self.assertEqual(first_events[-1].data["code"], "user_interreption")
            self.assertNotIn("error", [event.event for event in second_events])

            service.cancel_conversation(TEST_BOOK_ID, "parallel-2")
            second_worker.join(timeout=2)

        self.assertFalse(second_worker.is_alive())
        self.assertEqual(second_events[-1].data["code"], "user_interreption")
        self.print_success("取消一个会话不会停止另一个并行会话")


if __name__ == "__main__":
    unittest.main()

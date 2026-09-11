import tempfile
import unittest
from pathlib import Path

from services.conversation_store import ConversationStore
from services.models import Message


class ConversationStoreTests(unittest.TestCase):
    def create_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return ConversationStore(Path(temp_dir.name) / "test.db")

    def print_success(self, message):
        print(f"[OK] {message}", flush=True)

    def test_two_conversations_store_system_messages_separately(self):
        store = self.create_store()

        store.create_conversation("conversation-1")
        store.create_conversation("conversation-2")

        store.save_message(
            "conversation-1",
            Message(id="system-1", role="system", content="会话一的系统提示"),
        )
        store.save_message(
            "conversation-1",
            Message(id="system-2", role="system", content="会话一的小说信息"),
        )
        store.save_message(
            "conversation-2",
            Message(id="system-3", role="system", content="会话二的系统提示"),
        )
        store.save_message(
            "conversation-2",
            Message(id="system-4", role="system", content="会话二的小说信息"),
        )

        first = store.load_conversation("conversation-1")
        second = store.load_conversation("conversation-2")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(len(first.messages), 2)
        self.assertEqual(len(second.messages), 2)
        self.assertEqual(first.messages[0].content, "会话一的系统提示")
        self.assertEqual(second.messages[0].content, "会话二的系统提示")
        self.print_success("两个会话的 system 消息可以分别保存")

    def test_delete_missing_conversation_is_safe(self):
        store = self.create_store()

        store.delete_conversation("not-exist")

        self.assertIsNone(store.load_conversation("not-exist"))
        self.print_success("删除不存在的会话不会报错")

    def test_delete_conversation(self):
        store = self.create_store()
        store.create_conversation("conversation-1")

        store.delete_conversation("conversation-1")

        self.assertIsNone(store.load_conversation("conversation-1"))
        self.assertNotIn("conversation-1", store.load_all_conversations())
        self.print_success("删除会话功能正常")

    def test_delete_conversation_cascades_to_messages(self):
        store = self.create_store()
        store.create_conversation("conversation-1")
        store.save_message(
            "conversation-1",
            Message(id="user-1", role="user", content="你好"),
        )
        store.save_message(
            "conversation-1",
            Message(id="assistant-1", role="assistant", content="你好，读者"),
        )

        store.delete_conversation("conversation-1")

        with store._connect() as connection:
            message_count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                ("conversation-1",),
            ).fetchone()[0]

        self.assertEqual(message_count, 0)
        self.print_success("删除会话后 messages 会级联删除")

    def test_create_same_conversation_twice_does_not_duplicate(self):
        store = self.create_store()

        store.create_conversation("conversation-1")
        store.create_conversation("conversation-1")

        conversations = store.load_all_conversations()

        self.assertEqual(list(conversations), ["conversation-1"])
        self.print_success("重复创建同一个会话不会产生重复记录")

    def test_messages_from_different_conversations_are_isolated(self):
        store = self.create_store()
        store.create_conversation("conversation-1")
        store.create_conversation("conversation-2")
        store.save_message(
            "conversation-1",
            Message(id="message-1", role="user", content="只属于会话一"),
        )
        store.save_message(
            "conversation-2",
            Message(id="message-2", role="user", content="只属于会话二"),
        )

        first = store.load_conversation("conversation-1")
        second = store.load_conversation("conversation-2")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual([message.content for message in first.messages], ["只属于会话一"])
        self.assertEqual([message.content for message in second.messages], ["只属于会话二"])
        self.print_success("不同会话的消息互不影响")

    def test_message_order_is_preserved(self):
        store = self.create_store()
        store.create_conversation("conversation-1")

        messages = [
            Message(id="message-1", role="system", content="系统"),
            Message(id="message-2", role="user", content="用户"),
            Message(id="message-3", role="assistant", content="助手"),
            Message(id="message-4", role="tool", content="工具"),
        ]
        for message in messages:
            store.save_message("conversation-1", message)

        conversation = store.load_conversation("conversation-1")

        self.assertIsNotNone(conversation)
        self.assertEqual(
            [message.id for message in conversation.messages],
            ["message-1", "message-2", "message-3", "message-4"],
        )
        self.print_success("消息顺序保持不变")

    def test_tool_message_fields_are_preserved(self):
        store = self.create_store()
        store.create_conversation("conversation-1")
        tool_calls = [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "get_chapter",
                    "arguments": '{"chapter_id": 1}',
                },
            }
        ]
        store.save_message(
            "conversation-1",
            Message(
                id="assistant-1",
                role="assistant",
                content=None,
                tool_calls=tool_calls,
            ),
        )
        store.save_message(
            "conversation-1",
            Message(
                id="tool-1",
                role="tool",
                content='{"title":"第一章"}',
                tool_call_id="call-1",
            ),
        )

        conversation = store.load_conversation("conversation-1")

        self.assertIsNotNone(conversation)
        assistant = conversation.messages[0]
        tool = conversation.messages[1]
        self.assertEqual(assistant.content, None)
        self.assertEqual(assistant.tool_calls, tool_calls)
        self.assertEqual(tool.tool_call_id, "call-1")
        self.assertEqual(tool.content, '{"title":"第一章"}')
        self.print_success("tool_calls 和 tool_call_id 等字段保存完整")


if __name__ == "__main__":
    unittest.main()

"""Conversation orchestration shared by the CLI and FastAPI."""

from __future__ import annotations
import json
import threading
import uuid
import copy
from typing import Any, Iterator

from config import MODEL, SHOW_USAGE, USE_SUMMARY_TOOL, MESSAGE_STORAGE_FILE, client, BookPaths
from novel_tools import AVAILABLE_TOOLS, build_tools, load_titles
from prompts import get_system_prompt
from usage_stats import get_field, read_usage
from services.conversation_store import ConversationStore
from services.models import ChatEvent, Conversation, Message
from tool_results import (
    error_result,
    format_tool_result_data,
    load_tool_result_data,
    make_tool_result,
)


MAX_TOOL_ROUNDS = 100
MAX_CONVERSATION_TITLE_LENGTH = 20


def conversation_title(user_content: str) -> str:
    title = " ".join(user_content.split()) or "新对话"
    if len(title) <= MAX_CONVERSATION_TITLE_LENGTH:
        return title
    return title[:MAX_CONVERSATION_TITLE_LENGTH - 1] + "…"


class ChatService:
    def __init__(self) -> None:
        self._store = ConversationStore(MESSAGE_STORAGE_FILE)
        self._tools = build_tools(USE_SUMMARY_TOOL)
        self._available_tools = AVAILABLE_TOOLS

        self._conversations: dict[str, Conversation] = self._store.load_all_conversations()
        self._locks: dict[str, threading.Lock] = {
            conversation_id: threading.Lock()
            for conversation_id in self._conversations
        }
        self._cancel_events: dict[str, threading.Event] = {
            conversation_id: threading.Event()
            for conversation_id in self._conversations
        }
        self._conversations_lock = threading.Lock()

    def create_conversation(self, book_id: str, conversation_id: str, title: str) -> str:
        with self._conversations_lock:
            existing = self._conversations.get(conversation_id)
            if existing is not None:
                if existing.book_id != book_id:
                    raise ValueError("该会话属于另一本书")
                return existing.title

            book_path = BookPaths(book_id)
            messages = self._create_initial_messages(book_path)
            self._store.create_conversation(conversation_id, book_id, title)
            self._conversations[conversation_id] = Conversation(
                id=conversation_id,
                book_id=book_id,
                title=title,
                messages=messages,
            )
            for message in messages:
                self._store.save_message(conversation_id, message)
            self._locks[conversation_id] = threading.Lock()
            self._cancel_events[conversation_id] = threading.Event()
            return title
    
    def delete_conversation(self, book_id: str, conversation_id: str) -> None:
        with self._conversations_lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is not None and conversation.book_id != book_id:
                raise ValueError("该会话属于另一本书")
            lock = self._locks.get(conversation_id)
            if lock is not None and lock.locked():
                raise ValueError("该会话正在生成回复，请先停止生成")
            self._store.delete_conversation(conversation_id, book_id)
            self._conversations.pop(conversation_id, None)
            self._locks.pop(conversation_id, None)
            self._cancel_events.pop(conversation_id, None)

    def cancel_conversation(self, book_id: str, conversation_id: str) -> None:
        with self._conversations_lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is not None and conversation.book_id != book_id:
                raise ValueError("该会话属于另一本书")
            cancel_event = self._cancel_events.get(conversation_id)
            if cancel_event is not None:
                cancel_event.set()

    def stream_message(
        self,
        book_id: str,
        conversation_id: str,
        user_content: str,
    ) -> Iterator[ChatEvent]:
        try:
            title = self.create_conversation(
                book_id,
                conversation_id,
                conversation_title(user_content),
            )
        except ValueError as exc:
            yield ChatEvent("error", {
                "code": "conversation_book_mismatch",
                "message": str(exc),
            })
            return

        book_path = BookPaths(book_id)
        load_titles(book_path)
        with self._conversations_lock:
            lock = self._locks[conversation_id]
            acquired = lock.acquire(blocking=False)
            if acquired:
                cancel_event = self._cancel_events.get(conversation_id)
                if cancel_event is None:
                    cancel_event = threading.Event()
                    self._cancel_events[conversation_id] = cancel_event

        if not acquired:
            yield ChatEvent("error", {
                "code": "conversation_busy",
                "message": "该会话正在处理上一条消息，请稍候再试",
            })
            return
        message_id = str(uuid.uuid4())
        try:
            self._append_message(
                conversation_id,
                Message(id=message_id, role="user", content=user_content),
            )
            yield ChatEvent("message_start", {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "title": title,
            })

            has_error = False
            for event in self._run_model(book_path, conversation_id, cancel_event):
                yield event
                has_error = has_error or event.event == "error"

            if not has_error:
                yield ChatEvent("done", {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                })
        finally:
            self._cancel_events.pop(conversation_id, None)
            lock.release()

    def _run_model(self, book_path: BookPaths, conversation_id: str,cancel_event:threading.Event) -> Iterator[ChatEvent]:
        for round_index in range(1, MAX_TOOL_ROUNDS + 1):
            if cancel_event.is_set():
                yield ChatEvent("error", {
                "code": "user_interreption",
                "message": "用户终止了这条回答",
                })
                return
            request_args: dict[str, Any] = {
                "model": MODEL,
                "messages": self._messages_for_request(conversation_id),
                "tools": self._tools,
                "stream": True,
            }
            if SHOW_USAGE:
                request_args["stream_options"] = {"include_usage": True}

            try:
                response = client.chat.completions.create(**request_args)
            except Exception as exc:
                yield ChatEvent("error", {
                    "code": "provider_error",
                    "message": str(exc),
                })
                return

            full_content = ""
            tool_calls: list[dict[str, Any]] = []
            current_usage: dict[str, int] | None = None

            try:
                for chunk in response:
                    if cancel_event.is_set():
                        self._append_message(conversation_id, Message(
                            id=str(uuid.uuid4()),
                            role="assistant",
                            content=full_content or None,
                        ))
                        yield ChatEvent("error", {
                        "code": "user_interreption",
                        "message": "用户终止了这条回答",
                        })
                        return
                    if SHOW_USAGE:
                        usage = get_field(chunk, "usage")
                        if usage is not None:
                            current_usage = read_usage(usage)

                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    if not delta:
                        continue

                    if delta.content:
                        full_content += delta.content
                        yield ChatEvent("token", {"content": delta.content})

                    if delta.tool_calls:
                        for tool_call in delta.tool_calls:
                            index = tool_call.index
                            while len(tool_calls) <= index:
                                tool_calls.append({
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                })
                            slot = tool_calls[index]
                            if tool_call.id:
                                slot["id"] = tool_call.id
                            if tool_call.function:
                                if tool_call.function.name:
                                    slot["function"]["name"] = tool_call.function.name
                                if tool_call.function.arguments:
                                    slot["function"]["arguments"] += tool_call.function.arguments
            except Exception as exc:
                yield ChatEvent("error", {
                    "code": "provider_stream_error",
                    "message": str(exc),
                })
                return

            if current_usage is not None:
                yield ChatEvent("usage", current_usage)

            assistant_message = Message(
                id=str(uuid.uuid4()),
                role="assistant",
                content=full_content or None,
            )
            if tool_calls:
                assistant_message.tool_calls = tool_calls
            self._append_message(conversation_id, assistant_message)

            if not tool_calls:
                return

            for tool_call in tool_calls:
                yield from self._execute_tool(book_path, conversation_id, tool_call, round_index)

        yield ChatEvent("error", {
            "code": "tool_round_limit",
            "message": f"工具调用超过最大轮数 {MAX_TOOL_ROUNDS}",
        })

    def _execute_tool(
        self,
        book_path: BookPaths,
        conversation_id: str,
        tool_call: dict[str, Any],
        round_index: int,
    ) -> Iterator[ChatEvent]:
        call_id = tool_call.get("id", "")
        function = tool_call.get("function", {})
        name = function.get("name", "")
        raw_arguments = function.get("arguments", "") or "{}"

        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            if name not in self._available_tools:
                raise ValueError(f"Unknown tool: {name}")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            result_data = error_result(str(exc))
            result = make_tool_result(result_data)
            self._append_tool_result(conversation_id, call_id, result_data)
            yield ChatEvent("tool_result", {
                "round": round_index,
                "tool_call_id": call_id,
                "name": name,
                "arguments": {},
                "result": result,
                "error": True,
            })
            return

        yield ChatEvent("tool_start", {
            "round": round_index,
            "tool_call_id": call_id,
            "name": name,
            "arguments": arguments,
        })
        try:
            result_data = self._available_tools[name](
                book_path=book_path,
                **arguments,
            )
            if not isinstance(result_data, dict):
                raise TypeError(f"工具 {name} 没有返回字典")
            result = make_tool_result(result_data)
            is_error = result_data.get("kind") == "error"
        except Exception as exc:
            result_data = error_result(str(exc))
            result = make_tool_result(result_data)
            is_error = True

        self._append_tool_result(conversation_id, call_id, result_data)
        yield ChatEvent("tool_result", {
            "round": round_index,
            "tool_call_id": call_id,
            "name": name,
            "arguments": arguments,
            "result": result, #yield出处理后的结果
            "error": is_error,
        })

    def _append_tool_result(self, conversation_id: str, call_id: str, result: dict[str, Any]) -> None:
        self._append_message(
            conversation_id,
            Message(
                id=str(uuid.uuid4()),
                role="tool",
                tool_call_id=call_id,
                content=json.dumps(result, ensure_ascii=False), #保存原始结构
            ),
        )

    def _append_message(self, conversation_id: str, message: Message) -> None:
        with self._conversations_lock:
            self._conversations[conversation_id].messages.append(message)
            self._store.save_message(conversation_id, message)

    def _messages_for_request(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._conversations_lock:
            messages = self._conversations[conversation_id].messages
            return [self._message_for_request(message) for message in messages]

    @staticmethod
    def _message_for_request(message: Message) -> dict[str, Any]:
        #转换数据类型，同时将工具的原始结果加工处理
        request_message: dict[str, Any] = {"role": message.role}
        if message.content is not None:
            request_message["content"] = (
                format_tool_result_data(load_tool_result_data(message.content))
                if message.role == "tool"
                else message.content
            )
        if message.tool_calls is not None:
            request_message["tool_calls"] = copy.deepcopy(message.tool_calls)
        if message.tool_call_id is not None:
            request_message["tool_call_id"] = message.tool_call_id
        return request_message

    def _create_initial_messages(self, book_path: BookPaths) -> list[Message]:
        with open(book_path.info_file, "r", encoding="utf-8") as file:
            info_text = file.read()
        return [
            Message(
                id=str(uuid.uuid4()),
                role="system",
                content=get_system_prompt(USE_SUMMARY_TOOL),
            ),
            Message(
                id=str(uuid.uuid4()),
                role="system",
                content="这是小说的基本信息：" + info_text,
            ),
        ]

    def get_conversations(self, book_id: str) -> list[Conversation]:
        """Return a snapshot of all persisted conversations for the API layer."""
        with self._conversations_lock:
            return copy.deepcopy([
                conversation
                for conversation in self._conversations.values()
                if conversation.book_id == book_id
            ])

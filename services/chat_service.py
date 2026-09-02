"""Conversation orchestration shared by the CLI and FastAPI."""

from __future__ import annotations

import json
import threading
import uuid
import copy
from dataclasses import dataclass, field
from typing import Any, Iterator

from config import INFO_FILE, MODEL, SHOW_USAGE, USE_SUMMARY_TOOL, client
from novel_tools import AVAILABLE_TOOLS, build_tools, load_titles,get_chapter_list,get_chapter,search_keyword,search_keyword_in_chapter,semantic_search,get_summary
from prompts import get_system_prompt
from usage_stats import get_field, read_usage


MAX_TOOL_ROUNDS = 100


@dataclass(frozen=True)
class ChatEvent:
    """A transport-neutral event emitted while processing one message."""
    event: str
    data: dict[str, Any]

@dataclass
class Message:
    id: str
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

@dataclass
class Conversation:
    id: str
    messages: list[Message] = field(default_factory=list)


class ChatService:
    def __init__(self) -> None:
        self._tools = build_tools(USE_SUMMARY_TOOL)
        self._available_tools = AVAILABLE_TOOLS
        self._conversations: dict[str, Conversation] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._conversations_lock = threading.Lock()
        self._cancel_events :dict[str,threading.Event] = {}

        with open(INFO_FILE, "r", encoding="utf-8") as file:
            info_text = file.read()

        self._initial_messages = [
            Message(id="001", role="system", content=get_system_prompt(USE_SUMMARY_TOOL)),
            Message(id="002", role="system", content="这是小说的基本信息：" + info_text),
        ]
        load_titles()

    def create_conversation(self, conversation_id: str) -> None:
        #惰性加载，对话不存在时就新建对话
        with self._conversations_lock:
            if conversation_id not in self._conversations:
                mes = self._copy_initial_messages()
                self._conversations[conversation_id] = Conversation(id=conversation_id, messages=mes)
                self._locks[conversation_id] = threading.Lock()
                self._cancel_events[conversation_id] = threading.Event()
    
    def delete_conversation(self, conversation_id: str) -> None:
        with self._conversations_lock:
            self._conversations.pop(conversation_id, None)
            self._locks.pop(conversation_id, None)
            self._cancel_events.pop(conversation_id, None)

    def cancel_conversation(self, conversation_id: str) -> None:
        with self._conversations_lock:
            self._cancel_events[conversation_id].set()

    def stream_message(
        self,
        conversation_id: str,
        user_content: str,
    ) -> Iterator[ChatEvent]:
        self.create_conversation(conversation_id)
        lock = self._locks[conversation_id]
        
        if not lock.acquire(blocking=False):
            yield ChatEvent("error", {
                "code": "conversation_busy",
                "message": "该会话正在处理上一条消息，请稍候再试",
            })
            return
        cancel_event = threading.Event()
        self._cancel_events[conversation_id] = cancel_event
        message_id = str(uuid.uuid4())
        try:
            print("进入 try:", conversation_id)
            self._append_message(
                conversation_id,
                Message(id=message_id, role="user", content=user_content),
            )
            yield ChatEvent("message_start", {
                "conversation_id": conversation_id,
                "message_id": message_id,
            })

            has_error = False
            for event in self._run_model(conversation_id, cancel_event):
                if cancel_event.is_set():
                    return
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
            print("锁已经释放（finally）:", conversation_id)

    def _run_model(self, conversation_id: str,cancel_event:threading.Event) -> Iterator[ChatEvent]:
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
                yield from self._execute_tool(conversation_id, tool_call, round_index)

        yield ChatEvent("error", {
            "code": "tool_round_limit",
            "message": f"工具调用超过最大轮数 {MAX_TOOL_ROUNDS}",
        })

    def _execute_tool(
        self,
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
            result: Any = f"Tool execution failed: {exc}"
            self._append_tool_result(conversation_id, call_id, result)
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
            result = self._available_tools[name](**arguments)
            is_error = False
        except Exception as exc:
            result = f"工具执行失败:{exc}"
            is_error = True

        self._append_tool_result(conversation_id, call_id, result)
        yield ChatEvent("tool_result", {
            "round": round_index,
            "tool_call_id": call_id,
            "name": name,
            "arguments": arguments,
            "result": result,
            "error": is_error,
        })

    def _append_tool_result(self, conversation_id: str, call_id: str, result: Any) -> None:
        self._append_message(
            conversation_id,
            Message(
                id=str(uuid.uuid4()),
                role="tool",
                tool_call_id=call_id,
                content=json.dumps(result, ensure_ascii=False, default=str),
            ),
        )

    def _append_message(self, conversation_id: str, message: Message) -> None:
        with self._conversations_lock:
            self._conversations[conversation_id].messages.append(message)

    def _messages_for_request(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._conversations_lock:
            messages = self._conversations[conversation_id].messages
            return [self._message_for_request(message) for message in messages]

    @staticmethod
    def _message_for_request(message: Message) -> dict[str, Any]:
        request_message: dict[str, Any] = {"role": message.role}
        if message.content is not None:
            request_message["content"] = message.content
        if message.tool_calls is not None:
            request_message["tool_calls"] = copy.deepcopy(message.tool_calls)
        if message.tool_call_id is not None:
            request_message["tool_call_id"] = message.tool_call_id
        return request_message

    def _copy_initial_messages(self) -> list[Message]:
        return copy.deepcopy(self._initial_messages)

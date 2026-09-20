import { describe, expect, it } from "vitest";
import {
  addTokenUsage,
  applyChatEvent,
  timelineFromConversation,
} from "../chatTimeline";
import type { Conversation } from "../types";

describe("chat timeline", () => {
  it("accumulates usage from every model call in one answer", () => {
    const first = addTokenUsage(null, {
      input: 100,
      output: 20,
      total: 120,
      cached_input: 60,
      cache_miss_input: 40,
      reasoning: 5,
    });
    const total = addTokenUsage(first, {
      input: 80,
      output: 10,
      total: 90,
      cached_input: 50,
      cache_miss_input: 30,
      reasoning: 2,
    });

    expect(total).toEqual({
      input: 180,
      output: 30,
      total: 210,
      cached_input: 110,
      cache_miss_input: 70,
      reasoning: 7,
    });
  });

  it("can restore saved user, tool, and assistant messages", () => {
    const conversation: Conversation = {
      id: "conversation-1",
      book_id: "book-1",
      title: "请读取第一章",
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "请读取第一章",
          tool_calls: null,
          tool_call_id: null,
          tool_status: null,
          tool_result: null,
        },
        {
          id: "assistant-1",
          role: "assistant",
          content: null,
          tool_calls: [
            {
              id: "call-1",
              type: "function",
              function: {
                name: "get_chapter",
                arguments: '{"chapter_id":1}',
              },
            },
          ],
          tool_call_id: null,
          tool_status: null,
          tool_result: null,
        },
        {
          id: "tool-1",
          role: "tool",
          content: '{"title":"第一章"}',
          tool_calls: null,
          tool_call_id: "call-1",
          tool_status: "error",
          tool_result: {
            data: { kind: "chapter", chapter_id: 1, title: "第一章", content: "正文" },
            display: "正文",
          },
        },
        {
          id: "assistant-2",
          role: "assistant",
          content: "第一章的内容如下。",
          tool_calls: null,
          tool_call_id: null,
          tool_status: null,
          tool_result: null,
        },
      ],
    };

    const items = timelineFromConversation(conversation);

    expect(items.map((item) => item.type)).toEqual([
      "user",
      "tool",
      "assistant",
    ]);
    expect(items[0]).toMatchObject({
      id: "user-1",
      type: "user",
      content: "请读取第一章",
    });
    expect(items[1]).toMatchObject({
      id: "tool-1",
      type: "tool",
      tool: {
        id: "call-1",
        name: "get_chapter",
        arguments: { chapter_id: 1 },
        result: {
          data: { kind: "chapter", chapter_id: 1, title: "第一章", content: "正文" },
          display: "正文",
        },
        status: "error",
      },
    });
    expect(items[2]).toMatchObject({
      id: "assistant-2",
      type: "assistant",
      content: "第一章的内容如下。",
    });
  });

  it("appends streamed tokens to the current assistant message", () => {
    const initialItems = [
      { id: "assistant-1", type: "assistant" as const, content: "你好" },
    ];

    const items = applyChatEvent(initialItems, {
      event: "token",
      data: { content: "，读者" },
    });

    expect(items).toEqual([
      { id: "assistant-1", type: "assistant", content: "你好，读者" },
    ]);
  });

  it("matches a streamed tool result with its running tool call", () => {
    const started = applyChatEvent([], {
      event: "tool_start",
      data: {
        tool_call_id: "call-1",
        name: "get_chapter",
        arguments: { chapter_id: 3 },
      },
    });
    const completed = applyChatEvent(started, {
      event: "tool_result",
      data: {
        tool_call_id: "call-1",
        result: {
          data: { kind: "chapter", chapter_id: 3, title: "第三章", content: "第三章正文" },
          display: "第三章正文",
        },
        error: false,
      },
    });

    expect(completed).toHaveLength(1);
    expect(completed[0]).toMatchObject({
      type: "tool",
      tool: {
        id: "call-1",
        name: "get_chapter",
        arguments: { chapter_id: 3 },
        result: {
          data: { kind: "chapter", chapter_id: 3, title: "第三章", content: "第三章正文" },
          display: "第三章正文",
        },
        status: "completed",
      },
    });
  });
});

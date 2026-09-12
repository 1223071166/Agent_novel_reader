import { describe, expect, it } from "vitest";
import {
  applyChatEvent,
  timelineFromConversation,
} from "../chatTimeline";
import type { SavedConversation } from "../api";
//D
describe("chat timeline", () => {
  it("can restore saved user, tool, and assistant messages", () => {
    const conversation: SavedConversation = {
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
        },
        {
          id: "tool-1",
          role: "tool",
          content: '{"title":"第一章"}',
          tool_calls: null,
          tool_call_id: "call-1",
        },
        {
          id: "assistant-2",
          role: "assistant",
          content: "第一章的内容如下。",
          tool_calls: null,
          tool_call_id: null,
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
        result: { title: "第一章" },
        status: "completed",
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
});

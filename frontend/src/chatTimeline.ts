import type { SavedConversation } from "./api";

export type ToolStatus = "running" | "completed" | "error";

export type ToolCall = {
  id: string;
  name: string;
  arguments: unknown;
  result?: unknown;
  status: ToolStatus;
};

export type TimelineItem =
  | {
      id: string;
      type: "user";
      content: string;
    }
  | {
      id: string;
      type: "assistant";
      content: string;
    }
  | {
      id: string;
      type: "tool";
      tool: ToolCall;
    };

export type TimelineEvent = {
  event: string;
  data: Record<string, unknown>;
};

const newId = () => crypto.randomUUID();

function parseToolResult(content: string | null): unknown {
  if (content === null) return undefined;
  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

export function timelineFromConversation(conversation: SavedConversation): TimelineItem[] {
  const items: TimelineItem[] = [];
  const toolCalls = new Map<string, { name: string; arguments: unknown }>();

  for (const message of conversation.messages) {
    if (message.role === "user" && message.content !== null) {
      items.push({ id: message.id, type: "user", content: message.content });
      continue;
    }

    if (message.role === "assistant") {
      for (const call of message.tool_calls ?? []) {
        const id = String(call.id ?? "");
        if (id) {
          let args: unknown = call.function?.arguments ?? "{}";
          try { args = JSON.parse(String(args)); } catch { /* keep raw arguments */ }
          toolCalls.set(id, { name: String(call.function?.name ?? "unknown"), arguments: args });
        }
      }
      if (message.content !== null && message.content !== "") {
        items.push({ id: message.id, type: "assistant", content: message.content });
      }
      continue;
    }

    if (message.role === "tool") {
      const call = toolCalls.get(message.tool_call_id ?? "");
      items.push({
        id: message.id,
        type: "tool",
        tool: {
          id: message.tool_call_id ?? newId(),
          name: call?.name ?? "unknown",
          arguments: call?.arguments ?? {},
          result: parseToolResult(message.content),
          status: "completed",
        },
      });
    }
  }
  return items;
}

export function appendUserItem(items: TimelineItem[], content: string): TimelineItem[] {
  return [
    ...items,
    { id: newId(), type: "user", content },
    { id: newId(), type: "assistant", content: "" },
  ];
}

export function applyChatEvent(items: TimelineItem[], { event, data }: TimelineEvent): TimelineItem[] {
  if (event === "token") {
    const content = String(data.content ?? "");
    if (!content) return items;

    const last = items[items.length - 1];
    if (last?.type === "assistant") {
      return [
        ...items.slice(0, -1),
        { ...last, content: `${last.content}${content}` },
      ];
    }
    return [...items, { id: newId(), type: "assistant", content }];
  }

  if (event === "tool_start") {
    return [
      ...items,
      {
        id: newId(),
        type: "tool",
        tool: {
          id: String(data.tool_call_id ?? newId()),
          name: String(data.name ?? "unknown"),
          arguments: data.arguments ?? {},
          status: "running",
        },
      },
    ];
  }

  if (event === "tool_result") {
    const toolId = String(data.tool_call_id ?? "");
    const status: ToolStatus = data.error ? "error" : "completed";
    const index = items.findIndex((item) => item.type === "tool" && item.tool.id === toolId);

    if (index === -1) {
      return [
        ...items,
        {
          id: newId(),
          type: "tool",
          tool: {
            id: toolId || newId(),
            name: String(data.name ?? "unknown"),
            arguments: data.arguments ?? {},
            result: data.result,
            status,
          },
        },
      ];
    }

    return items.map((item, itemIndex) => (
      itemIndex === index && item.type === "tool"
        ? { ...item, tool: { ...item.tool, result: data.result, status } }
        : item
    ));
  }

  return items;
}

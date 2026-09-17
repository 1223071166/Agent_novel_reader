import type {
  ChatEvent,
  Conversation,
  TimelineItem,
  ToolResult,
  ToolStatus,
} from "./types";

const newId = () => crypto.randomUUID();

export function timelineFromConversation(conversation: Conversation): TimelineItem[] {
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
          result: message.tool_result ?? undefined,
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

export function applyChatEvent(items: TimelineItem[], { event, data }: ChatEvent): TimelineItem[] {
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
            result: data.result as ToolResult,
            status,
          },
        },
      ];
    }

    return items.map((item, itemIndex) => (
      itemIndex === index && item.type === "tool"
        ? { ...item, tool: { ...item.tool, result: data.result as ToolResult, status } }
        : item
    ));
  }

  return items;
}

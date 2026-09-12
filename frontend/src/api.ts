export type ChatEvent = {
  event: string;
  data: Record<string, unknown>;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type SavedMessage = {
  id: string;
  role: string;
  content: string | null;
  tool_calls: Array<{
    id?: string;
    type?: string;
    function?: { name?: string; arguments?: string };
  }> | null;
  tool_call_id: string | null;
};

export type SavedConversation = {
  id: string;
  book_id: string;
  messages: SavedMessage[];
};

export type BookSelection = {
  books: string[];
  selected_book_id: string | null;
};

export async function loadBookSelection(): Promise<BookSelection> {
  const response = await fetch(`${API_BASE_URL}/api/books`);
  if (!response.ok) throw new Error(`加载书籍失败（${response.status}）`);
  return await response.json() as BookSelection;
}

export async function loadConversations(bookId: string): Promise<SavedConversation[]> {
  const query = new URLSearchParams({ book_id: bookId });
  const response = await fetch(`${API_BASE_URL}/api/conversations?${query}`);
  if (!response.ok) throw new Error(`加载历史会话失败（${response.status}）`);
  const body = await response.json() as { conversations?: SavedConversation[] };
  return body.conversations ?? [];
}

export async function deleteConversation(bookId: string, conversationId: string): Promise<void> {
  const query = new URLSearchParams({ book_id: bookId });
  const response = await fetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}?${query}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(`删除会话失败（${response.status}）`);
}

export async function streamChat(
  bookId: string,
  conversationId: string,
  message: string,
  onEvent: (event: ChatEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ book_id: bookId, conversation_id: conversationId, message })
  });

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the HTTP status message when the server did not return JSON.
    }
    throw new Error(detail);
  }

  if (!response.body) throw new Error("服务器没有返回流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const eventLine = block.split("\n").find((line) => line.startsWith("event: "));
      const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
      if (!eventLine || !dataLine) continue;
      onEvent({
        event: eventLine.slice("event: ".length),
        data: JSON.parse(dataLine.slice("data: ".length)),
      });
    }
    if (done) break;
  }
}

export async function cancelStream(bookId: string, conversationId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ book_id: bookId, conversation_id: conversationId }),
  });
  if (!response.ok) throw new Error(`取消请求失败（${response.status}）`);
}
  

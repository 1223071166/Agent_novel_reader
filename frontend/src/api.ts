import type {
  BookImportStatus,
  BookSelection,
  ChatEvent,
  Conversation,
  ReadingSettings,
  SummaryJob,
  SummaryOverview,
  SummaryPlan,
  SummaryTarget,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function responseError(response: Response, fallback: string): Promise<Error> {
  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === "string") return new Error(body.detail);
  } catch {
    // Use the fallback when the response is not JSON.
  }
  return new Error(`${fallback}（${response.status}）`);
}

export async function loadBookSelection(): Promise<BookSelection> {
  const response = await fetch(`${API_BASE_URL}/api/books`);
  if (!response.ok) throw await responseError(response, "加载书籍失败");
  return await response.json() as BookSelection;
}

export async function saveBookSelection(bookId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/books/selected`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ book_id: bookId }),
  });
  if (!response.ok) throw await responseError(response, "保存当前书籍失败");
}


export async function loadReadingSettings(bookId: string): Promise<ReadingSettings> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/reading-settings`,
  );
  if (!response.ok) throw await responseError(response, "加载防剧透设置失败");
  return await response.json() as ReadingSettings;
}

export async function saveReadingSettings(
  bookId: string,
  spoilerMode: boolean,
  readThroughChapter: number,
): Promise<ReadingSettings> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/reading-settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        spoiler_mode: spoilerMode,
        read_through_chapter: readThroughChapter,
      }),
    },
  );
  if (!response.ok) throw await responseError(response, "保存防剧透设置失败");
  return await response.json() as ReadingSettings;
}


export async function loadSummaryOverview(bookId: string): Promise<SummaryOverview> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/summaries`,
  );
  if (!response.ok) throw await responseError(response, "加载总结状态失败");
  return await response.json() as SummaryOverview;
}

export async function saveSummaryEnabled(
  bookId: string,
  enabled: boolean,
): Promise<SummaryOverview> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/summary-settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
  if (!response.ok) throw await responseError(response, "保存总结检索设置失败");
  return await response.json() as SummaryOverview;
}

export async function planSummaries(
  bookId: string,
  targets: SummaryTarget[],
): Promise<SummaryPlan> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/summaries/plan`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    },
  );
  if (!response.ok) throw await responseError(response, "估算总结消耗失败");
  return await response.json() as SummaryPlan;
}

export async function startSummaryJob(
  bookId: string,
  targets: SummaryTarget[],
): Promise<SummaryJob> {
  const response = await fetch(
    `${API_BASE_URL}/api/books/${encodeURIComponent(bookId)}/summary-jobs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    },
  );
  if (!response.ok) throw await responseError(response, "启动总结任务失败");
  return await response.json() as SummaryJob;
}

export async function importBook(file: File): Promise<BookImportStatus> {
  const response = await fetch(`${API_BASE_URL}/api/book-imports`, {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-File-Name": encodeURIComponent(file.name),
    },
    body: file,
  });
  if (!response.ok) throw await responseError(response, "导入小说失败");
  return await response.json() as BookImportStatus;
}

export async function saveBookInfo(
  bookId: string,
  name: string,
  content: string,
): Promise<BookImportStatus> {
  const response = await fetch(
    `${API_BASE_URL}/api/book-imports/${encodeURIComponent(bookId)}/info`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content }),
    },
  );
  if (!response.ok) throw await responseError(response, "保存书籍信息失败");
  return await response.json() as BookImportStatus;
}

export async function startBookEmbedding(bookId: string): Promise<BookImportStatus> {
  const response = await fetch(
    `${API_BASE_URL}/api/book-imports/${encodeURIComponent(bookId)}/embedding`,
    { method: "POST" },
  );
  if (!response.ok) throw await responseError(response, "启动向量化失败");
  return await response.json() as BookImportStatus;
}

export async function loadBookEmbeddingStatus(bookId: string): Promise<BookImportStatus> {
  const response = await fetch(
    `${API_BASE_URL}/api/book-imports/${encodeURIComponent(bookId)}/embedding`,
  );
  if (!response.ok) throw await responseError(response, "读取向量化进度失败");
  return await response.json() as BookImportStatus;
}

export async function loadBookImport(bookId: string): Promise<BookImportStatus> {
  const response = await fetch(
    `${API_BASE_URL}/api/book-imports/${encodeURIComponent(bookId)}`,
  );
  if (!response.ok) throw await responseError(response, "读取导入进度失败");
  return await response.json() as BookImportStatus;
}

export async function discardBookImport(bookId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/book-imports/${encodeURIComponent(bookId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw await responseError(response, "放弃导入失败");
}

export async function loadConversations(bookId: string): Promise<Conversation[]> {
  const query = new URLSearchParams({ book_id: bookId });
  const response = await fetch(`${API_BASE_URL}/api/conversations?${query}`);
  if (!response.ok) throw await responseError(response, "加载历史会话失败");
  const body = await response.json() as { conversations: Conversation[] };
  return body.conversations;
}

export async function deleteConversation(bookId: string, conversationId: string): Promise<void> {
  const query = new URLSearchParams({ book_id: bookId });
  const response = await fetch(
    `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId)}?${query}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw await responseError(response, "删除会话失败");
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

  if (!response.ok) throw await responseError(response, "请求失败");

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
  if (!response.ok) throw await responseError(response, "取消请求失败");
}
  

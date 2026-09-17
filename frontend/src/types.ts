// 后端接口返回或接收的数据类型

export type ChatEvent = {
  event: string;
  data: Record<string, unknown>;
};

export type ToolResult = {
  data: {
    kind: string;
    [key: string]: unknown;
  };
  display: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_calls: Array<{
    id?: string;
    type?: string;
    function?: { name?: string; arguments?: string };
  }> | null;
  tool_call_id: string | null;
  tool_result: ToolResult | null;
};

export type Conversation = {
  id: string;
  book_id: string;
  title: string;
  messages: Message[];
};

export type BookSelection = {
  books: string[];
  importing_book_ids: string[];
  selected_book_id: string | null;
};

export type BookImportStatus = {
  book_id: string;
  original_name?: string;
  chapter_count?: number;
  status: "splitting" | "awaiting_info" | "ready_for_embedding" | "pending" | "loading_model" | "encoding" | "writing" | "completed" | "failed";
  processed: number;
  total: number;
  message: string;
  error: string | null;
  info?: string;
};

// 前端运行期间使用的状态类型

export type ToolStatus = "running" | "completed" | "error";

export type ToolCall = {
  id: string;
  name: string;
  arguments: unknown;
  result?: ToolResult;
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

export type FrontendConversation = {
  id: string;
  title: string;
  messages: TimelineItem[];
  draft: string;
  error: string;
};

export type BookWorkspace = {
  bookId: string;
  conversations: FrontendConversation[];
  activeConversationId: string;
};

export type BookImporterTarget = {
  bookId?: string;
};

export type RunningRequest = {
  bookId: string;
  conversationId: string;
};

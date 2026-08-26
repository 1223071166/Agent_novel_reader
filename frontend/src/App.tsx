import { useState } from "react";
import { streamChat } from "./api";
//npm --prefix frontend run dev
type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: ToolCall[];
};

type ToolCall = {
  id: string;
  name: string;
  arguments: unknown;
  result?: unknown;
  status: "running" | "completed" | "error";
};

type Conversation = {
  id: string;
  messages: Message[];
  deleted?: boolean;
};

const makeConversation = (): Conversation => ({
  id: crypto.randomUUID(),
  messages: [],
});

const toolDisplayName = (name: string, args: unknown) => {
  const argumentsObject = args && typeof args === "object"
    ? args as Record<string, unknown>
    : {};
  const chapterId = argumentsObject.chapter_id;
  const keyword = argumentsObject.keyword;
  const query = argumentsObject.query;

  if (name === "get_chapter_list") return "读取章节目录";
  if (name === "get_chapter" && chapterId !== undefined) return `阅读第 ${chapterId} 章`;
  if (name === "search_keyword" && keyword !== undefined) return `关键词全文搜索：${keyword}`;
  if (name === "search_keyword_in_chapter" && chapterId !== undefined && keyword !== undefined) {
    return `第 ${chapterId} 章关键词搜索：${keyword}`;
  }
  if (name === "semantic_search" && query !== undefined) return `模糊搜索：${query}`;
  if (name === "get_summary") {
    const levelNames: Record<string, string> = { mid: "中段", big: "大段", whole: "全书" };
    const level = typeof argumentsObject.level === "string"
      ? levelNames[argumentsObject.level] ?? argumentsObject.level
      : "剧情";
    return argumentsObject.start !== undefined
      ? `读取${level}总结（第 ${argumentsObject.start} 章起）`
      : `读取${level}总结`;
  }
  return name === "" ? "执行工具" : name;
};

const formatToolValue = (value: unknown) => {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? "";
};

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([makeConversation()]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const activeConversation = conversations[activeIndex];

  const updateConversation = (index: number, update: (conversation: Conversation) => Conversation) => {
    setConversations((previous) => previous.map((conversation, i) => (
      i === index ? update(conversation) : conversation
    )));
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading || !activeConversation || activeConversation.deleted) return;

    const conversationIndex = activeIndex;
    const conversationId = activeConversation.id;
    const assistantId = crypto.randomUUID();
    updateConversation(conversationIndex, (conversation) => ({
        ...conversation,
        messages: [
          ...conversation.messages,
          { id: crypto.randomUUID(), role: "user", content: text },
        { id: assistantId, role: "assistant", content: "", tools: [] },
      ],
    }));
    setInput("");
    setLoading(true);
    setError("");

    try {
      await streamChat(conversationId, text, ({ event, data }) => {
        if (event === "token") {
          updateConversation(conversationIndex, (conversation) => ({
            ...conversation,
            messages: conversation.messages.map((message) => (
              message.id === assistantId
                ? { ...message, content: `${message.content}${String(data.content ?? "")}` }
                : message
            )),
          }));
        } else if (event === "tool_start") {
          const tool: ToolCall = {
            id: String(data.tool_call_id ?? crypto.randomUUID()),
            name: String(data.name ?? "unknown"),
            arguments: data.arguments ?? {},
            status: "running",
          };
          updateConversation(conversationIndex, (conversation) => ({
            ...conversation,
            messages: conversation.messages.map((message) => (
              message.id === assistantId
                ? { ...message, tools: [...(message.tools ?? []), tool] }
                : message
            )),
          }));
        } else if (event === "tool_result") {
          const toolId = String(data.tool_call_id ?? "");
          updateConversation(conversationIndex, (conversation) => ({
            ...conversation,
            messages: conversation.messages.map((message) => {
              if (message.id !== assistantId) return message;
              const existingTools = message.tools ?? [];
              const found = existingTools.some((tool) => tool.id === toolId);
              const tools = found
                ? existingTools.map((tool) => tool.id === toolId
                  ? {
                    ...tool,
                    result: data.result,
                    status: data.error ? "error" as const : "completed" as const,
                  }
                  : tool)
                : [...existingTools, {
                  id: toolId || crypto.randomUUID(),
                  name: String(data.name ?? "unknown"),
                  arguments: data.arguments ?? {},
                  result: data.result,
                  status: data.error ? "error" as const : "completed" as const,
                }];
              return { ...message, tools };
            }),
          }));
        } else if (event === "error") {
          throw new Error(String(data.message ?? "聊天请求失败"));
        }
      });
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "聊天请求失败";
      setError(message);
      updateConversation(conversationIndex, (conversation) => ({
        ...conversation,
        messages: conversation.messages.filter((item) => item.id !== assistantId),
      }));
    } finally {
      setLoading(false);
    }
  };

  const createConversation = () => {
    setConversations((previous) => [...previous, makeConversation()]);
    setActiveIndex(conversations.length);
    setInput("");
    setError("");
  };

  const deleteConversation = (index: number) => {
    updateConversation(index, (conversation) => ({ ...conversation, deleted: true }));
    if (index === activeIndex) setError("");
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="new-chat" onClick={createConversation}>
          <span>＋</span>
          新建聊天
        </button>

        <div className="conversation-list">
          {conversations.map((conversation, index) => (
            !conversation.deleted && (
              <div
                key={conversation.id}
                className={`conversation ${index === activeIndex ? "active" : ""}`}
                onClick={() => setActiveIndex(index)}
              >
                <span>💬</span>
                <span>对话 {index + 1}</span>
                <button
                  className="delete-chat"
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteConversation(index);
                  }}
                >
                  ×
                </button>
              </div>
            )
          ))}
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-item">⚙ 设置</div>
          <div className="sidebar-item">👤 用户</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span className="model-name">AgentReader</span>
          <span className="model-arrow">⌄</span>
        </header>

        <section className="chat">
          {!activeConversation || activeConversation.deleted ? (
            <div className="empty-state"><h1>这个对话已删除</h1></div>
          ) : activeConversation.messages.length === 0 ? (
            <div className="empty-state">
              <div className="logo">✦</div>
              <h1>有什么可以帮忙的？</h1>
              <p>输入一条消息，开始你的对话。</p>
            </div>
          ) : (
            <div className="messages">
              {activeConversation.messages.map((message) => (
                <div key={message.id} className={`message-row ${message.role}`}>
                  <div className="avatar">{message.role === "user" ? "你" : "✦"}</div>
                  <div className="message-content">
                    {message.role === "assistant" && message.tools?.map((tool) => (
                      <details className={`tool-card ${tool.status}`} key={tool.id}>
                        <summary>
                          <span className="tool-card-title">{toolDisplayName(tool.name, tool.arguments)}</span>
                        </summary>
                        <div className="tool-card-body">
                          <div className="tool-field">
                            <span>参数</span>
                            <pre>{formatToolValue(tool.arguments)}</pre>
                          </div>
                          {tool.result !== undefined && (
                            <div className="tool-field">
                              <span>结果</span>
                              <pre>{formatToolValue(tool.result)}</pre>
                            </div>
                          )}
                        </div>
                      </details>
                    ))}
                    {message.content || (loading ? "" : "未收到回复")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="input-area">
          {error && <div className="input-error">{error}</div>}
          <form className="input-box" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="发送消息"
              rows={1}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
            />
            <button className="send-button" type="submit" disabled={!input.trim() || loading || !activeConversation || !!activeConversation.deleted}>↑</button>
          </form>
          <div className="input-hint">回答来自小说内容检索，请检查重要信息。</div>
        </div>
      </main>
    </div>
  );
}

export default App;

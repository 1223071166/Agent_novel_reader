import { useState } from "react";
import { streamChat } from "./api";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
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

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([makeConversation()]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState("");
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
        { id: assistantId, role: "assistant", content: "" },
      ],
    }));
    setInput("");
    setLoading(true);
    setError("");
    setActivity("正在思考...");

    try {
      await streamChat(conversationId, text, ({ event, data }) => {
        if (event === "token") {
          setActivity("");
          updateConversation(conversationIndex, (conversation) => ({
            ...conversation,
            messages: conversation.messages.map((message) => (
              message.id === assistantId
                ? { ...message, content: `${message.content}${String(data.content ?? "")}` }
                : message
            )),
          }));
        } else if (event === "tool_start") {
          setActivity(`正在使用 ${String(data.name ?? "工具")}...`);
        } else if (event === "tool_result") {
          setActivity("正在整理检索结果...");
        } else if (event === "error") {
          throw new Error(String(data.message ?? "聊天请求失败"));
        } else if (event === "done") {
          setActivity("");
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
      setActivity("");
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
                  <div className="message-content">{message.content || (loading ? "" : "未收到回复")}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="input-area">
          {activity && <div className="input-status">{activity}</div>}
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

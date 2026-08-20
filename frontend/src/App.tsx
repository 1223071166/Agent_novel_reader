import React,{ useState } from "react";

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
};

const initialMessages: Message[] = [];

function App() {
  const [mindex,setMindex] = useState(0);
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sendMessage = () => {

    const text = input.trim();
    if (!text || loading) return;

    const userMessage: Message = {
      id: Date.now(),
      role: "user",
      content: text,
    };

    setMessages((prev) => [...prev, userMessage]);

    setInput("");
    setLoading(true);

    setTimeout(() => {
      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: "assistant",
        content: `这是一个假的回复。我收到了你的消息：“${text}”`,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setLoading(false);
    }, 1000);
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="new-chat" onClick={() => setMessages([])}>
          <span>＋</span>
          新建聊天
        </button>

        <div className="conversation-list">
          {messages.length > 0 && (
            <div className="conversation active">
              <span>💬</span>
              当前对话
            </div>
          )}
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-item">⚙ 设置</div>
          <div className="sidebar-item">👤 用户</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span className="model-name">ChatGPT</span>
          <span className="model-arrow">⌄</span>
        </header>

        <section className="chat">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="logo">✦</div>
              <h1>有什么可以帮忙的？</h1>
              <p>输入一条消息，开始你的对话。</p>
            </div>
          ) : (
            <div className="messages">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`message-row ${message.role}`}
                >
                  <div className="avatar">
                    {message.role === "user" ? "你" : "✦"}
                  </div>
                  <div className="message-content">{message.content}</div>
                </div>
              ))}

              {loading && (
                <div className="message-row assistant">
                  <div className="avatar">✦</div>
                  <div className="message-content loading">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <div className="input-area">
          <form className="input-box" onSubmit={sendMessage}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="发送消息"
              rows={1}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage();
                }
              }}
            />
            <button
              className="send-button"
              type="submit"
              disabled={!input.trim() || loading}
            >
              ↑
            </button>
          </form>
          <div className="input-hint">
            ChatGPT 可能犯错。请检查重要信息。
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
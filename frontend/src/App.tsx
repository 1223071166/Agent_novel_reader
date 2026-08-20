import React, { useState } from "react";

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
};

const initialMessages: (Message[] | null)[] = [[]];

function App() {
  const [mindex, setMindex] = useState(0);
  const [messages, setMessages] = useState<(Message[] | null)[]>(initialMessages);
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

    setMessages((prev) => {
      const newMessages = [...prev];
      newMessages[mindex] = [...(newMessages[mindex] ?? []), userMessage];
      return newMessages;
    });

    setInput("");
    setLoading(true);

    setTimeout(() => {
      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: "assistant",
        content: `这是一个假的回复。我收到了你的消息：“${text}”`,
      };

      setMessages((prev) => {
        const newMessages = [...prev];
        newMessages[mindex] = [...(newMessages[mindex] ?? []), assistantMessage];
        return newMessages;
      });

      setLoading(false);
    }, 1000);
  };

  const newChat = () => {
    const newIndex = messages.length;
    setMessages((prev) => [...prev, []]);
    setMindex(newIndex);
    setInput("");
    setLoading(false);
  };

  const deleteChat = (index: number) => {
    setMessages((prev) => {
      const newMessages = [...prev];
      newMessages[index] = null;
      return newMessages;
    });

    if (index === mindex) {
      setInput("");
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="new-chat" onClick={newChat}>
          <span>＋</span>
          新建聊天
        </button>

        <div className="conversation-list">
          {messages.map((conversation, index) =>
            conversation !== null ? (
              <div
                key={index}
                className={`conversation ${index === mindex ? "active" : ""}`}
                onClick={() => setMindex(index)}
              >
                <span>💬</span>
                <span>对话 {index + 1}</span>

                <button
                  className="delete-chat"
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteChat(index);
                  }}
                >
                  ×
                </button>
              </div>
            ) : null
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
          {messages[mindex]?.length === 0 ? (
            <div className="empty-state">
              <div className="logo">✦</div>
              <h1>有什么可以帮忙的？</h1>
              <p>输入一条消息，开始你的对话。</p>
            </div>
          ) : messages[mindex] ? (
            <div className="messages">
              {messages[mindex].map((message) => (
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
          ) : (
            <div className="empty-state">
              <div className="logo">✦</div>
              <h1>这个对话已删除</h1>
              <p>点击“新建聊天”开始新的对话。</p>
            </div>
          )}
        </section>

        <div className="input-area">
          <form
            className="input-box"
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
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
              disabled={!input.trim() || loading || messages[mindex] === null}
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
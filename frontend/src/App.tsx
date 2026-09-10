import { useState, useEffect } from "react";
import { deleteConversation as deleteConversationApi, loadConversations, streamChat,cancelStream } from "./api";
import {
  applyChatEvent,
  appendUserItem,
  timelineFromConversation,
} from "./chatTimeline";
import type { TimelineItem } from "./chatTimeline";
//npm --prefix frontend run dev
type Conversation = {
  id: string;
  messages: TimelineItem[];
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
  if (Array.isArray(value)) return value.map(String).join("\n\n");
  return JSON.stringify(value, null, 2) ?? "";
};

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([makeConversation()]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void loadConversations()
      .then((savedConversations) => {
        if (cancelled) return;
        setConversations(savedConversations.length > 0
          ? savedConversations.map((conversation) => ({
              id: conversation.id,
              messages: timelineFromConversation(conversation),
            }))
          : [makeConversation()]);
        setActiveIndex(0);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : "加载历史会话失败");
        }
      });
    return () => { cancelled = true; };
  }, []);

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
    updateConversation(conversationIndex, (conversation) => ({
        ...conversation,
        messages: appendUserItem(conversation.messages, text),
    }));
    setInput("");
    setLoading(true);
    setError("");
    try {
      await streamChat(conversationId, text, ({ event, data }) => {
        if (event === "error") {
          throw new Error(String(data.message ?? "聊天请求失败"));
        }
        updateConversation(conversationIndex, (conversation) => ({
          ...conversation,
          messages: applyChatEvent(conversation.messages, { event, data }),
        }));
      });
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "聊天请求失败";
      setError(message);
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

  const deleteConversation = async (index: number) => {
    const conversation = conversations[index];
    if (!conversation) return;

    try {
      await deleteConversationApi(conversation.id);
      updateConversation(index, (currentConversation) => ({ ...currentConversation, deleted: true }));
      if (index === activeIndex) {
        const nextIndex = conversations.findIndex(
          (item, itemIndex) => itemIndex !== index && !item.deleted,
        );
        setActiveIndex(nextIndex);
        setError("");
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除会话失败");
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">✦</div>
          <div>
            <div className="brand-name">AgentReader</div>
            <div className="brand-caption">小说阅读助手</div>
          </div>
        </div>

        <button className="new-chat" onClick={createConversation}>
          <span className="new-chat-icon">＋</span>
          <span>新建聊天</span>
        </button>

        <div className="conversation-list">
          <div className="sidebar-section-label">最近对话</div>
          {conversations.map((conversation, index) => (
            !conversation.deleted && (
              <div
                key={conversation.id}
                className={`conversation ${index === activeIndex ? "active" : ""}`}
                onClick={() => setActiveIndex(index)}
              >
                <span className="conversation-icon">✧</span>
                <span className="conversation-name">对话 {index + 1}</span>
                <button
                  className="delete-chat"
                  disabled={loading && index === activeIndex}
                  aria-label={`删除对话 ${index + 1}`}
                  title="删除对话"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteConversation(index);
                  }}
                >
                  ×
                </button>
              </div>
            )
          ))}
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-item"><span>⚙</span> 设置</div>
          <div className="sidebar-item"><span>◉</span> 本地模式</div>
        </div>
      </aside>

      <main className="main">
        <section className="chat">
          {!activeConversation || activeConversation.deleted ? (
            <div className="empty-state"><h1>这个对话已删除</h1></div>
          ) : activeConversation.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-logo"><span>✦</span></div>
              <div className="empty-eyebrow">AgentReader</div>
              <h1>有什么可以帮忙的？</h1>
              <p>从小说内容中检索细节，开始一段新的探索。</p>
            </div>
          ) : (
            <div className="messages">
              {activeConversation.messages.map((item) => (
                <div key={item.id} className={`message-row ${item.type}`}>
                  <div className="avatar">{item.type === "user" ? "你" : "✦"}</div>
                  <div className="message-content">
                    {item.type === "tool" && (
                      <details className={`tool-card ${item.tool.status}`}>
                        <summary>
                          <span className="tool-card-title">{toolDisplayName(item.tool.name, item.tool.arguments)}</span>
                        </summary>
                        <div className="tool-card-body">
                          {item.tool.result !== undefined && (
                            <div className="tool-field">
                              <pre>{formatToolValue(item.tool.result)}</pre>
                            </div>
                          )}
                        </div>
                      </details>
                    )}
                    {(item.type === "user" || item.type === "assistant") && item.content}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="input-area">
          {error && <div className="input-error">{error}</div>}
          <form className="input-box" onSubmit={(event) => {
             event.preventDefault();
             if(loading){
                cancelStream(activeConversation.id);
             }
                
             else
              void sendMessage(); 
             }}>
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
            <button className="send-button" type="submit" disabled={(!input.trim()&&!loading) || !activeConversation || !!activeConversation.deleted}>
              {loading ? "■" : "↑"}
            </button>
          </form>
          <div className="input-hint"><span>✦</span> 回答来自小说内容检索，请检查重要信息。</div>
        </div>
      </main>
    </div>
  );
}

export default App;

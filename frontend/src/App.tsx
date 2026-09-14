import { useState, useEffect } from "react";
import { cancelStream, deleteConversation as deleteConversationApi, loadBookSelection, loadConversations, streamChat } from "./api";
import type { ConversationResponse } from "./api";
import {
  applyChatEvent,
  appendUserItem,
  timelineFromConversation,
} from "./chatTimeline";
import type { TimelineItem } from "./chatTimeline";
import BookImporter from "./BookImporter";
//npm --prefix frontend run dev
type ConversationState = {
  id: string;
  title: string;
  messages: TimelineItem[];
};

type BookWorkspace = {
  bookId: string;
  conversations: ConversationState[];
  activeConversationId: string;
};

type BookImporterTarget = {
  bookId?: string;
};

const makeConversation = (): ConversationState => ({
  id: crypto.randomUUID(),
  title: "新对话",
  messages: [],
});

const conversationFromResponse = (conversation: ConversationResponse): ConversationState => ({
  id: conversation.id,
  title: conversation.title,
  messages: timelineFromConversation(conversation),
});

const makeWorkspace = (
  bookId: string,
  conversationResponses: ConversationResponse[],
): BookWorkspace => {
  const conversations = conversationResponses.length > 0
    ? conversationResponses.map(conversationFromResponse)
    : [makeConversation()];
  return {
    bookId,
    conversations,
    activeConversationId: conversations[0].id,
  };
};

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
  const [books, setBooks] = useState<string[]>([]);
  const [importingBookIds, setImportingBookIds] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState<BookWorkspace | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [switchingBook, setSwitchingBook] = useState(false);
  const [bookImporterTarget, setBookImporterTarget] = useState<BookImporterTarget | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void loadBookSelection()
      .then(async (selection) => {
        const savedConversations = selection.selected_book_id
          ? await loadConversations(selection.selected_book_id)
          : [];
        return { selection, savedConversations };
      })
      .then(({ selection, savedConversations }) => {
        if (cancelled) return;
        setBooks(selection.books);
        setImportingBookIds(selection.importing_book_ids ?? []);
        setWorkspace(selection.selected_book_id
          ? makeWorkspace(selection.selected_book_id, savedConversations)
          : null);
        setError(selection.books.length === 0 ? "还没有书籍，可以先导入一本小说" : "");
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : "加载历史会话失败");
        }
      });
    return () => { cancelled = true; };
  }, []);

  const bookId = workspace?.bookId ?? null;
  const conversations = workspace?.conversations ?? [];
  const activeConversation = workspace?.conversations.find(
    (conversation) => conversation.id === workspace.activeConversationId,
  );

  const updateConversation = (
    targetBookId: string,
    conversationId: string,
    update: (conversation: ConversationState) => ConversationState,
  ) => {
    setWorkspace((previous) => {
      if (!previous || previous.bookId !== targetBookId) return previous;
      return {
        ...previous,
        conversations: previous.conversations.map((conversation) => (
          conversation.id === conversationId ? update(conversation) : conversation
        )),
      };
    });
  };

  const switchBook = async (nextBookId: string) => {
    if (nextBookId === workspace?.bookId || loading || switchingBook) return;

    setSwitchingBook(true);
    setError("");
    try {
      const savedConversations = await loadConversations(nextBookId);
      setWorkspace(makeWorkspace(nextBookId, savedConversations));
      setInput("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "切换书籍失败");
    } finally {
      setSwitchingBook(false);
    }
  };

  const finishBookImport = async (importedBookId: string) => {
    const selection = await loadBookSelection();
    setBooks(selection.books);
    setImportingBookIds(selection.importing_book_ids ?? []);
    await switchBook(importedBookId);
    setBookImporterTarget(null);
  };

  const registerBookImport = (importedBookId: string) => {
    setBooks((previous) => previous.includes(importedBookId)
      ? previous
      : [...previous, importedBookId].sort());
    setImportingBookIds((previous) => previous.includes(importedBookId)
      ? previous
      : [...previous, importedBookId].sort());
  };

  const finishDiscardBookImport = async () => {
    const selection = await loadBookSelection();
    setBooks(selection.books);
    setImportingBookIds(selection.importing_book_ids ?? []);
    setBookImporterTarget(null);
  };

  const selectBook = (nextBookId: string) => {
    if (importingBookIds.includes(nextBookId)) {
      setBookImporterTarget({ bookId: nextBookId });
      return;
    }
    void switchBook(nextBookId);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading || !bookId || !activeConversation) return;

    const requestBookId = bookId;
    const conversationId = activeConversation.id;
    updateConversation(requestBookId, conversationId, (conversation) => ({
        ...conversation,
        messages: appendUserItem(conversation.messages, text),
    }));
    setInput("");
    setLoading(true);
    setError("");
    try {
      await streamChat(requestBookId, conversationId, text, ({ event, data }) => {
        if (event === "error") {
          throw new Error(String(data.message ?? "聊天请求失败"));
        }
        updateConversation(requestBookId, conversationId, (conversation) => ({
          ...conversation,
          title: event === "message_start" && typeof data.title === "string"
            ? data.title
            : conversation.title,
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
    if (!workspace || switchingBook) return;
    const conversation = makeConversation();
    setWorkspace((previous) => previous ? {
      ...previous,
      conversations: [...previous.conversations, conversation],
      activeConversationId: conversation.id,
    } : previous);
    setInput("");
    setError("");
  };

  const deleteConversation = async (conversationId: string) => {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!bookId || !conversation || switchingBook) return;

    const requestBookId = bookId;

    try {
      await deleteConversationApi(requestBookId, conversation.id);
      setWorkspace((previous) => {
        if (!previous || previous.bookId !== requestBookId) return previous;

        const deletedIndex = previous.conversations.findIndex((item) => item.id === conversationId);
        const remaining = previous.conversations.filter((item) => item.id !== conversationId);
        if (remaining.length === 0) {
          const replacement = makeConversation();
          return {
            ...previous,
            conversations: [replacement],
            activeConversationId: replacement.id,
          };
        }

        const activeConversationId = previous.activeConversationId === conversationId
          ? remaining[Math.min(deletedIndex, remaining.length - 1)].id
          : previous.activeConversationId;
        return { ...previous, conversations: remaining, activeConversationId };
      });
      if (activeConversation?.id === conversationId) {
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

        <button className="new-chat" onClick={createConversation} disabled={!workspace || loading || switchingBook}>
          <span className="new-chat-icon">＋</span>
          <span>新建聊天</span>
        </button>

        <button
          className="import-book"
          type="button"
          disabled={loading || switchingBook}
          onClick={() => setBookImporterTarget({})}
        >
          <span className="new-chat-icon">⇧</span>
          <span>导入书籍</span>
        </button>

        <div className="conversation-list">
          <div className="sidebar-section-label">最近对话</div>
          {conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`conversation ${conversation.id === activeConversation?.id ? "active" : ""}`}
                onClick={() => setWorkspace((previous) => previous ? {
                  ...previous,
                  activeConversationId: conversation.id,
                } : previous)}
              >
                <span className="conversation-icon">✧</span>
                <span className="conversation-name">{conversation.title}</span>
                <button
                  className="delete-chat"
                  disabled={switchingBook || (loading && conversation.id === activeConversation?.id)}
                  aria-label={`删除对话：${conversation.title}`}
                  title="删除对话"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteConversation(conversation.id);
                  }}
                >
                  ×
                </button>
              </div>
          ))}
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-item"><span>⚙</span> 设置</div>
          <div className="sidebar-item"><span>◉</span> 本地模式</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <label className="book-selector">
            <span>当前书籍</span>
            <select
              aria-label="切换书籍"
              value={bookId ?? ""}
              disabled={books.length === 0 || loading || switchingBook}
              onChange={(event) => selectBook(event.target.value)}
            >
              {!bookId && <option value="" disabled>选择书籍</option>}
              {books.map((book) => (
                <option key={book} value={book}>
                  {book}{importingBookIds.includes(book) ? "（未完成）" : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="topbar-status">
            <span />
            {switchingBook ? "正在切换" : "本地模式"}
          </div>
        </header>
        <section className="chat">
          {!activeConversation || activeConversation.messages.length === 0 ? (
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
                if (bookId && activeConversation) {
                  void cancelStream(bookId, activeConversation.id).catch((requestError) => {
                    setError(requestError instanceof Error ? requestError.message : "取消请求失败");
                  });
                }
             }
                
             else
              void sendMessage(); 
             }}>
            <textarea
              value={input}
              disabled={!workspace || switchingBook}
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
            <button className="send-button" type="submit" disabled={switchingBook || ((!input.trim()&&!loading) || !activeConversation)}>
              {loading ? "■" : "↑"}
            </button>
          </form>
          <div className="input-hint"><span>✦</span> 回答来自小说内容检索，请检查重要信息。</div>
        </div>
      </main>
      {bookImporterTarget && (
        <BookImporter
          key={bookImporterTarget.bookId ?? "new-import"}
          initialBookId={bookImporterTarget.bookId}
          onClose={() => setBookImporterTarget(null)}
          onImportCreated={registerBookImport}
          onImported={finishBookImport}
          onDiscarded={finishDiscardBookImport}
        />
      )}
    </div>
  );
}

export default App;

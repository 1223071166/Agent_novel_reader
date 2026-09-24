import { useState, useEffect } from "react";
import { cancelStream, deleteConversation as deleteConversationApi, loadBookImport, loadBookSelection, loadConversations, saveBookSelection, streamChat } from "./api";
import {
  addTokenUsage,
  applyChatEvent,
  appendUserItem,
  removeUnsentMessage,
} from "./chatTimeline";
import BookImporter from "./BookImporter";
import SettingsDialog from "./SettingsDialog";
import SummaryManager from "./SummaryManager";
import SpoilerControls from "./SpoilerControls";
import {
  bookDisplayName,
  makeConversation,
  makeWorkspace,
  updateConversationInWorkspace,
} from "./workspaceState";
import type {
  BookImporterTarget,
  BookImportStatus,
  BookWorkspace,
  ChatEvent,
  RunningRequest,
  ToolResult,
} from "./types";

const embeddingRunningStatuses = new Set<BookImportStatus["status"]>([
  "pending",
  "loading_model",
  "encoding",
  "writing",
]);

const toolDisplayName = (name: string, args: unknown, result?: ToolResult) => {
  const argumentsObject = args && typeof args === "object"
    ? args as Record<string, unknown>
    : {};
  const chapterId = argumentsObject.chapter_id;
  const keyword = argumentsObject.keyword;
  const query = argumentsObject.query;

  if (name === "get_chapter_list") {
    const startChapter = argumentsObject.start_chapter;
    const endChapter = argumentsObject.end_chapter;
    if (typeof query === "string" && query.trim()) {
      if (typeof startChapter === "number" && typeof endChapter === "number") {
        return `在第 ${startChapter}-${endChapter} 章查找标题：${query}`;
      }
      if (typeof startChapter === "number") return `在第 ${startChapter} 章后查找标题：${query}`;
      if (typeof endChapter === "number") return `在前 ${endChapter} 章查找标题：${query}`;
      return `查找章节标题：${query}`;
    }
    if (typeof startChapter === "number" && typeof endChapter === "number") {
      return `查看第 ${startChapter}-${endChapter} 章目录`;
    }
    if (typeof startChapter === "number") return `查看第 ${startChapter} 章后的目录`;
    if (typeof endChapter === "number") return `查看前 ${endChapter} 章目录`;
    return "读取章节目录";
  }
  if (name === "get_chapter" && chapterId !== undefined) return `阅读第 ${chapterId} 章`;
  if (name === "get_chapters" && Array.isArray(argumentsObject.chapter_ids)) {
    return `阅读第 ${argumentsObject.chapter_ids.map(String).join("、")} 章`;
  }
  if (name === "search_keyword" && keyword !== undefined) {
    const startChapter = argumentsObject.start_chapter;
    const endChapter = argumentsObject.end_chapter;
    if (typeof startChapter === "number" && typeof endChapter === "number") {
      return `第 ${startChapter}-${endChapter} 章关键词搜索：${keyword}`;
    }
    if (typeof startChapter === "number") return `第 ${startChapter} 章后关键词搜索：${keyword}`;
    if (typeof endChapter === "number") return `前 ${endChapter} 章关键词搜索：${keyword}`;
    return `关键词全文搜索：${keyword}`;
  }
  if (name === "semantic_search" && query !== undefined) {
    const startChapter = argumentsObject.start_chapter;
    const endChapter = argumentsObject.end_chapter;
    if (typeof startChapter === "number" && typeof endChapter === "number") {
      return `第 ${startChapter}-${endChapter} 章模糊搜索：${query}`;
    }
    if (typeof startChapter === "number") return `第 ${startChapter} 章后模糊搜索：${query}`;
    if (typeof endChapter === "number") return `前 ${endChapter} 章模糊搜索：${query}`;
    return `模糊搜索：${query}`;
  }
  if (name === "get_summary") {
    const level = argumentsObject.level;
    if (level === "whole") return "查看全书总结";

    const start = typeof argumentsObject.start === "number" ? argumentsObject.start : null;
    const returnedEnd = result?.data.kind === "summary" && typeof result.data.end === "number"
      ? result.data.end
      : null;
    const blockSize = level === "mid" ? 20 : level === "big" ? 100 : null;
    if (start !== null && blockSize !== null) {
      const end = returnedEnd ?? start + blockSize - 1;
      return `查看第 ${start}-${end} 章总结`;
    }
    return "查看剧情总结";
  }
  return name === "" ? "执行工具" : name;
};

function App() {
  const [books, setBooks] = useState<string[]>([]);
  const [bookNames, setBookNames] = useState<Record<string, string>>({});
  const [importingBookIds, setImportingBookIds] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState<BookWorkspace | null>(null);
  const [runningRequests, setRunningRequests] = useState<RunningRequest[]>([]);
  const [switchingBook, setSwitchingBook] = useState(false);
  const [bookImporterTarget, setBookImporterTarget] = useState<BookImporterTarget | null>(null);
  const [embeddingStatus, setEmbeddingStatus] = useState<BookImportStatus | null>(null);
  const [summaryManagerBookId, setSummaryManagerBookId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [appError, setAppError] = useState("");
  const bookId = workspace?.bookId ?? null;

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
        setBookNames(selection.book_names ?? {});
        setImportingBookIds(selection.importing_book_ids);
        setWorkspace(selection.selected_book_id
          ? makeWorkspace(selection.selected_book_id, savedConversations)
          : null);
        setAppError(selection.books.length === 0 ? "还没有书籍，可以先导入一本小说" : "");
      })
      .catch((requestError) => {
        if (!cancelled) {
          setAppError(requestError instanceof Error ? requestError.message : "加载历史会话失败");
        }
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!bookId || !importingBookIds.includes(bookId)) {
      setEmbeddingStatus(null);
      return;
    }

    let cancelled = false;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const status = await loadBookImport(bookId);
        if (cancelled) return;
        if (status.status === "completed") {
          setImportingBookIds((previous) => previous.filter((id) => id !== bookId));
          setEmbeddingStatus(null);
          return;
        }
        setEmbeddingStatus(status);
        if (embeddingRunningStatuses.has(status.status)) {
          timer = window.setTimeout(() => void refresh(), 1000);
        }
      } catch (requestError) {
        if (!cancelled) {
          setAppError(requestError instanceof Error ? requestError.message : "读取向量化进度失败");
        }
      }
    };
    void refresh();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [bookId, importingBookIds, bookImporterTarget]);

  const conversations = workspace?.conversations ?? [];
  const activeConversation = workspace?.conversations.find(
    (conversation) => conversation.id === workspace.activeConversationId,
  );
  const input = activeConversation?.draft ?? "";
  const isConversationRunning = (targetBookId: string, conversationId: string) => (
    runningRequests.some((request) => (
      request.bookId === targetBookId && request.conversationId === conversationId
    ))
  );
  const activeRunningRequest = bookId && activeConversation
    ? runningRequests.find((request) => (
      request.bookId === bookId && request.conversationId === activeConversation.id
    ))
    : undefined;
  const activeConversationRunning = Boolean(activeRunningRequest);
  const activeConversationStopping = activeRunningRequest?.stopping ?? false;
  const hasRunningRequests = runningRequests.length > 0;
  const visibleMessages = activeConversation?.messages.filter((item) => (
    item.type !== "assistant" || item.content !== ""
  )) ?? [];

  const addUserMessageToConversation = (
    targetBookId: string,
    conversationId: string,
    content: string,
  ) => {
    setWorkspace((previous) => updateConversationInWorkspace(
      previous,
      targetBookId,
      conversationId,
      (conversation) => ({
        ...conversation,
        messages: appendUserItem(conversation.messages, content),
        draft: "",
        error: "",
        usage: null,
      }),
    ));
  };

  const applyEventToConversation = (
    targetBookId: string,
    conversationId: string,
    chatEvent: ChatEvent,
  ) => {
    setWorkspace((previous) => updateConversationInWorkspace(
      previous,
      targetBookId,
      conversationId,
      (conversation) => ({
        ...conversation,
        title: chatEvent.event === "message_start" && typeof chatEvent.data.title === "string"
          ? chatEvent.data.title
          : conversation.title,
        messages: applyChatEvent(conversation.messages, chatEvent),
        usage: chatEvent.event === "usage"
          ? addTokenUsage(conversation.usage, chatEvent.data)
          : conversation.usage,
      }),
    ));
  };

  const setConversationError = (
    targetBookId: string,
    conversationId: string,
    error: string,
  ) => {
    setWorkspace((previous) => updateConversationInWorkspace(
      previous,
      targetBookId,
      conversationId,
      (conversation) => ({ ...conversation, error }),
    ));
  };

  const setConversationDraft = (
    targetBookId: string,
    conversationId: string,
    draft: string,
  ) => {
    setWorkspace((previous) => updateConversationInWorkspace(
      previous,
      targetBookId,
      conversationId,
      (conversation) => ({ ...conversation, draft }),
    ));
  };

  const switchBook = async (nextBookId: string) => {
    if (nextBookId === workspace?.bookId || hasRunningRequests || switchingBook) return;

    setSwitchingBook(true);
    setAppError("");
    try {
      const savedConversations = await loadConversations(nextBookId);
      await saveBookSelection(nextBookId);
      setWorkspace(makeWorkspace(nextBookId, savedConversations));
    } catch (requestError) {
      setAppError(requestError instanceof Error ? requestError.message : "切换书籍失败");
    } finally {
      setSwitchingBook(false);
    }
  };

  const finishBookImport = async (importedBookId: string) => {
    const selection = await loadBookSelection();
    setBooks(selection.books);
    setBookNames(selection.book_names ?? {});
    setImportingBookIds(selection.importing_book_ids);
    await switchBook(importedBookId);
    setBookImporterTarget(null);
  };

  const registerBookImport = (importedBookId: string, name: string) => {
    setBooks((previous) => previous.includes(importedBookId)
      ? previous
      : [...previous, importedBookId].sort());
    setImportingBookIds((previous) => previous.includes(importedBookId)
      ? previous
      : [...previous, importedBookId].sort());
    setBookNames((previous) => ({ ...previous, [importedBookId]: name }));
  };

  const updateBookName = (targetBookId: string, name: string) => {
    setBookNames((previous) => ({ ...previous, [targetBookId]: name }));
  };

  const finishDiscardBookImport = async () => {
    const selection = await loadBookSelection();
    setBooks(selection.books);
    setBookNames(selection.book_names ?? {});
    setImportingBookIds(selection.importing_book_ids);
    setBookImporterTarget(null);
  };

  const selectBook = async (nextBookId: string) => {
    if (importingBookIds.includes(nextBookId)) {
      try {
        const status = await loadBookImport(nextBookId);
        if (status.status === "splitting" || status.status === "awaiting_info") {
          setBookImporterTarget({ bookId: nextBookId });
          return;
        }
      } catch (requestError) {
        setAppError(requestError instanceof Error ? requestError.message : "读取导入进度失败");
        return;
      }
    }
    await switchBook(nextBookId);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || !bookId || !activeConversation) return;

    const requestBookId = bookId;
    const conversationId = activeConversation.id;
    if (isConversationRunning(requestBookId, conversationId)) return;

    addUserMessageToConversation(requestBookId, conversationId, text);
    setRunningRequests((previous) => [
      ...previous,
      { bookId: requestBookId, conversationId, stopping: false },
    ]);
    setAppError("");
    let messageStarted = false;
    let rejectedBeforeStart = false;
    try {
      await streamChat(requestBookId, conversationId, text, ({ event, data }) => {
        if (event === "error") {
          rejectedBeforeStart = !messageStarted;
          throw new Error(String(data.message ?? "聊天请求失败"));
        }
        if (event === "message_start") messageStarted = true;
        applyEventToConversation(requestBookId, conversationId, { event, data });
      });
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "聊天请求失败";
      setWorkspace((previous) => updateConversationInWorkspace(
        previous,
        requestBookId,
        conversationId,
        (conversation) => ({
          ...conversation,
          messages: rejectedBeforeStart
            ? removeUnsentMessage(conversation.messages, text)
            : conversation.messages,
          draft: rejectedBeforeStart ? text : conversation.draft,
          error: message,
        }),
      ));
    } finally {
      setRunningRequests((previous) => previous.filter((request) => (
        request.bookId !== requestBookId || request.conversationId !== conversationId
      )));
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
    setAppError("");
  };

  const deleteConversation = async (conversationId: string) => {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!bookId || !conversation || switchingBook) return;

    const requestBookId = bookId;
    if (isConversationRunning(requestBookId, conversationId)) return;

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
        setAppError("");
      }
    } catch (requestError) {
      setAppError(requestError instanceof Error ? requestError.message : "删除会话失败");
    }
  };

  const stopActiveConversation = () => {
    if (!bookId || !activeConversation || activeConversationStopping) return;

    const requestBookId = bookId;
    const conversationId = activeConversation.id;
    setRunningRequests((previous) => previous.map((request) => (
      request.bookId === requestBookId && request.conversationId === conversationId
        ? { ...request, stopping: true }
        : request
    )));
    void cancelStream(requestBookId, conversationId).catch((requestError) => {
      setRunningRequests((previous) => previous.map((request) => (
        request.bookId === requestBookId && request.conversationId === conversationId
          ? { ...request, stopping: false }
          : request
      )));
      const message = requestError instanceof Error ? requestError.message : "取消请求失败";
      setConversationError(requestBookId, conversationId, message);
    });
  };

  const submitCurrentConversation = () => {
    if (activeConversationRunning) {
      stopActiveConversation();
      return;
    }
    void sendMessage();
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

        <button className="new-chat" onClick={createConversation} disabled={!workspace || switchingBook}>
          <span className="new-chat-icon">＋</span>
          <span>新对话</span>
        </button>

        <button
          className="import-book"
          type="button"
          disabled={hasRunningRequests || switchingBook}
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
                  disabled={switchingBook || Boolean(bookId && isConversationRunning(bookId, conversation.id))}
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
          <button
            className="sidebar-item"
            type="button"
            disabled={hasRunningRequests}
            onClick={() => setSettingsOpen(true)}
          >
            <span>⚙</span> 设置
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-book-controls">
            <label className="book-selector">
              <span>当前书籍</span>
              <select
                aria-label="切换书籍"
                value={bookId ?? ""}
                disabled={books.length === 0 || hasRunningRequests || switchingBook}
                onChange={(event) => void selectBook(event.target.value)}
              >
                {!bookId && <option value="" disabled>选择书籍</option>}
                {books.map((book) => (
                  <option key={book} value={book}>
                    {bookDisplayName(book, bookNames)}
                  </option>
                ))}
              </select>
            </label>
            {embeddingStatus && (
              <div className="topbar-embedding">
                <button
                  className="topbar-embedding-label"
                  type="button"
                  title="查看向量化状态"
                  onClick={() => bookId && setBookImporterTarget({ bookId })}
                >
                  <span>{embeddingStatus.message}</span>
                  <span>{embeddingRunningStatuses.has(embeddingStatus.status)
                    ? embeddingStatus.total > 0
                      ? `${embeddingStatus.processed}/${embeddingStatus.total}`
                      : "准备中"
                    : "查看"}</span>
                </button>
                {embeddingRunningStatuses.has(embeddingStatus.status) && (
                  <div className="embedding-progress" aria-label={`向量化进度 ${embeddingStatus.processed}/${embeddingStatus.total}`}>
                    <div
                      className="embedding-progress-value"
                      style={{
                        width: `${embeddingStatus.total > 0
                          ? Math.round(embeddingStatus.processed / embeddingStatus.total * 100)
                          : 0}%`,
                      }}
                    />
                  </div>
                )}
              </div>
            )}
            <button
              className="summary-open"
              type="button"
              disabled={!bookId || switchingBook }
              onClick={() => bookId && setSummaryManagerBookId(bookId)}
            >
              总结管理
            </button>

            {bookId && (
              <SpoilerControls
                key={bookId}
                bookId={bookId}
                disabled={switchingBook}
              />
            )}
          </div>
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
            </div>
          ) : (
            <div className="messages">
              {visibleMessages.map((item, index, items) => {
                const showAvatar = item.type === "user"
                  || index === 0
                  || items[index - 1].type === "user";
                return (
                  <div
                    key={item.id}
                    className={`message-row ${item.type}${showAvatar ? " turn-start" : " continuation"}`}
                  >
                    {showAvatar
                      ? <div className="avatar">{item.type === "user" ? "你" : "✦"}</div>
                      : <div className="avatar-space" aria-hidden="true" />}
                    <div className="message-content">
                      {item.type === "tool" && (
                        <details className={`tool-card ${item.tool.status}`}>
                          <summary>
                            <span className="tool-card-title">
                              {toolDisplayName(item.tool.name, item.tool.arguments, item.tool.result)}
                            </span>
                          </summary>
                          <div className="tool-card-body">
                            {item.tool.result !== undefined && (
                              <div className="tool-field">
                                <pre>{item.tool.result.display}</pre>
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                      {(item.type === "user" || item.type === "assistant") && item.content}
                    </div>
                  </div>
                );
              })}
              {activeConversation.usage && (
                <div className="usage-row">
                  <div className="avatar-space" aria-hidden="true" />
                  <div>
                    本轮 Token：输入 {activeConversation.usage.input}
                    <span>·</span> 输出 {activeConversation.usage.output}
                    <span>·</span> 合计 {activeConversation.usage.total}
                    <span>·</span> 缓存命中 {activeConversation.usage.cached_input}
                    <span>·</span> 缓存未命中 {activeConversation.usage.cache_miss_input}
                    <span>·</span> 推理 {activeConversation.usage.reasoning}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <div className="input-area">
          {appError && <div className="input-error">{appError}</div>}
          {activeConversation?.error && (
            <div className="input-error">{activeConversation.error}</div>
          )}
          <form className="input-box" onSubmit={(event) => {
            event.preventDefault();
            submitCurrentConversation();
          }}>
            <textarea
              value={input}
              disabled={!workspace || switchingBook}
              onChange={(event) => {
                if (!bookId || !activeConversation) return;
                const draft = event.target.value;
                setConversationDraft(bookId, activeConversation.id, draft);
              }}
              placeholder="发送消息"
              rows={1}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <button
              className={`send-button${activeConversationStopping ? " stopping" : ""}`}
              type="submit"
              disabled={
                switchingBook
                || !activeConversation
                || activeConversationStopping
                || (!input.trim() && !activeConversationRunning)
              }
            >
              {activeConversationStopping ? "停止中…" : activeConversationRunning ? "■" : "↑"}
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
          onInfoSaved={updateBookName}
          onImported={finishBookImport}
          onDiscarded={finishDiscardBookImport}
        />
      )}
      {summaryManagerBookId && (
        <SummaryManager
          key={summaryManagerBookId}
          bookId={summaryManagerBookId}
          bookName={bookDisplayName(summaryManagerBookId, bookNames)}
          onClose={() => setSummaryManagerBookId(null)}
        />
      )}
      {settingsOpen && (
        <SettingsDialog
          onClose={() => setSettingsOpen(false)}
          onSaved={(showUsage) => {
            if (showUsage) return;
            setWorkspace((previous) => previous ? {
              ...previous,
              conversations: previous.conversations.map((conversation) => ({
                ...conversation,
                usage: null,
              })),
            } : previous);
          }}
        />
      )}
    </div>
  );
}

export default App;

import { useEffect, useState } from "react";

import { deleteBook, loadBookSelection } from "./api";
import type { BookSelection } from "./types";

type BookDeleteDialogProps = {
  onClose: () => void;
  onDeleted: (bookId: string, selection: BookSelection) => void;
};

export default function BookDeleteDialog({ onClose, onDeleted }: BookDeleteDialogProps) {
  const [selection, setSelection] = useState<BookSelection | null>(null);
  const [bookId, setBookId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void loadBookSelection()
      .then((loaded) => {
        if (!active) return;
        const available = loaded.books.filter((id) => !loaded.importing_book_ids.includes(id));
        setSelection(loaded);
        setBookId(available.includes(loaded.selected_book_id ?? "")
          ? loaded.selected_book_id ?? ""
          : available[0] ?? "");
      })
      .catch((requestError) => {
        if (active) setError(requestError instanceof Error ? requestError.message : "读取书籍列表失败");
      });
    return () => { active = false; };
  }, []);

  const availableBooks = selection?.books.filter(
    (id) => !selection.importing_book_ids.includes(id),
  ) ?? [];
  const bookName = selection?.book_names?.[bookId] ?? bookId;

  const confirmDelete = async () => {
    if (!bookId || deleting) return;
    setDeleting(true);
    setError("");
    try {
      const updated = await deleteBook(bookId);
      onDeleted(bookId, updated);
      onClose();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除书籍失败");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog settings-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-book-title">
        <div className="import-header">
          <h2 id="delete-book-title">删除书籍</h2>
          <button className="import-close" type="button" aria-label="关闭删除书籍" disabled={deleting} onClick={onClose}>×</button>
        </div>

        {!selection && !error ? <div className="settings-loading">加载书籍中…</div> : (
          <div className="delete-book-body">
            {!confirming ? (
              <>
                <label className="delete-book-field">
                  <span>你想删除哪一本书？</span>
                  <select value={bookId} disabled={availableBooks.length === 0} onChange={(event) => setBookId(event.target.value)}>
                    {availableBooks.map((id) => (
                      <option key={id} value={id}>
                        {selection?.book_names?.[id] && selection.book_names[id] !== id
                          ? `${selection.book_names[id]}（${id}）`
                          : id}
                      </option>
                    ))}
                  </select>
                </label>
                {selection && availableBooks.length === 0 && <p className="delete-book-note">暂无可删除的书籍。</p>}
              </>
            ) : (
              <p className="delete-book-warning">
                确定删除《{bookName}》（{bookId}）吗？书籍文件、模糊搜索索引和这本书的所有对话记录将永久删除。
              </p>
            )}
            {error && <div className="import-error">{error}</div>}
            <div className="delete-book-actions">
              <button type="button" className="delete-book-cancel" disabled={deleting} onClick={() => {
                if (confirming) {
                  setConfirming(false);
                  setError("");
                } else {
                  onClose();
                }
              }}>{confirming ? "返回选择" : "取消"}</button>
              <button
                type="button"
                className={confirming ? "delete-book-confirm" : "import-primary"}
                disabled={!bookId || deleting}
                onClick={() => confirming ? void confirmDelete() : setConfirming(true)}
              >
                {deleting ? "删除中…" : confirming ? "确认永久删除" : "下一步"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

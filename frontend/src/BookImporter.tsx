import { useEffect, useState } from "react";
import { discardBookImport, importBook, loadBookImport, saveBookInfo } from "./api";

type BookImporterProps = {
  initialBookId?: string;
  onClose: () => void;
  onImportCreated: (bookId: string, name: string) => void;
  onImported: (bookId: string, startEmbedding: boolean) => Promise<void>;
  onDiscarded: (bookId: string) => Promise<void>;
};

export default function BookImporter({
  initialBookId,
  onClose,
  onImportCreated,
  onImported,
  onDiscarded,
}: BookImporterProps) {
  const [step, setStep] = useState<"upload" | "info" | "completed">(
    initialBookId ? "info" : "upload",
  );
  const [file, setFile] = useState<File | null>(null);
  const [bookId, setBookId] = useState<string | null>(initialBookId ?? null);
  const [chapterCount, setChapterCount] = useState(0);
  const [name, setName] = useState("");
  const [info, setInfo] = useState("");
  const [startEmbedding, setStartEmbedding] = useState(false);
  const [busy, setBusy] = useState(Boolean(initialBookId));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initialBookId) return;
    let cancelled = false;
    void loadBookImport(initialBookId)
      .then((current) => {
        if (cancelled) return;
        setChapterCount(current.chapter_count ?? 0);
        setName(current.name || current.original_name?.replace(/\.txt$/i, "") || initialBookId);
        setInfo(current.info || "");
        setStep(current.status === "awaiting_info" ? "info" : "completed");
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "恢复导入失败");
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => { cancelled = true; };
  }, [initialBookId]);

  const upload = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await importBook(file);
      const importedName = result.name || file.name.replace(/\.txt$/i, "");
      setBookId(result.book_id);
      setChapterCount(result.chapter_count ?? 0);
      setName(importedName);
      setInfo("");
      setStep("info");
      onImportCreated(result.book_id, importedName);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "导入小说失败");
    } finally {
      setBusy(false);
    }
  };

  const enterBook = async (targetBookId: string) => {
    setBusy(true);
    setError("");
    try {
      await onImported(targetBookId, startEmbedding);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "打开书籍失败");
    } finally {
      setBusy(false);
    }
  };

  const submitInfo = async () => {
    if (!bookId || !name.trim() || !info.trim() || busy) return;
    setBusy(true);
    setError("");
    let saved = false;
    try {
      await saveBookInfo(bookId, name.trim(), info);
      saved = true;
      setStep("completed");
      await onImported(bookId, startEmbedding);
    } catch (requestError) {
      setError(requestError instanceof Error
        ? requestError.message
        : saved ? "打开书籍失败" : "保存书籍信息失败");
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!bookId || busy) return;
    setBusy(true);
    setError("");
    try {
      await discardBookImport(bookId);
      await onDiscarded(bookId);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "放弃导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="import-header">
          <h2 id="import-title">{initialBookId ? "继续导入书籍" : "导入书籍"}</h2>
          <button className="import-close" type="button" aria-label="关闭导入窗口"
            title="关闭并稍后继续" disabled={busy} onClick={onClose}>×</button>
        </div>

        <div className="import-steps" aria-label="导入进度">
          <span className={step === "upload" ? "active" : "done"}>1 上传并切章</span>
          <span className={step === "info" ? "active" : step === "completed" ? "done" : ""}>2 书籍信息</span>
        </div>

        {step === "upload" && (
          <div className="import-body">
            <label className="file-picker">
              <span>{file ? file.name : "选择小说 TXT 文件"}</span>
              <input type="file" accept=".txt,text/plain" disabled={busy}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>
            <button className="import-primary" type="button" disabled={!file || busy}
              onClick={() => void upload()}>
              {busy ? "正在上传并切章…" : "上传并切分章节"}
            </button>
          </div>
        )}

        {step === "info" && (
          <div className="import-body">
            <div className="import-result">已识别 {chapterCount} 章</div>
            <label className="info-editor">
              <span>书名</span>
              <input value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="info-editor">
              <span>概况</span>
              <textarea value={info} rows={10} disabled={busy}
                onChange={(event) => setInfo(event.target.value)} />
            </label>
            <label className="import-option">
              <input type="checkbox" checked={startEmbedding} disabled={busy}
                onChange={(event) => setStartEmbedding(event.target.checked)} />
              完成导入后在后台建立模糊搜索索引
            </label>
            <button className="import-primary" type="button"
              disabled={!name.trim() || !info.trim() || busy} onClick={() => void submitInfo()}>
              {busy ? "正在保存…" : "完成导入"}
            </button>
          </div>
        )}

        {step === "completed" && (
          <div className="import-body">
            <p className="import-note">书籍已导入，可以开始聊天。</p>
            {bookId && <button className="import-primary" type="button" disabled={busy}
              onClick={() => void enterBook(bookId)}>进入书籍</button>}
          </div>
        )}

        {bookId && step === "info" && (
          <button className="import-discard" type="button" disabled={busy}
            onClick={() => void discard()}>放弃这次导入</button>
        )}
        {error && <div className="import-error">{error}</div>}
      </section>
    </div>
  );
}

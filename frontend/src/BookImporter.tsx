import { useEffect, useRef, useState } from "react";
import {
  discardBookImport,
  importBook,
  loadBookEmbeddingStatus,
  loadBookImport,
  saveBookInfo,
  startBookEmbedding,
} from "./api";
import type { BookImportStatus } from "./types";

type BookImporterProps = {
  initialBookId?: string;
  onClose: () => void;
  onImportCreated: (bookId: string, name: string) => void;
  onInfoSaved: (bookId: string, name: string) => void;
  onImported: (bookId: string) => Promise<void>;
  onDiscarded: (bookId: string) => Promise<void>;
};

const runningStatuses = new Set<BookImportStatus["status"]>([
  "pending",
  "loading_model",
  "encoding",
  "writing",
]);

const wait = (milliseconds: number) => new Promise((resolve) => {
  window.setTimeout(resolve, milliseconds);
});

function defaultName(filename: string): string {
  return filename.replace(/\.txt$/i, "");
}

function defaultInfo(): string {
  return "作者：\n类型：\n主要人物：\n简介：";
}

export default function BookImporter({
  initialBookId,
  onClose,
  onImportCreated,
  onInfoSaved,
  onImported,
  onDiscarded,
}: BookImporterProps) {
  const [step, setStep] = useState<"upload" | "info" | "embedding">(
    initialBookId ? "info" : "upload",
  );
  const [file, setFile] = useState<File | null>(null);
  const [bookId, setBookId] = useState<string | null>(initialBookId ?? null);
  const [chapterCount, setChapterCount] = useState(0);
  const [name, setName] = useState("");
  const [info, setInfo] = useState("");
  const [status, setStatus] = useState<BookImportStatus | null>(null);
  const [busy, setBusy] = useState(Boolean(initialBookId));
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const polling = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!initialBookId) return;
    void resumeImport(initialBookId);
  }, [initialBookId]);

  async function resumeImport(resumeBookId: string) {
    setBusy(true);
    setError("");
    try {
      const current = await loadBookImport(resumeBookId);
      if (!mounted.current) return;
      setBookId(resumeBookId);
      setChapterCount(current.chapter_count ?? 0);
      setName(current.name || defaultName(current.original_name ?? resumeBookId));
      setInfo(current.info || defaultInfo());

      if (current.status === "completed") {
        await onImported(resumeBookId);
        return;
      }

      if (current.status === "awaiting_info") {
        setStep("info");
        return;
      }

      setStep("embedding");
      setStatus(current);
      if (runningStatuses.has(current.status)) {
        setBusy(false);
        await pollEmbedding(resumeBookId, current);
      } else if (current.status === "failed") {
        setError(current.error || "向量化失败，可以重新尝试");
      }
    } catch (requestError) {
      if (mounted.current) {
        setError(requestError instanceof Error ? requestError.message : "恢复导入失败");
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function pollEmbedding(targetBookId: string, initial: BookImportStatus) {
    if (polling.current) return;
    polling.current = true;
    let current = initial;
    try {
      while (mounted.current && runningStatuses.has(current.status)) {
        await wait(1000);
        if (!mounted.current) return;
        current = await loadBookEmbeddingStatus(targetBookId);
        if (mounted.current) setStatus(current);
      }

      if (!mounted.current) return;
      if (current.status === "failed") {
        setError(current.error || "向量化失败，可以重新尝试");
      } else if (current.status === "completed") {
        await onImported(targetBookId);
      }
    } catch (requestError) {
      if (!mounted.current) return;
      const message = requestError instanceof Error ? requestError.message : "向量化失败";
      setStatus((previous) => previous ? {
        ...previous,
        status: "failed",
        message: "暂时无法读取向量化进度，可以重新连接",
        error: message,
      } : previous);
      setError(message);
    } finally {
      polling.current = false;
    }
  }

  const upload = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await importBook(file);
      setBookId(result.book_id);
      setChapterCount(result.chapter_count ?? 0);
      const importedName = result.name || defaultName(file.name);
      setName(importedName);
      setInfo(defaultInfo());
      setStep("info");
      onImportCreated(result.book_id, importedName);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "导入小说失败");
    } finally {
      setBusy(false);
    }
  };

  const submitInfo = async () => {
    if (!bookId || !name.trim() || !info.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await saveBookInfo(bookId, name.trim(), info);
      onInfoSaved(bookId, result.name ?? name.trim());
      setStep("embedding");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存书籍信息失败");
    } finally {
      setBusy(false);
    }
  };

  const runEmbedding = async () => {
    if (!bookId || busy || polling.current) return;
    setBusy(true);
    setError("");
    try {
      const current = await startBookEmbedding(bookId);
      setStatus(current);
      if (current.status === "completed") {
        await onImported(bookId);
      } else if (current.status === "failed") {
        setError(current.error || "向量化失败，可以重新尝试");
      } else {
        onClose();
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "向量化失败");
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const discard = async () => {
    if (!bookId || busy || (status && runningStatuses.has(status.status))) return;
    setBusy(true);
    setError("");
    try {
      await discardBookImport(bookId);
      await onDiscarded(bookId);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "放弃导入失败");
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const progress = status?.total
    ? Math.round(status.processed / status.total * 100)
    : 0;
  const embeddingRunning = Boolean(status && runningStatuses.has(status.status));

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="import-header">
          <div>
            <h2 id="import-title">{initialBookId ? "继续导入书籍" : "导入书籍"}</h2>
          </div>
          <button
            className="import-close"
            type="button"
            aria-label="关闭导入窗口"
            title="关闭并稍后继续"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <div className="import-steps" aria-label="导入进度">
          <span className={step === "upload" ? "active" : "done"}>1 上传并切章</span>
          <span className={step === "info" ? "active" : step === "embedding" ? "done" : ""}>2 书籍信息</span>
          <span className={step === "embedding" ? "active" : ""}>3 向量化</span>
        </div>

        {step === "upload" && (
          <div className="import-body">
            <label className="file-picker">
              <span>{file ? file.name : "选择小说 TXT 文件"}</span>
              <input
                type="file"
                accept=".txt,text/plain"
                disabled={busy}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button className="import-primary" type="button" disabled={!file || busy} onClick={() => void upload()}>
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
              <textarea value={info} rows={10} disabled={busy} onChange={(event) => setInfo(event.target.value)} />
            </label>
            <button className="import-primary" type="button" disabled={!name.trim() || !info.trim() || busy} onClick={() => void submitInfo()}>
              {busy ? "正在保存…" : "下一步"}
            </button>
          </div>
        )}

        {step === "embedding" && (
          <div className="import-body">
            {status ? (
              <>
                <div className="embedding-message">{status.message}</div>
                <div className="embedding-progress" aria-label={`向量化进度 ${progress}%`}>
                  <div className="embedding-progress-value" style={{ width: `${progress}%` }} />
                </div>
                <div className="embedding-progress-text">
                  {status.total > 0
                    ? `${status.processed} / ${status.total}（${progress}%）`
                    : "正在准备向量模型…"}
                </div>
              </>
            ) : (
              <p className="import-note">任务会在后台运行，可随时从书籍菜单查看进度。</p>
            )}
            {!embeddingRunning && status?.status !== "completed" && (
              <button className="import-primary" type="button" disabled={busy} onClick={() => void runEmbedding()}>
                {status?.status === "failed" ? "重新开始后台向量化" : "开始后台向量化"}
              </button>
            )}
          </div>
        )}

        {bookId && !embeddingRunning && (
          <button className="import-discard" type="button" disabled={busy} onClick={() => void discard()}>
            放弃这次导入
          </button>
        )}
        {error && <div className="import-error">{error}</div>}
      </section>
    </div>
  );
}

import { useState } from "react";
import type { BookImportStatus } from "./types";

type EmbeddingManagerProps = {
  bookName: string;
  status: BookImportStatus | null;
  loadError: string;
  onClose: () => void;
  onStart: () => Promise<void>;
  onRefresh: () => void;
};

const runningStatuses = new Set<BookImportStatus["status"]>([
  "pending", "loading_model", "encoding", "writing",
]);

export default function EmbeddingManager({
  bookName, status, loadError, onClose, onStart, onRefresh,
}: EmbeddingManagerProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = Boolean(status && runningStatuses.has(status.status));
  const progress = status?.total ? Math.round(status.processed / status.total * 100) : 0;

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      await onStart();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "启动向量化失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="embedding-title">
        <div className="import-header">
          <h2 id="embedding-title">向量化</h2>
          <button className="import-close" type="button" aria-label="关闭模糊搜索窗口"
            onClick={onClose}>×</button>
        </div>
        <div className="import-body embedding-manager-body">
          <p className="import-note">建立向量索引后，AI 会获得模糊搜索工具。生成期间仍可正常聊天。</p>
          <div className="embedding-message">{status?.message ?? (loadError || "正在读取状态…")}</div>
          {running && status && (
            <>
              <div className="embedding-progress" aria-label={`向量化进度 ${status.processed}/${status.total}`}>
                <div className="embedding-progress-value" style={{ width: `${progress}%` }} />
              </div>
              <div className="embedding-progress-text">
                {status.total > 0 ? `${status.processed} / ${status.total}（${progress}%）` : "正在准备向量模型…"}
              </div>
            </>
          )}
          {status?.status === "failed" && status.error && <div className="import-error">{status.error}</div>}
          {status && !running && status.status !== "completed" && (
            <button className="import-primary" type="button" disabled={busy}
              onClick={() => void start()}>
              {status.status === "failed" ? "继续向量化" : "开始向量化"}
            </button>
          )}
          {!status && loadError && (
            <button className="import-primary" type="button" onClick={onRefresh}>重新读取状态</button>
          )}
          {error && <div className="import-error">{error}</div>}
        </div>
      </section>
    </div>
  );
}

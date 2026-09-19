import { useEffect, useState } from "react";

import {
  loadSummaryOverview,
  planSummaries,
  saveSummaryEnabled,
  startSummaryJob,
} from "./api";
import type {
  SummaryArtifact,
  SummaryOverview,
  SummaryPlan,
  SummaryTarget,
} from "./types";
import {
  isSummaryTargetChecked,
  summaryTargetKey,
  toggleSummaryTarget,
} from "./summarySelection";


type SummaryManagerProps = {
  bookId: string;
  bookName: string;
  onClose: () => void;
};

const runningStatuses = new Set(["pending", "running"]);

function formatMillions(tokens: number): string {
  if (tokens === 0) return "0M";
  if (tokens < 10_000) return "<0.01M";
  return `${(tokens / 1_000_000).toFixed(2)}M`;
}

function artifactLabel(artifact: SummaryArtifact): string {
  if (artifact.level === "whole") return "全书总结";
  if (artifact.level === "big") return `第 ${artifact.start}-${artifact.end} 章大段总结`;
  return `第 ${artifact.start}-${artifact.end} 章总结`;
}

export default function SummaryManager({ bookId, bookName, onClose }: SummaryManagerProps) {
  const [overview, setOverview] = useState<SummaryOverview | null>(null);
  const [selectedTargets, setSelectedTargets] = useState<SummaryTarget[]>([]);
  const [plan, setPlan] = useState<SummaryPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [showCompletedJob, setShowCompletedJob] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const jobRunning = Boolean(
    overview?.job && runningStatuses.has(overview.job.status),
  );

  useEffect(() => {
    let active = true;
    setError("");
    void loadSummaryOverview(bookId)
      .then((result) => {
        if (active) setOverview(result);
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "加载总结状态失败");
        }
      });
    return () => { active = false; };
  }, [bookId]);

  useEffect(() => {
    if (!jobRunning) return;
    let active = true;
    let timer = 0;
    const poll = async () => {
      try {
        const result = await loadSummaryOverview(bookId);
        if (!active) return;
        setOverview(result);
        setError("");
        if (result.job?.status === "completed") {
          setShowCompletedJob(true);
          setSelectedTargets([]);
          setPlan(null);
        } else if (result.job && runningStatuses.has(result.job.status)) {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (requestError) {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : "读取总结进度失败");
        timer = window.setTimeout(poll, 1000);
      }
    };
    timer = window.setTimeout(poll, 1000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [bookId, jobRunning]);

  useEffect(() => {
    if (selectedTargets.length === 0 || jobRunning) {
      setPlan(null);
      setPlanning(false);
      return;
    }
    let active = true;
    setPlanning(true);
    void planSummaries(bookId, selectedTargets)
      .then((result) => {
        if (active) {
          setPlan(result);
          setError("");
        }
      })
      .catch((requestError) => {
        if (active) {
          setPlan(null);
          setError(requestError instanceof Error ? requestError.message : "估算总结消耗失败");
        }
      })
      .finally(() => {
        if (active) setPlanning(false);
      });
    return () => { active = false; };
  }, [bookId, selectedTargets, jobRunning]);

  const toggleTarget = (artifact: SummaryArtifact) => {
    if (!overview) return;
    setPlan(null);
    setSelectedTargets((previous) => toggleSummaryTarget(
      overview.summaries,
      previous,
      artifact,
    ));
  };

  const toggleEnabled = async () => {
    if (!overview || busy) return;
    setBusy(true);
    setError("");
    try {
      setOverview(await saveSummaryEnabled(bookId, !overview.enabled));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存总结检索设置失败");
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (selectedTargets.length === 0 || busy || jobRunning) return;
    setBusy(true);
    setError("");
    try {
      const job = await startSummaryJob(bookId, selectedTargets);
      setShowCompletedJob(job.status === "completed");
      setOverview((previous) => previous ? { ...previous, job } : previous);
      if (job.status === "completed") {
        setOverview(await loadSummaryOverview(bookId));
        setSelectedTargets([]);
        setPlan(null);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "启动总结任务失败");
    } finally {
      setBusy(false);
    }
  };

  const summaries = overview?.summaries ?? [];
  const whole = summaries.find((item) => item.level === "whole");
  const bigs = summaries.filter((item) => item.level === "big");
  const mids = summaries.filter((item) => item.level === "mid");
  const progress = overview?.job?.total_calls
    ? Math.round(overview.job.completed_calls / overview.job.total_calls * 100)
    : 0;

  const renderArtifact = (artifact: SummaryArtifact, nested = false) => {
    const checked = isSummaryTargetChecked(artifact, selectedTargets);
    return (
      <label className={`summary-choice ${nested ? "nested" : ""}`} key={summaryTargetKey(artifact)}>
        <input
          type="checkbox"
          checked={checked}
          disabled={artifact.exists || jobRunning || busy}
          onChange={() => toggleTarget(artifact)}
        />
        <span>{artifactLabel(artifact)}</span>
        <small>{artifact.exists ? "已生成" : "未生成"}</small>
      </label>
    );
  };

  return (
    <div className="import-overlay" role="presentation">
      <section className="import-dialog summary-dialog" role="dialog" aria-modal="true" aria-labelledby="summary-title">
        <div className="import-header">
          <div>
            <div className="import-eyebrow">当前书籍：{bookName}</div>
            <h2 id="summary-title">总结管理</h2>
          </div>
          <button className="import-close" type="button" aria-label="关闭总结管理" onClick={onClose}>×</button>
        </div>

        {overview && (
          <>
            <div className="summary-toggle-row">
              <div>
                <strong>允许 AI 查看总结</strong>
              </div>
              <button
                type="button"
                className={`summary-switch ${overview.enabled ? "enabled" : ""}`}
                aria-pressed={overview.enabled}
                disabled={busy}
                onClick={() => void toggleEnabled()}
              >
                <span />
              </button>
            </div>

            <div className="summary-meta">全书共 {overview.chapter_count} 章</div>

            <div className="summary-list">
              {whole && renderArtifact(whole)}
              {bigs.map((big) => (
                <div className="summary-group" key={summaryTargetKey(big)}>
                  {renderArtifact(big)}
                  {mids
                    .filter((mid) => (
                      mid.start !== null
                      && big.start !== null
                      && mid.start >= big.start
                      && mid.start <= big.end
                    ))
                    .map((mid) => renderArtifact(mid, true))}
                </div>
              ))}
            </div>

            {plan && !planning && !jobRunning && (
              <div className="summary-estimate">
                <strong>预计 {plan.total_calls} 次 AI 调用</strong>
                <span>
                  约 {formatMillions(plan.estimated_tokens)} tokens
                  （输入 {formatMillions(plan.estimated_input_tokens)}，输出 {formatMillions(plan.estimated_output_tokens)}）
                </span>
                <small>这是按中文字符长度计算的近似值，实际消耗以模型 usage 为准。</small>
              </div>
            )}

            {planning && !jobRunning && (
              <div className="summary-estimate">正在估算所选总结的 Token 消耗…</div>
            )}

            {overview.job && (
              overview.job.status !== "completed" || showCompletedJob
            ) && (
              <div className={`summary-job ${overview.job.status}`}>
                <div className="summary-job-heading">
                  <strong>{overview.job.current}</strong>
                  <span>{overview.job.completed_calls} / {overview.job.total_calls}</span>
                </div>
                <div className="embedding-progress" aria-label={`总结进度 ${progress}%`}>
                  <div className="embedding-progress-value" style={{ width: `${progress}%` }} />
                </div>
                {overview.job.error && <div className="import-error">{overview.job.error}</div>}
              </div>
            )}

            <div className="summary-actions">
              <span>任务开始后可关闭此页面，生成会在后台继续。</span>
              <button
                className="import-primary"
                type="button"
                disabled={selectedTargets.length === 0 || !plan || planning || plan.total_calls === 0 || busy || jobRunning}
                onClick={() => void start()}
              >
                {jobRunning ? "正在生成" : "开始生成"}
              </button>
            </div>
          </>
        )}

        {!overview && !error && <div className="summary-loading">加载中…</div>}
        {error && <div className="import-error">{error}</div>}
      </section>
    </div>
  );
}

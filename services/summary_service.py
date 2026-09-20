"""Per-book summary settings, planning, and background generation."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any

from config import BOOKS_DIR, BookPaths
from services.model_provider import ModelConnection, get_selected_model_connection
from summaries import (
    generate_summary,
    plan_summary_targets,
    summary_inventory,
    total_chapters,
)


RUNNING_SUMMARY_STATUSES = {"pending", "running"}
SUMMARY_STATUSES = RUNNING_SUMMARY_STATUSES | {"completed", "failed"}


def _default_state() -> dict[str, Any]:
    return {"enabled": False, "job": None}


def _valid_job(job: Any) -> bool:
    if job is None:
        return True
    if not isinstance(job, dict) or job.get("status") not in SUMMARY_STATUSES:
        return False
    if not isinstance(job.get("targets"), list):
        return False
    integer_fields = (
        "completed_calls",
        "total_calls",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_tokens",
    )
    if any(
        not isinstance(job.get(field), int)
        or isinstance(job.get(field), bool)
        or job[field] < 0
        for field in integer_fields
    ):
        return False
    return (
        job["completed_calls"] <= job["total_calls"]
        and isinstance(job.get("current"), str)
        and (job.get("error") is None or isinstance(job.get("error"), str))
    )


def read_summary_state(book_path: BookPaths) -> dict[str, Any]:
    path = book_path.summary_state_file
    if not path.exists():
        return _default_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"总结状态文件损坏：{exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("enabled"), bool):
        raise ValueError("总结状态文件格式错误")
    if "job" not in state:
        raise ValueError("总结状态文件缺少 job 字段")
    if not _valid_job(state["job"]):
        raise ValueError("总结状态文件中的 job 格式错误")
    return state


def summary_enabled(book_id: str) -> bool:
    return bool(read_summary_state(BookPaths(book_id))["enabled"])


class SummaryService:
    def __init__(self, books_dir: Path = BOOKS_DIR):
        self._books_dir = books_dir
        self._state_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._recover_jobs()

    def get_overview(self, book_id: str) -> dict[str, Any]:
        book_path = self._require_book(book_id)
        state = self._read_state(book_path)
        return {
            "book_id": book_id,
            "enabled": state["enabled"],
            "chapter_count": total_chapters(book_path),
            "summaries": summary_inventory(book_path),
            "job": state["job"],
        }

    def set_enabled(self, book_id: str, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise ValueError("总结检索开关必须是布尔值")
        book_path = self._require_book(book_id)
        with self._state_lock:
            state = read_summary_state(book_path)
            state["enabled"] = enabled
            self._write_state(book_path, state)
        return self.get_overview(book_id)

    def plan(self, book_id: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
        book_path = self._require_book(book_id)
        if not targets:
            raise ValueError("请至少选择一个总结")
        return plan_summary_targets(targets, book_path)

    def start(self, book_id: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
        book_path = self._require_book(book_id)
        plan = self.plan(book_id, targets)
        model_connection = (
            get_selected_model_connection()
            if plan["total_calls"] > 0
            else None
        )

        with self._state_lock:
            state = read_summary_state(book_path)
            current_job = state["job"]
            if current_job and current_job.get("status") in RUNNING_SUMMARY_STATUSES:
                raise RuntimeError("该书的总结任务正在运行")

            completed = plan["total_calls"] == 0
            job = {
                "status": "completed" if completed else "pending",
                "targets": plan["targets"],
                "completed_calls": plan["total_calls"] if completed else 0,
                "total_calls": plan["total_calls"],
                "estimated_input_tokens": plan["estimated_input_tokens"],
                "estimated_output_tokens": plan["estimated_output_tokens"],
                "estimated_tokens": plan["estimated_tokens"],
                "current": "所选总结均已生成" if completed else "任务正在等待执行",
                "error": None,
            }
            state["job"] = job
            self._write_state(book_path, state)

        if not completed:
            self._start_worker(book_id, plan["targets"], model_connection)
        return job

    def _start_worker(
        self,
        book_id: str,
        targets: list[dict[str, Any]],
        model_connection: ModelConnection | None = None,
    ) -> None:
        threading.Thread(
            target=self._run_job,
            args=(book_id, targets, model_connection),
            daemon=True,
            name=f"summary-{book_id}",
        ).start()

    def _run_job(
        self,
        book_id: str,
        targets: list[dict[str, Any]],
        model_connection: ModelConnection | None = None,
    ) -> None:
        book_path = BookPaths(book_id)
        try:
            connection = model_connection or get_selected_model_connection()
            with self._worker_lock:
                self._update_job(
                    book_path,
                    status="running",
                    current="正在准备总结任务",
                    error=None,
                )

                def on_progress(event: str, label: str) -> None:
                    if event == "start":
                        self._update_job(book_path, current=label)
                    elif event == "complete":
                        with self._state_lock:
                            state = read_summary_state(book_path)
                            job = state["job"]
                            if job is None:
                                return
                            job["completed_calls"] = min(
                                job["completed_calls"] + 1,
                                job["total_calls"],
                            )
                            job["current"] = f"已完成：{label.removeprefix('正在')}"
                            self._write_state(book_path, state)

                for target in targets:
                    generate_summary(
                        target["level"],
                        book_path,
                        target.get("start"),
                        on_progress,
                        connection,
                    )

                with self._state_lock:
                    state = read_summary_state(book_path)
                    job = state["job"]
                    if job is not None:
                        job.update({
                            "status": "completed",
                            "completed_calls": job["total_calls"],
                            "current": "所选总结已全部生成",
                            "error": None,
                        })
                        self._write_state(book_path, state)
        except Exception as exc:
            self._update_job(
                book_path,
                status="failed",
                current="总结生成失败，可以重新开始",
                error=str(exc),
            )

    def _recover_jobs(self) -> None:
        if not self._books_dir.exists():
            return
        for root in self._books_dir.iterdir():
            if not root.is_dir():
                continue
            book_path = BookPaths(root.name)
            if not book_path.summary_state_file.exists():
                continue
            state = read_summary_state(book_path)
            job = state["job"]
            if job and job.get("status") in RUNNING_SUMMARY_STATUSES:
                job["status"] = "pending"
                job["current"] = "程序重新启动，任务正在等待恢复"
                self._write_state(book_path, state)
                self._start_worker(root.name, job["targets"])

    def _require_book(self, book_id: str) -> BookPaths:
        book_path = BookPaths(book_id)
        if not book_id or not book_path.root.is_dir() or not book_path.chapter_dir.is_dir():
            raise ValueError(f"找不到书籍：{book_id}")
        return book_path

    def _read_state(self, book_path: BookPaths) -> dict[str, Any]:
        with self._state_lock:
            return read_summary_state(book_path)

    def _update_job(self, book_path: BookPaths, **changes: Any) -> None:
        with self._state_lock:
            state = read_summary_state(book_path)
            job = state["job"]
            if job is None:
                return
            job.update(changes)
            self._write_state(book_path, state)

    @staticmethod
    def _write_state(book_path: BookPaths, state: dict[str, Any]) -> None:
        path = book_path.summary_state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(state, temporary_file, ensure_ascii=False, indent=2)
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

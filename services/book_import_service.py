"""Create books through the upload, info, and embedding import workflow."""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from config import BOOKS_DIR, DATABASE_DIR, BookPaths
from embedding import build_embedding
from scripts.splitter import split_book


IMPORT_STATE_FILE = ".importing.json"
BOOK_ID_PATTERN = re.compile(r"book_[0-9a-f]{12}")


class BookImportService:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._states_lock = threading.Lock()
        self._embedding_lock = threading.Lock()
        self._recover_interrupted_imports()

    def create_import(self, filename: str, content: bytes) -> dict[str, Any]:
        if not filename.lower().endswith(".txt"):
            raise ValueError("请选择 txt 小说文件")
        if not content:
            raise ValueError("小说文件不能为空")

        text = self._decode_novel(content)
        book_id = self._new_book_id()
        book_path = BookPaths(book_id)
        book_path.root.mkdir(parents=True)

        state = {
            "book_id": book_id,
            "original_name": Path(filename).name,
            "chapter_count": 0,
            "status": "splitting",
            "processed": 0,
            "total": 0,
            "message": "正在切分章节",
            "error": None,
        }
        self._save_state(book_path, state)

        try:
            self._write_text(book_path.novel_file, text)
            state["chapter_count"] = split_book(book_path)
            state["status"] = "awaiting_info"
            state["message"] = "章节切分完成，请填写书籍信息"
            self._save_state(book_path, state)
            return dict(state)
        except Exception:
            shutil.rmtree(book_path.root, ignore_errors=True)
            with self._states_lock:
                self._states.pop(book_id, None)
            raise

    def save_info(self, book_id: str, content: str) -> dict[str, Any]:
        book_path = self._require_import(book_id)
        if not content.strip():
            raise ValueError("书籍信息不能为空")

        self._write_text(book_path.info_file, content.strip() + "\n")
        state = self._read_state(book_path)
        state.update({
            "status": "ready_for_embedding",
            "message": "书籍信息已保存，可以开始向量化",
            "error": None,
        })
        self._remove_building_dirs(book_id)
        self._save_state(book_path, state)
        return dict(state)

    def start_embedding(self, book_id: str) -> dict[str, Any]:
        book_path = self._require_import(book_id)
        if not book_path.info_file.exists():
            raise ValueError("请先填写书籍信息")

        state = self._read_state(book_path)
        if state["status"] in {"pending", "loading_model", "encoding", "writing"}:
            return state

        state.update({
            "status": "pending",
            "processed": 0,
            "total": 0,
            "message": "向量化任务正在等待执行",
            "error": None,
        })
        self._save_state(book_path, state)
        threading.Thread(
            target=self._run_embedding,
            args=(book_path,),
            daemon=True,
            name=f"embedding-{book_id}",
        ).start()
        return dict(state)

    def get_status(self, book_id: str) -> dict[str, Any]:
        self._validate_book_id(book_id)
        book_path = BookPaths(book_id)
        if not book_path.root.exists():
            raise ValueError("找不到这次书籍导入")

        marker = book_path.root / IMPORT_STATE_FILE
        if marker.exists():
            return self._read_state(book_path)

        if book_path.vector_db_dir.exists():
            with self._states_lock:
                state = self._states.get(book_id)
            return dict(state) if state is not None else {
                "book_id": book_id,
                "status": "completed",
                "processed": 0,
                "total": 0,
                "message": "书籍导入完成",
                "error": None,
            }
        raise ValueError("找不到这次书籍导入")

    def get_import(self, book_id: str) -> dict[str, Any]:
        state = self.get_status(book_id)
        book_path = BookPaths(book_id)
        state["info"] = (
            book_path.info_file.read_text(encoding="utf-8")
            if book_path.info_file.exists()
            else ""
        )
        return state

    def discard_import(self, book_id: str) -> None:
        book_path = self._require_import(book_id)
        state = self._read_state(book_path)
        if state["status"] in {"pending", "loading_model", "encoding", "writing"}:
            raise ValueError("向量化正在运行，暂时不能放弃导入")
        self._remove_building_dirs(book_id)
        shutil.rmtree(book_path.root)
        with self._states_lock:
            self._states.pop(book_id, None)

    def _run_embedding(self, book_path: BookPaths) -> None:
        temporary_dir = (
            DATABASE_DIR
            / "vector_db"
            / f".building-{book_path.book_id}-{uuid.uuid4().hex[:8]}"
        )
        try:
            with self._embedding_lock:
                self._update_state(
                    book_path,
                    status="loading_model",
                    message="正在加载向量模型",
                )

                def on_progress(processed: int, total: int) -> None:
                    self._update_state(
                        book_path,
                        status="encoding",
                        processed=processed,
                        total=total,
                        message="正在生成文本向量",
                    )

                build_embedding(book_path, temporary_dir, on_progress)
                self._update_state(
                    book_path,
                    status="writing",
                    message="正在保存向量数据库",
                )
                book_path.vector_db_dir.parent.mkdir(parents=True, exist_ok=True)
                if book_path.vector_db_dir.exists():
                    shutil.rmtree(book_path.vector_db_dir)
                temporary_dir.replace(book_path.vector_db_dir)

                state = self._read_state(book_path)
                state.update({
                    "status": "completed",
                    "processed": state.get("total", 0),
                    "message": "书籍导入完成",
                    "error": None,
                })
                with self._states_lock:
                    self._states[book_path.book_id] = dict(state)
                (book_path.root / IMPORT_STATE_FILE).unlink()
        except Exception as exc:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            self._update_state(
                book_path,
                status="failed",
                message="向量化失败，可以重新尝试",
                error=str(exc),
            )

    def _update_state(self, book_path: BookPaths, **changes: Any) -> None:
        state = self._read_state(book_path)
        state.update(changes)
        self._save_state(book_path, state)

    def _require_import(self, book_id: str) -> BookPaths:
        self._validate_book_id(book_id)
        book_path = BookPaths(book_id)
        if not (book_path.root / IMPORT_STATE_FILE).exists():
            raise ValueError("找不到这次未完成的书籍导入")
        return book_path

    @staticmethod
    def _validate_book_id(book_id: str) -> None:
        if BOOK_ID_PATTERN.fullmatch(book_id) is None:
            raise ValueError("无效的 book_id")

    @staticmethod
    def _decode_novel(content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("无法识别小说文件编码，请转换为 UTF-8 后重试")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(path)

    def _new_book_id(self) -> str:
        while True:
            book_id = f"book_{uuid.uuid4().hex[:12]}"
            if not (BOOKS_DIR / book_id).exists():
                return book_id

    def _recover_interrupted_imports(self) -> None:
        if not BOOKS_DIR.exists():
            return
        running_statuses = {"pending", "loading_model", "encoding", "writing"}
        for marker in BOOKS_DIR.glob(f"*/{IMPORT_STATE_FILE}"):
            state = json.loads(marker.read_text(encoding="utf-8"))
            if state.get("status") == "splitting":
                shutil.rmtree(marker.parent, ignore_errors=True)
                continue
            if state.get("status") not in running_statuses:
                continue
            state.update({
                "status": "failed",
                "message": "后端在向量化期间重新启动，可以重新尝试",
                "error": "向量化任务因后端重启而中断",
            })
            book_path = BookPaths(state["book_id"])
            self._remove_building_dirs(book_path.book_id)
            self._save_state(book_path, state)

    @staticmethod
    def _remove_building_dirs(book_id: str) -> None:
        vector_root = DATABASE_DIR / "vector_db"
        if not vector_root.exists():
            return
        for path in vector_root.glob(f".building-{book_id}-*"):
            shutil.rmtree(path, ignore_errors=True)

    def _read_state(self, book_path: BookPaths) -> dict[str, Any]:
        with self._states_lock:
            state = self._states.get(book_path.book_id)
            if state is not None:
                return dict(state)

        marker = book_path.root / IMPORT_STATE_FILE
        state = json.loads(marker.read_text(encoding="utf-8"))
        with self._states_lock:
            self._states[book_path.book_id] = dict(state)
        return state

    def _save_state(self, book_path: BookPaths, state: dict[str, Any]) -> None:
        marker = book_path.root / IMPORT_STATE_FILE
        serialized = json.dumps(state, ensure_ascii=False, indent=2)
        self._write_text(marker, serialized)
        with self._states_lock:
            self._states[book_path.book_id] = dict(state)

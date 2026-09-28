"""Import books and manage their optional embedding jobs."""

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
BOOK_ID_PATTERN = re.compile(r"[\w-]+")


class BookImportService:
    def __init__(self) -> None:
        self._start_lock = threading.Lock()
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
            "name": Path(filename).stem,
            "chapter_count": 0,
            "status": "splitting",
            "processed": 0,
            "total": 0,
            "message": "正在切分章节",
            "error": None,
        }
        self._write_state(book_path.root / IMPORT_STATE_FILE, state)

        try:
            self._write_text(book_path.novel_file, text)
            state["chapter_count"] = split_book(book_path)
            state["status"] = "awaiting_info"
            state["message"] = "章节切分完成，请填写书籍信息"
            self._write_state(book_path.root / IMPORT_STATE_FILE, state)
            return dict(state)
        except Exception:
            shutil.rmtree(book_path.root, ignore_errors=True)
            raise

    def save_info(self, book_id: str, name: str, content: str) -> dict[str, Any]:
        book_path = self._require_import(book_id)
        state = self._read_state(book_path.root / IMPORT_STATE_FILE)
        if state["status"] != "awaiting_info":
            raise ValueError("书籍信息已保存，不能在导入流程中修改")
        name = name.strip()
        if not name:
            raise ValueError("书名不能为空")
        if not content.strip():
            raise ValueError("书籍信息不能为空")

        self._write_text(book_path.name_file, name + "\n")
        self._write_text(book_path.info_file, content.strip() + "\n")
        state.update({
            "name": name,
            "status": "ready_for_embedding",
            "message": "尚未生成模糊搜索索引",
            "error": None,
        })
        self._write_state(book_path.embedding_state_file, state)
        (book_path.root / IMPORT_STATE_FILE).unlink()
        return dict(state)

    def start_embedding(self, book_id: str) -> dict[str, Any]:
        with self._start_lock:
            self._validate_book_id(book_id)
            book_path = BookPaths(book_id)
            if not book_path.info_file.exists():
                raise ValueError("请先填写书籍信息")

            state = self.get_status(book_id)
            if state["status"] in {"pending", "loading_model", "encoding", "writing"}:
                return state
            if state["status"] == "completed":
                return state

            state.update({
                "status": "pending",
                "message": "向量化任务正在等待继续",
                "error": None,
            })
            self._write_state(book_path.embedding_state_file, state)
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
            raise ValueError("找不到书籍")

        if book_path.embedding_state_file.exists():
            return self._read_state(book_path.embedding_state_file)

        if book_path.vector_db_dir.exists():
            return {
                "book_id": book_id,
                "status": "completed",
                "processed": 0,
                "total": 0,
                "message": "模糊搜索已可用",
                "error": None,
            }
        if book_path.info_file.exists():
            return {
                "book_id": book_id,
                "status": "ready_for_embedding",
                "processed": 0,
                "total": 0,
                "message": "尚未生成模糊搜索索引",
                "error": None,
            }
        marker = book_path.root / IMPORT_STATE_FILE
        if marker.exists():
            return self._read_state(marker)
        raise ValueError("书籍尚未填写信息")

    def get_import(self, book_id: str) -> dict[str, Any]:
        state = self.get_status(book_id)
        book_path = BookPaths(book_id)
        state["name"] = (
            book_path.name_file.read_text(encoding="utf-8").strip()
            if book_path.name_file.exists()
            else state.get("name", "")
        )
        state["info"] = (
            book_path.info_file.read_text(encoding="utf-8")
            if book_path.info_file.exists()
            else ""
        )
        return state

    def discard_import(self, book_id: str) -> None:
        book_path = self._require_import(book_id)
        state = self._read_state(book_path.root / IMPORT_STATE_FILE)
        if state["status"] != "awaiting_info":
            raise ValueError("只能放弃尚未完成的书籍导入")
        self._remove_building_dirs(book_id)
        shutil.rmtree(book_path.root)

    def _run_embedding(self, book_path: BookPaths) -> None:
        temporary_dir = self._building_dir(book_path.book_id)
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

                state = self._read_state(book_path.embedding_state_file)
                state.update({
                    "status": "completed",
                    "processed": state.get("total", 0),
                    "message": "模糊搜索已可用",
                    "error": None,
                })
                self._write_state(book_path.embedding_state_file, state)
        except Exception as exc:
            self._update_state(
                book_path,
                status="failed",
                message="向量化失败，可以从已有进度继续",
                error=str(exc),
            )

    def _update_state(self, book_path: BookPaths, **changes: Any) -> None:
        state = self._read_state(book_path.embedding_state_file)
        state.update(changes)
        self._write_state(book_path.embedding_state_file, state)

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

        for marker in BOOKS_DIR.glob("*/embedding_state.json"):
            state = self._read_state(marker)
            if state.get("status") in running_statuses:
                if (DATABASE_DIR / "vector_db" / marker.parent.name).exists():
                    state.update({
                        "status": "completed",
                        "processed": state.get("total", 0),
                        "message": "模糊搜索已可用",
                        "error": None,
                    })
                else:
                    state.update({
                        "status": "failed",
                        "message": "向量化已中断，可以从已有进度继续",
                        "error": "向量化任务因后端重启而中断",
                    })
                self._write_state(marker, state)

    @staticmethod
    def _building_dir(book_id: str) -> Path:
        vector_root = DATABASE_DIR / "vector_db"
        current = vector_root / f".building-{book_id}"
        if current.exists():
            return current
        existing = sorted(vector_root.glob(f".building-{book_id}-*"))
        if existing:
            return existing[0]
        return current

    @staticmethod
    def _remove_building_dirs(book_id: str) -> None:
        vector_root = DATABASE_DIR / "vector_db"
        if not vector_root.exists():
            return
        shutil.rmtree(vector_root / f".building-{book_id}", ignore_errors=True)
        for path in vector_root.glob(f".building-{book_id}-*"):
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _read_state(marker: Path) -> dict[str, Any]:
        return json.loads(marker.read_text(encoding="utf-8"))

    def _write_state(self, marker: Path, state: dict[str, Any]) -> None:
        serialized = json.dumps(state, ensure_ascii=False, indent=2)
        self._write_text(marker, serialized)

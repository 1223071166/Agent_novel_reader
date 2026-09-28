"""Delete one book and its associated local data."""

from __future__ import annotations

import shutil
from pathlib import Path

import config
from config import BookPaths
from services.book_import_service import BOOK_ID_PATTERN, IMPORT_STATE_FILE, BookImportService
from services.chat_service import ChatService
from services.summary_service import (
    RUNNING_SUMMARY_STATUSES,
    SummaryService,
    read_summary_state,
)


RUNNING_EMBEDDING_STATUSES = {"splitting", "pending", "loading_model", "encoding", "writing"}


def _remove_book_directory(path: Path, parent: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != parent.resolve():
        raise ValueError("书籍数据目录不安全，无法删除")
    shutil.rmtree(path)


class BookDeletionService:
    def __init__(
        self,
        imports: BookImportService,
        summaries: SummaryService,
        chats: ChatService,
    ) -> None:
        self._imports = imports
        self._summaries = summaries
        self._chats = chats

    def delete_book(self, book_id: str) -> None:
        if BOOK_ID_PATTERN.fullmatch(book_id) is None:
            raise ValueError("无效的 book_id")
        book_path = BookPaths(book_id)
        vector_root = config.DATABASE_DIR / "vector_db"

        # Hold the start/state/chat locks so a new job cannot start between the
        # idle checks and removal of its files.
        with self._imports._start_lock, self._summaries._state_lock, self._chats._conversations_lock:
            if not book_path.root.is_dir():
                raise ValueError("找不到书籍")
            state_file = book_path.embedding_state_file
            if not state_file.exists():
                state_file = book_path.root / IMPORT_STATE_FILE
            if state_file.exists():
                state = self._imports._read_state(state_file)
                if state.get("status") in RUNNING_EMBEDDING_STATUSES:
                    raise ValueError("该书正在导入或生成模糊搜索索引，请完成后再删除")
            summary_job = read_summary_state(book_path)["job"]
            if summary_job and summary_job["status"] in RUNNING_SUMMARY_STATUSES:
                raise ValueError("该书的总结任务正在运行，请完成后再删除")

            conversation_ids = [
                conversation_id
                for conversation_id, conversation in self._chats._conversations.items()
                if conversation.book_id == book_id
            ]
            if any(self._chats._locks[conversation_id].locked() for conversation_id in conversation_ids):
                raise ValueError("该书有正在生成的回复，请先停止生成")

            _remove_book_directory(book_path.vector_db_dir, vector_root)
            if vector_root.exists():
                for path in [
                    vector_root / f".building-{book_id}",
                    *vector_root.glob(f".building-{book_id}-*"),
                ]:
                    _remove_book_directory(path, vector_root)
            _remove_book_directory(book_path.root, config.BOOKS_DIR)
            self._chats._store.delete_book_conversations(book_id)
            self._chats._deleted_book_ids.add(book_id)
            for conversation_id in conversation_ids:
                self._chats._conversations.pop(conversation_id, None)
                self._chats._locks.pop(conversation_id, None)
                self._chats._cancel_events.pop(conversation_id, None)

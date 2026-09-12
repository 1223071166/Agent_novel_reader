"""SQLite persistence for conversations and messages."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from services.models import Conversation, Message


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes itself after a transaction context ends."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class ConversationStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls TEXT,
                    tool_call_id TEXT,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_book_id
                    ON conversations(book_id);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                    ON messages(conversation_id);
                """
            )

    def create_conversation(self, conversation_id: str, book_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO conversations (id, book_id) VALUES (?, ?)",
                (conversation_id, book_id),
            )

    def save_message(self, conversation_id: str, message: Message) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO messages (
                    id,
                    conversation_id,
                    role,
                    content,
                    tool_calls,
                    tool_call_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    conversation_id,
                    message.role,
                    message.content,
                    json.dumps(message.tool_calls, ensure_ascii=False)
                    if message.tool_calls is not None
                    else None,
                    message.tool_call_id,
                ),
            )

    def load_conversation(self, conversation_id: str, book_id: str) -> Conversation | None:
        with self._connect() as connection:
            conversation_row = connection.execute(
                "SELECT id, book_id FROM conversations WHERE id = ? AND book_id = ?",
                (conversation_id, book_id),
            ).fetchone()

            if conversation_row is None:
                return None

            rows = connection.execute(
                """
                SELECT id, role, content, tool_calls, tool_call_id
                FROM messages
                WHERE conversation_id = ?
                ORDER BY rowid
                """,
                (conversation_id,),
            ).fetchall()

        return Conversation(
            id=conversation_row["id"],
            book_id=conversation_row["book_id"],
            messages=[self._message_from_row(row) for row in rows],
        )

    def load_all_conversations(self) -> dict[str, Conversation]:
        with self._connect() as connection:
            conversation_rows = connection.execute(
                "SELECT id, book_id FROM conversations ORDER BY rowid"
            ).fetchall()

            message_rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, tool_calls, tool_call_id
                FROM messages
                ORDER BY conversation_id, rowid
                """
            ).fetchall()

        conversations = {
            row["id"]: Conversation(id=row["id"], book_id=row["book_id"])
            for row in conversation_rows
        }

        for row in message_rows:
            conversations[row["conversation_id"]].messages.append(
                self._message_from_row(row)
            )

        return conversations

    def delete_conversation(self, conversation_id: str, book_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM conversations WHERE id = ? AND book_id = ?",
                (conversation_id, book_id),
            )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Message:
        tool_calls = (
            json.loads(row["tool_calls"])
            if row["tool_calls"] is not None
            else None
        )
        return Message(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
        )

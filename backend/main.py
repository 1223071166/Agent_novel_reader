import json
from typing import Iterator
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.chat_service import ChatService
from services.book_import_service import BookImportService, IMPORT_STATE_FILE
from services.models import ChatEvent, Conversation
from config import BOOKS_DIR, SELECTED_BOOK_FILE
#部署方法： uvicorn backend.main:app --reload
app = FastAPI()
chat_service = ChatService()
book_import_service = BookImportService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/hello")
def hello():
    return {"message": "Hello from FastAPI!"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


class ChatRequest(BaseModel):
    book_id: str
    conversation_id: str
    message: str
class CancelRequest(BaseModel):
    book_id: str
    conversation_id: str


class BookInfoRequest(BaseModel):
    content: str


def _available_book_ids() -> list[str]:
    if not BOOKS_DIR.exists():
        return []
    return sorted(
        path.name
        for path in BOOKS_DIR.iterdir()
        if path.is_dir() and not (path / IMPORT_STATE_FILE).exists()
    )


def _all_book_ids() -> list[str]:
    if not BOOKS_DIR.exists():
        return []
    return sorted(path.name for path in BOOKS_DIR.iterdir() if path.is_dir())


def _require_book_id(value: str) -> str:
    book_id = value.strip()
    if not book_id:
        raise HTTPException(status_code=422, detail="book_id 不能为空")
    if book_id not in _available_book_ids():
        raise HTTPException(status_code=404, detail=f"找不到书籍：{book_id}")
    return book_id

def _sse_stream(events: Iterator[ChatEvent]) -> Iterator[str]:
    for event in events:
        yield (
            f"event: {event.event}\n"
            f"data: {json.dumps(event.data, ensure_ascii=False, default=str)}\n\n"
        )


def _conversation_payload(conversation: Conversation) -> dict:
    # System messages contain the model prompt and novel metadata. They are
    # needed by the model, but should not be sent to the browser.
    messages = []
    for message in conversation.messages:
        if message.role == "system":
            continue
        messages.append({
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "tool_calls": message.tool_calls,
            "tool_call_id": message.tool_call_id,
        })
    return {
        "id": conversation.id,
        "book_id": conversation.book_id,
        "title": conversation.title,
        "messages": messages,
    }


@app.get("/api/books")
def get_books():
    book_ids = _available_book_ids()
    all_book_ids = _all_book_ids()
    importing_book_ids = sorted(set(all_book_ids) - set(book_ids))
    selected_book_id = (
        SELECTED_BOOK_FILE.read_text(encoding="utf-8").strip()
        if SELECTED_BOOK_FILE.exists()
        else ""
    )
    if selected_book_id not in book_ids:
        selected_book_id = book_ids[0] if book_ids else None
    return {
        "books": all_book_ids,
        "importing_book_ids": importing_book_ids,
        "selected_book_id": selected_book_id,
    }


@app.post("/api/book-imports", status_code=201)
async def create_book_import(
    request: Request,
    x_file_name: str = Header(...),
):
    try:
        return book_import_service.create_import(
            unquote(x_file_name),
            await request.body(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/book-imports/{book_id}/info")
def save_book_info(book_id: str, request: BookInfoRequest):
    try:
        return book_import_service.save_info(book_id, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/book-imports/{book_id}/embedding", status_code=202)
def start_book_embedding(book_id: str):
    try:
        return book_import_service.start_embedding(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/book-imports/{book_id}/embedding")
def get_book_embedding_status(book_id: str):
    try:
        return book_import_service.get_status(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/book-imports/{book_id}")
def get_book_import(book_id: str):
    try:
        return book_import_service.get_import(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/book-imports/{book_id}")
def discard_book_import(book_id: str):
    try:
        book_import_service.discard_import(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/conversations")
def get_conversations(book_id: str):
    book_id = _require_book_id(book_id)
    return {"conversations": [
        _conversation_payload(conversation)
        for conversation in chat_service.get_conversations(book_id)
    ]}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, book_id: str):
    book_id = _require_book_id(book_id)
    conversation_id = conversation_id.strip()
    if not conversation_id:
        raise HTTPException(status_code=422, detail="conversation_id 不能为空")
    try:
        chat_service.delete_conversation(book_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/chat")
def chat(request: ChatRequest):
    book_id = _require_book_id(request.book_id)
    conversation_id = request.conversation_id.strip()
    message = request.message.strip()
    if not conversation_id or not message:
        raise HTTPException(status_code=422, detail="conversation_id 和 message 不能为空")

    return StreamingResponse(
        _sse_stream(chat_service.stream_message(book_id, conversation_id, message)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/api/cancel")
def cancel_chat(request: CancelRequest):
    book_id = _require_book_id(request.book_id)
    conversation_id = request.conversation_id.strip()
    try:
        chat_service.cancel_conversation(book_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}

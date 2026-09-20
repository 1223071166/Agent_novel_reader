import json
import uuid
from typing import Iterator
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StrictBool, StrictInt

from services.chat_service import ChatService
from services.app_settings import get_app_settings, save_app_settings
from services.book_import_service import BookImportService, IMPORT_STATE_FILE
from services.summary_service import SummaryService
from services.reading_service import get_reading_settings, save_reading_settings
from services.models import ChatEvent, Conversation
from config import BOOKS_DIR, SELECTED_BOOK_FILE, BookPaths
from tool_results import load_tool_result_data, make_tool_result
#部署方法： uvicorn backend.main:app --reload
app = FastAPI()
summary_service = SummaryService()
chat_service = ChatService()
book_import_service = BookImportService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    name: str
    content: str


class BookSelectionRequest(BaseModel):
    book_id: str


class SummarySettingsRequest(BaseModel):
    enabled: StrictBool


class ReadingSettingsRequest(BaseModel):
    spoiler_mode: StrictBool
    read_through_chapter: StrictInt


class AppSettingsRequest(BaseModel):
    tool_round_limit: StrictInt


class SummaryTargetRequest(BaseModel):
    level: str
    start: StrictInt | None = None


class SummaryTargetsRequest(BaseModel):
    targets: list[SummaryTargetRequest]


def _summary_targets(request: SummaryTargetsRequest) -> list[dict]:
    return [
        {"level": target.level, "start": target.start}
        for target in request.targets
    ]


@app.get("/api/settings")
def load_app_settings():
    try:
        return get_app_settings()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/settings")
def update_app_settings(request: AppSettingsRequest):
    try:
        return save_app_settings(request.tool_round_limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


def _book_names(book_ids: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for book_id in book_ids:
        book_path = BookPaths(book_id)
        if book_path.name_file.exists():
            name = book_path.name_file.read_text(encoding="utf-8").strip()
            if name:
                names[book_id] = name
                continue
        marker = book_path.root / IMPORT_STATE_FILE
        if marker.exists():
            try:
                name = json.loads(marker.read_text(encoding="utf-8")).get("name")
            except (OSError, json.JSONDecodeError):
                name = None
            if isinstance(name, str) and name.strip():
                names[book_id] = name.strip()
                continue
        names[book_id] = book_id
    return names


def _require_book_id(value: str) -> str:
    book_id = value.strip()
    if not book_id:
        raise HTTPException(status_code=422, detail="book_id 不能为空")
    if book_id not in _available_book_ids():
        raise HTTPException(status_code=404, detail=f"找不到书籍：{book_id}")
    return book_id


def _write_selected_book_id(book_id: str) -> None:
    SELECTED_BOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SELECTED_BOOK_FILE.with_name(
        f".{SELECTED_BOOK_FILE.name}.{uuid.uuid4().hex}.tmp"
    )
    temporary_path.write_text(book_id + "\n", encoding="utf-8")
    temporary_path.replace(SELECTED_BOOK_FILE)

def _sse_stream(events: Iterator[ChatEvent]) -> Iterator[str]:
    for event in events:
        yield (
            f"event: {event.event}\n"
            f"data: {json.dumps(event.data, ensure_ascii=False, default=str)}\n\n"
        )


def _conversation_payload(conversation: Conversation) -> dict:
    # System messages contain the model prompt and novel metadata. They are
    # needed by the model, but should not be sent to the browser.
    # And tool messages are not sent to the browser either, but their tool results are.
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
            "tool_status": message.tool_status,
            "tool_result": (
                make_tool_result(load_tool_result_data(message.content))
                if message.role == "tool" and message.content is not None
                else None
            ),
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
        if selected_book_id is None:
            SELECTED_BOOK_FILE.unlink(missing_ok=True)
        else:
            _write_selected_book_id(selected_book_id)
    return {
        "books": all_book_ids,
        "book_names": _book_names(all_book_ids),
        "importing_book_ids": importing_book_ids,
        "selected_book_id": selected_book_id,
    }


@app.put("/api/books/selected")
def save_selected_book(request: BookSelectionRequest):
    book_id = _require_book_id(request.book_id)
    _write_selected_book_id(book_id)
    return {"selected_book_id": book_id}


@app.get("/api/books/{book_id}/summaries")
def get_book_summaries(book_id: str):
    book_id = _require_book_id(book_id)
    try:
        return summary_service.get_overview(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/books/{book_id}/summary-settings")
def save_summary_settings(book_id: str, request: SummarySettingsRequest):
    book_id = _require_book_id(book_id)
    try:
        return summary_service.set_enabled(book_id, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/books/{book_id}/reading-settings")
def get_book_reading_settings(book_id: str):
    book_id = _require_book_id(book_id)
    try:
        return get_reading_settings(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/books/{book_id}/reading-settings")
def save_book_reading_settings(book_id: str, request: ReadingSettingsRequest):
    book_id = _require_book_id(book_id)
    try:
        return save_reading_settings(
            book_id,
            request.spoiler_mode,
            request.read_through_chapter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/books/{book_id}/summaries/plan")
def plan_book_summaries(book_id: str, request: SummaryTargetsRequest):
    book_id = _require_book_id(book_id)
    try:
        return summary_service.plan(book_id, _summary_targets(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/books/{book_id}/summary-jobs", status_code=202)
def start_book_summary_job(book_id: str, request: SummaryTargetsRequest):
    book_id = _require_book_id(book_id)
    try:
        return summary_service.start(book_id, _summary_targets(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        return book_import_service.save_info(book_id, request.name, request.content)
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

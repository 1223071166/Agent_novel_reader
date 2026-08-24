import json
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.chat_service import ChatEvent, ChatService
#部署方法： uvicorn backend.main:app --reload
app = FastAPI()
chat_service = ChatService()

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
    conversation_id: str
    message: str


def _sse_stream(events: Iterator[ChatEvent]) -> Iterator[str]:
    for event in events:
        yield (
            f"event: {event.event}\n"
            f"data: {json.dumps(event.data, ensure_ascii=False, default=str)}\n\n"
        )


@app.post("/api/chat")
def chat(request: ChatRequest):
    conversation_id = request.conversation_id.strip()
    message = request.message.strip()
    if not conversation_id or not message:
        raise HTTPException(status_code=422, detail="conversation_id 和 message 不能为空")

    return StreamingResponse(
        _sse_stream(chat_service.stream_message(conversation_id, message)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

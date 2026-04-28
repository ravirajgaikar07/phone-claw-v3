"""PhoneClaw FastAPI server."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

import agent
from memory import db
from tools.registry import registry
from utils.logger import get_logger

log = get_logger("server")

app = FastAPI(
    title="PhoneClaw",
    description="Lightweight AI agent system for Android",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ─────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str
    session_id: Optional[int] = Field(None, description="Session ID (uses active if omitted)")


class SessionCreateRequest(BaseModel):
    title: str = "New Session"


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "tools": len(registry),
        "sessions": len(db.list_sessions()),
    }


@app.get("/tools")
def list_tools():
    return {"tools": registry.get_all_metadata()}


@app.post("/task")
def run_task(req: TaskRequest):
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="Task cannot be empty")
    log.info("API task: %s", req.task[:100])
    try:
        result = agent.run(req.task, session_id=req.session_id)
        return {"result": result}
    except Exception as exc:
        log.error("Task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/sessions")
def list_sessions():
    return {"sessions": db.list_sessions()}


@app.post("/sessions")
def create_session(req: SessionCreateRequest):
    session = db.create_session(req.title)
    return {"session": session}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: int):
    sessions = db.list_sessions()
    if not any(s["id"] == session_id for s in sessions):
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/sessions/{session_id}/history")
def session_history(session_id: int):
    history = db.get_session_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return history
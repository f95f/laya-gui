import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "laya-config.json"
DB_PATH = ROOT / "data" / "laya_history.db"
DEFAULT_CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

app = FastAPI(title="Laya Decision Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/api/config":
        return JSONResponse(status_code=400, content={"detail": "Config body must be valid JSON containing a questions object."})
    return JSONResponse(status_code=422, content={"detail": "Invalid request body."})

_router = None
_router_lock = Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize() -> None:
    with db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_responses (
                id TEXT PRIMARY KEY, request_message_id TEXT NOT NULL REFERENCES messages(id),
                response_message_id TEXT NOT NULL REFERENCES messages(id),
                status TEXT NOT NULL, selected_choice TEXT, probability REAL,
                probabilities_json TEXT, confidence REAL, answer_confidence REAL,
                latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER,
                model_name TEXT, routing_json TEXT, raw_json TEXT, config_json TEXT NOT NULL,
                error TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS config_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, config_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)


initialize()


def validate_config(value: Any) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("questions"), dict) or not value["questions"]:
        raise HTTPException(400, "Config must contain a nonempty questions object.")
    for name, question in value["questions"].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(question, dict):
            raise HTTPException(400, "Every question needs a name and an object definition.")
        criteria = question.get("criteria")
        if (question.get("type") != "choice" or not isinstance(question.get("instructions"), str)
                or not question["instructions"].strip() or not isinstance(criteria, dict)
                or len(criteria) < 2 or any(not isinstance(k, str) or not k.strip()
                or not isinstance(v, str) or not v.strip() for k, v in criteria.items())):
            raise HTTPException(400, f"Question '{name}' needs type 'choice', instructions, and at least two nonempty criteria.")
    return value


def load_config() -> dict:
    try:
        return validate_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Config file contains invalid JSON: {exc.msg}") from exc


def get_router():
    global _router
    with _router_lock:
        if _router is None:
            from laya import Router
            _router = Router(max_loaded=1)
        return _router


class ClassifyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversationId: str | None = None
    configOverride: dict | None = None


@app.get("/api/config")
def get_config():
    return load_config()


@app.put("/api/config")
def put_config(value: dict):
    config = validate_config(value)
    encoded = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(encoded, encoding="utf-8")
    temp.replace(CONFIG_PATH)
    with db() as connection:
        connection.execute("INSERT INTO config_versions (config_json, created_at) VALUES (?, ?)", (encoded, now()))
    return config


@app.get("/api/config/default")
def get_default_config():
    return DEFAULT_CONFIG


def response_view(row: sqlite3.Row) -> dict:
    return {
        "status": row["status"], "choice": row["selected_choice"],
        "probability": row["probability"],
        "probabilities": json.loads(row["probabilities_json"] or "{}"),
        "confidence": row["confidence"], "answerConfidence": row["answer_confidence"],
        "latencyMs": row["latency_ms"], "inputTokens": row["input_tokens"],
        "outputTokens": row["output_tokens"], "model": row["model_name"],
        "routing": json.loads(row["routing_json"] or "null"),
        "raw": json.loads(row["raw_json"] or "null"), "config": json.loads(row["config_json"]),
        "error": row["error"], "timestamp": row["created_at"],
    }


@app.post("/api/classify")
def classify(payload: ClassifyRequest):
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Message cannot be blank.")
    config = validate_config(payload.configOverride) if payload.configOverride is not None else load_config()
    stamp = now()
    conversation_id = payload.conversationId or str(uuid.uuid4())
    request_id, response_id, record_id = (str(uuid.uuid4()) for _ in range(3))
    with db() as connection:
        if payload.conversationId:
            if not connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
                raise HTTPException(404, "Conversation not found.")
        else:
            title = message[:55] + ("..." if len(message) > 55 else "")
            connection.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (conversation_id, title, stamp, stamp))
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", (request_id, conversation_id, "user", message, stamp))

    start = time.perf_counter()
    error = None
    raw = None
    try:
        raw = get_router().predict({"message": message}, config["questions"], model="english")
        answers = raw.get("answers") or {}
        primary = answers.get("decision") or next(iter(answers.values()))
        choice = primary.get("choice")
        probabilities = primary.get("probabilities") or {}
        probability = probabilities.get(choice, primary.get("answer_confidence"))
        usage = raw.get("usage") or {}
        status = "ok"
    except Exception as exc:
        error = f"Laya could not classify this message: {exc}"
        primary, probabilities, usage, choice, probability = {}, {}, {}, None, None
        status = "error"
    latency = round((time.perf_counter() - start) * 1000, 2)
    response_stamp = now()
    model_name = (raw or {}).get("model")
    routing = (raw or {}).get("routing")
    with db() as connection:
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                           (response_id, conversation_id, "assistant", choice or error or "Unknown", response_stamp))
        connection.execute("""INSERT INTO model_responses VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            record_id, request_id, response_id, status, choice, probability,
            json.dumps(probabilities), primary.get("confidence"), primary.get("answer_confidence"),
            latency, usage.get("input_tokens"), usage.get("output_tokens"), model_name,
            json.dumps(routing), json.dumps(raw, default=str) if raw is not None else None,
            json.dumps(config), error, response_stamp,
        ))
        connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (response_stamp, conversation_id))
        row = connection.execute("SELECT * FROM model_responses WHERE id = ?", (record_id,)).fetchone()
    result = {"conversationId": conversation_id, "requestId": request_id, "responseId": response_id,
              "response": response_view(row)}
    if error:
        raise HTTPException(503, {"message": error, **result})
    return result


@app.get("/api/conversations")
def list_conversations():
    with db() as connection:
        rows = connection.execute("""SELECT c.*, COUNT(m.id) AS message_count,
            (SELECT content FROM messages WHERE conversation_id = c.id AND role = 'user'
             ORDER BY created_at DESC, rowid DESC LIMIT 1) AS latest_message
            FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id ORDER BY c.updated_at DESC""").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    with db() as connection:
        conversation = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not conversation:
            raise HTTPException(404, "Conversation not found.")
        rows = connection.execute("""SELECT m.*, r.id AS result_id FROM messages m
            LEFT JOIN model_responses r ON r.response_message_id = m.id
            WHERE m.conversation_id = ? ORDER BY m.created_at, m.rowid""", (conversation_id,)).fetchall()
        messages = []
        for row in rows:
            item = {"id": row["id"], "role": row["role"], "content": row["content"], "timestamp": row["created_at"]}
            if row["result_id"]:
                record = connection.execute("SELECT * FROM model_responses WHERE id = ?", (row["result_id"],)).fetchone()
                item["response"] = response_view(record)
            messages.append(item)
    return {"id": conversation_id, "title": conversation["title"], "messages": messages}


@app.get("/api/dashboard")
def dashboard():
    with db() as connection:
        stats = connection.execute("""SELECT COUNT(*) AS total_requests,
            COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) AS failed_requests,
            AVG(latency_ms) AS average_latency_ms, AVG(confidence) AS average_confidence,
            AVG(answer_confidence) AS average_answer_confidence,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens
            FROM model_responses""").fetchone()
        choices = connection.execute("""SELECT selected_choice AS choice, COUNT(*) AS count
            FROM model_responses WHERE status = 'ok' GROUP BY selected_choice ORDER BY count DESC""").fetchall()
        recent = connection.execute("""SELECT r.created_at AS timestamp, r.selected_choice AS choice,
            r.probability, r.latency_ms AS latencyMs, r.status, m.content AS message,
            m.conversation_id AS conversationId FROM model_responses r
            JOIN messages m ON m.id = r.request_message_id
            ORDER BY r.created_at DESC LIMIT 20""").fetchall()
    return {"stats": dict(stats), "choices": [dict(row) for row in choices],
            "recent": [dict(row) for row in recent]}

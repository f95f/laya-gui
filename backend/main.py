import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
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
DEFAULT_MODEL_ID = "laya:english"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_OLLAMA_MODELS = "granite4.2:3b,qwen3.5:0.8b,qwen3.5:4b"
OLLAMA_MODEL_IDS = [
    item.strip() for item in os.getenv("OLLAMA_MODEL_IDS", DEFAULT_OLLAMA_MODELS).split(",") if item.strip()
]

app = FastAPI(title="Laya Decision Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/config"):
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


def models() -> list[dict[str, str]]:
    items = [{"id": DEFAULT_MODEL_ID, "name": "Laya English", "provider": "laya", "model": "english"}]
    items.extend({"id": f"ollama:{name}", "name": f"Ollama {name}", "provider": "ollama", "model": name} for name in OLLAMA_MODEL_IDS)
    return items


def model_by_id(model_id: str | None) -> dict[str, str]:
    selected = model_id or DEFAULT_MODEL_ID
    for item in models():
        if item["id"] == selected:
            return item
    raise HTTPException(400, f"Unknown model '{selected}'.")


def add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
            CREATE TABLE IF NOT EXISTS decision_configs (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL,
                default_model_id TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        add_column_if_missing(connection, "model_responses", "config_id", "TEXT")
        add_column_if_missing(connection, "model_responses", "config_name", "TEXT")
        add_column_if_missing(connection, "model_responses", "model_id", "TEXT")
        add_column_if_missing(connection, "model_responses", "provider", "TEXT")
        if connection.execute("SELECT COUNT(*) FROM decision_configs").fetchone()[0] == 0:
            stamp = now()
            encoded = json.dumps(validate_config(DEFAULT_CONFIG), ensure_ascii=False)
            connection.execute(
                """INSERT INTO decision_configs
                (id, name, config_json, default_model_id, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (str(uuid.uuid4()), DEFAULT_CONFIG.get("name") or "Default decision config", encoded, DEFAULT_MODEL_ID, stamp, stamp),
            )


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


def config_view(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "config": json.loads(row["config_json"]),
        "defaultModelId": row["default_model_id"], "isActive": bool(row["is_active"]),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def active_config(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM decision_configs WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1").fetchone()
    if row:
        return row
    row = connection.execute("SELECT * FROM decision_configs ORDER BY updated_at DESC LIMIT 1").fetchone()
    if not row:
        raise HTTPException(500, "No decision config exists.")
    connection.execute("UPDATE decision_configs SET is_active = CASE WHEN id = ? THEN 1 ELSE 0 END", (row["id"],))
    return row


def selected_config(connection: sqlite3.Connection, config_id: str | None) -> sqlite3.Row:
    if config_id:
        row = connection.execute("SELECT * FROM decision_configs WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Decision config not found.")
        return row
    return active_config(connection)


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
    configId: str | None = None
    modelId: str | None = None
    configOverride: dict | None = None


class ConfigProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: dict
    defaultModelId: str = DEFAULT_MODEL_ID
    isActive: bool = False


initialize()


@app.get("/api/models")
def list_models():
    return models()


@app.get("/api/configs")
def list_configs():
    with db() as connection:
        rows = connection.execute("SELECT * FROM decision_configs ORDER BY is_active DESC, updated_at DESC").fetchall()
    return [config_view(row) for row in rows]


@app.get("/api/configs/{config_id}")
def get_config_profile(config_id: str):
    with db() as connection:
        row = selected_config(connection, config_id)
    return config_view(row)


@app.post("/api/configs")
def create_config_profile(payload: ConfigProfileRequest):
    config = validate_config(payload.config)
    model_by_id(payload.defaultModelId)
    stamp = now()
    config_id = str(uuid.uuid4())
    encoded = json.dumps(config, ensure_ascii=False)
    with db() as connection:
        if payload.isActive:
            connection.execute("UPDATE decision_configs SET is_active = 0")
        connection.execute(
            """INSERT INTO decision_configs
            (id, name, config_json, default_model_id, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (config_id, payload.name.strip(), encoded, payload.defaultModelId, int(payload.isActive), stamp, stamp),
        )
        connection.execute("INSERT INTO config_versions (config_json, created_at) VALUES (?, ?)", (encoded, stamp))
        row = connection.execute("SELECT * FROM decision_configs WHERE id = ?", (config_id,)).fetchone()
    return config_view(row)


@app.put("/api/configs/{config_id}")
def update_config_profile(config_id: str, payload: ConfigProfileRequest):
    config = validate_config(payload.config)
    model_by_id(payload.defaultModelId)
    stamp = now()
    encoded = json.dumps(config, ensure_ascii=False)
    with db() as connection:
        if not connection.execute("SELECT 1 FROM decision_configs WHERE id = ?", (config_id,)).fetchone():
            raise HTTPException(404, "Decision config not found.")
        if payload.isActive:
            connection.execute("UPDATE decision_configs SET is_active = 0")
        connection.execute(
            """UPDATE decision_configs SET name = ?, config_json = ?, default_model_id = ?,
            is_active = ?, updated_at = ? WHERE id = ?""",
            (payload.name.strip(), encoded, payload.defaultModelId, int(payload.isActive), stamp, config_id),
        )
        connection.execute("INSERT INTO config_versions (config_json, created_at) VALUES (?, ?)", (encoded, stamp))
        row = connection.execute("SELECT * FROM decision_configs WHERE id = ?", (config_id,)).fetchone()
    return config_view(row)


@app.post("/api/configs/{config_id}/activate")
def activate_config_profile(config_id: str):
    stamp = now()
    with db() as connection:
        if not connection.execute("SELECT 1 FROM decision_configs WHERE id = ?", (config_id,)).fetchone():
            raise HTTPException(404, "Decision config not found.")
        connection.execute("UPDATE decision_configs SET is_active = 0")
        connection.execute("UPDATE decision_configs SET is_active = 1, updated_at = ? WHERE id = ?", (stamp, config_id))
        row = connection.execute("SELECT * FROM decision_configs WHERE id = ?", (config_id,)).fetchone()
    return config_view(row)


@app.delete("/api/configs/{config_id}")
def delete_config_profile(config_id: str):
    with db() as connection:
        row = connection.execute("SELECT * FROM decision_configs WHERE id = ?", (config_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Decision config not found.")
        if row["is_active"]:
            raise HTTPException(400, "Cannot delete the active config. Activate another config first.")
        if connection.execute("SELECT COUNT(*) FROM decision_configs").fetchone()[0] <= 1:
            raise HTTPException(400, "Cannot delete the last config.")
        connection.execute("DELETE FROM decision_configs WHERE id = ?", (config_id,))
    return {"ok": True}


@app.get("/api/config")
def get_config():
    with db() as connection:
        return json.loads(active_config(connection)["config_json"])


@app.put("/api/config")
def put_config(value: dict):
    config = validate_config(value)
    with db() as connection:
        row = active_config(connection)
        payload = ConfigProfileRequest(
            name=row["name"], config=config, defaultModelId=row["default_model_id"], isActive=True,
        )
    return update_config_profile(row["id"], payload)["config"]


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
        "modelId": row["model_id"] or row["model_name"], "provider": row["provider"] or "laya",
        "configId": row["config_id"], "configName": row["config_name"],
        "routing": json.loads(row["routing_json"] or "null"),
        "raw": json.loads(row["raw_json"] or "null"), "config": json.loads(row["config_json"]),
        "error": row["error"], "timestamp": row["created_at"],
    }


def primary_question(config: dict) -> tuple[str, dict]:
    questions = config["questions"]
    if "decision" in questions:
        return "decision", questions["decision"]
    name = next(iter(questions))
    return name, questions[name]


def normalize_laya(message: str, config: dict, model: dict) -> dict:
    raw = get_router().predict({"message": message}, config["questions"], model=model["model"])
    answers = raw.get("answers") or {}
    question_name, _ = primary_question(config)
    primary = answers.get(question_name) or next(iter(answers.values()))
    choice = primary.get("choice")
    probabilities = primary.get("probabilities") or {}
    probability = probabilities.get(choice, primary.get("answer_confidence"))
    usage = raw.get("usage") or {}
    return {
        "choice": choice, "probability": probability, "probabilities": probabilities,
        "confidence": primary.get("confidence"), "answerConfidence": primary.get("answer_confidence"),
        "inputTokens": usage.get("input_tokens"), "outputTokens": usage.get("output_tokens"),
        "modelName": raw.get("model") or model["name"], "routing": raw.get("routing"), "raw": raw,
    }


def strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def ollama_prompt(message: str, config: dict) -> str:
    question_name, question = primary_question(config)
    criteria = "\n".join(f"- {key}: {description}" for key, description in question["criteria"].items())
    return (
        "You are a strict decision classifier. Return only valid JSON and no markdown.\n"
        f"Question: {question_name}\n"
        f"Instructions: {question['instructions']}\n"
        "Allowed choices:\n"
        f"{criteria}\n\n"
        "Return this JSON shape exactly: "
        '{"choice":"ONE_ALLOWED_CHOICE","confidence":0.0,"probabilities":{"ONE_ALLOWED_CHOICE":0.0},"reason":"short reason"}\n'
        "The choice must be one of the allowed choices. Confidence must be between 0 and 1.\n"
        f"Message: {message}"
    )


def normalize_ollama(message: str, config: dict, model: dict) -> dict:
    body = json.dumps({
        "model": model["model"],
        "messages": [{"role": "user", "content": ollama_prompt(message, config)}],
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    content = (raw.get("message") or {}).get("content") or raw.get("response")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned no message content.")
    try:
        answer = json.loads(strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {exc.msg}") from exc
    _, question = primary_question(config)
    allowed = set(question["criteria"].keys())
    choice = answer.get("choice")
    if choice not in allowed:
        raise RuntimeError(f"Ollama returned unknown choice '{choice}'.")
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        raise RuntimeError("Ollama response must include confidence between 0 and 1.")
    probabilities = answer.get("probabilities") if isinstance(answer.get("probabilities"), dict) else {}
    probability = probabilities.get(choice, confidence)
    return {
        "choice": choice, "probability": probability, "probabilities": probabilities,
        "confidence": confidence, "answerConfidence": probability,
        "inputTokens": raw.get("prompt_eval_count"), "outputTokens": raw.get("eval_count"),
        "modelName": model["model"], "routing": {"provider": "ollama", "baseUrl": OLLAMA_BASE_URL},
        "raw": {"ollama": raw, "parsed": answer},
    }


def run_model(message: str, config: dict, model: dict) -> dict:
    if model["provider"] == "laya":
        return normalize_laya(message, config, model)
    if model["provider"] == "ollama":
        return normalize_ollama(message, config, model)
    raise RuntimeError(f"Unsupported provider '{model['provider']}'.")


@app.post("/api/classify")
def classify(payload: ClassifyRequest):
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Message cannot be blank.")
    stamp = now()
    conversation_id = payload.conversationId or str(uuid.uuid4())
    request_id, response_id, record_id = (str(uuid.uuid4()) for _ in range(3))
    with db() as connection:
        if payload.configOverride is not None:
            config = validate_config(payload.configOverride)
            config_id, config_name, default_model = None, "Override", DEFAULT_MODEL_ID
        else:
            config_row = selected_config(connection, payload.configId)
            config = validate_config(json.loads(config_row["config_json"]))
            config_id, config_name, default_model = config_row["id"], config_row["name"], config_row["default_model_id"]
        model = model_by_id(payload.modelId or default_model)
        if payload.conversationId:
            if not connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
                raise HTTPException(404, "Conversation not found.")
        else:
            title = message[:55] + ("..." if len(message) > 55 else "")
            connection.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (conversation_id, title, stamp, stamp))
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", (request_id, conversation_id, "user", message, stamp))

    start = time.perf_counter()
    error = None
    normalized = {}
    try:
        normalized = run_model(message, config, model)
        status = "ok"
        choice = normalized["choice"]
    except Exception as exc:
        error = f"{model['name']} could not classify this message: {exc}"
        status = "error"
        choice = None
    latency = round((time.perf_counter() - start) * 1000, 2)
    response_stamp = now()
    with db() as connection:
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                           (response_id, conversation_id, "assistant", choice or error or "Unknown", response_stamp))
        connection.execute("""INSERT INTO model_responses
            (id, request_message_id, response_message_id, status, selected_choice, probability,
             probabilities_json, confidence, answer_confidence, latency_ms, input_tokens,
             output_tokens, model_name, routing_json, raw_json, config_json, error, created_at,
             config_id, config_name, model_id, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            record_id, request_id, response_id, status, choice, normalized.get("probability"),
            json.dumps(normalized.get("probabilities") or {}), normalized.get("confidence"),
            normalized.get("answerConfidence"), latency, normalized.get("inputTokens"), normalized.get("outputTokens"),
            normalized.get("modelName") or model["name"], json.dumps(normalized.get("routing")),
            json.dumps(normalized.get("raw"), default=str) if normalized.get("raw") is not None else None,
            json.dumps(config), error, response_stamp, config_id, config_name, model["id"], model["provider"],
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
def dashboard(configId: str | None = None, modelId: str | None = None):
    filters, values = [], []
    if configId:
        filters.append("config_id = ?")
        values.append(configId)
    if modelId:
        filters.append("model_id = ?")
        values.append(modelId)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with db() as connection:
        stats = connection.execute(f"""SELECT COUNT(*) AS total_requests,
            COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) AS failed_requests,
            AVG(latency_ms) AS average_latency_ms, AVG(confidence) AS average_confidence,
            AVG(answer_confidence) AS average_answer_confidence,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens
            FROM model_responses {where}""", values).fetchone()
        choices = connection.execute(f"""SELECT selected_choice AS choice, COUNT(*) AS count
            FROM model_responses {where} {'AND' if where else 'WHERE'} status = 'ok'
            GROUP BY selected_choice ORDER BY count DESC""", values).fetchall()
        config_groups = connection.execute(f"""SELECT COALESCE(config_name, 'Legacy config') AS name,
            COALESCE(config_id, 'legacy') AS id, COUNT(*) AS count
            FROM model_responses {where} GROUP BY COALESCE(config_id, 'legacy'), COALESCE(config_name, 'Legacy config')
            ORDER BY count DESC""", values).fetchall()
        model_groups = connection.execute(f"""SELECT COALESCE(model_id, model_name, 'legacy') AS id,
            COALESCE(model_name, model_id, 'Legacy model') AS name, COALESCE(provider, 'laya') AS provider,
            COUNT(*) AS count FROM model_responses {where}
            GROUP BY COALESCE(model_id, model_name, 'legacy'), COALESCE(model_name, model_id, 'Legacy model'), COALESCE(provider, 'laya')
            ORDER BY count DESC""", values).fetchall()
        recent = connection.execute(f"""SELECT r.created_at AS timestamp, r.selected_choice AS choice,
            r.probability, r.latency_ms AS latencyMs, r.status, r.config_name AS configName,
            r.model_name AS modelName, r.provider, m.content AS message,
            m.conversation_id AS conversationId FROM model_responses r
            JOIN messages m ON m.id = r.request_message_id
            {where} ORDER BY r.created_at DESC LIMIT 20""", values).fetchall()
    return {"stats": dict(stats), "choices": [dict(row) for row in choices],
            "configs": [dict(row) for row in config_groups], "models": [dict(row) for row in model_groups],
            "recent": [dict(row) for row in recent]}

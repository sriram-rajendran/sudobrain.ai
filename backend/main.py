"""SudoBrain backend server — handles audio processing, transcription, and knowledge extraction."""

import json
import logging
import os
import re
import time
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.processing.audio_processor import process_audio, mix_meeting_audio
from backend.transcription.sarvam_client import transcribe_short, transcribe_meeting
from backend.ai.local_llm_engine import extract_knowledge as local_llm_extract
from backend.storage import database as db

# ── Logging setup ──

LOG_DIR = os.path.join(os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain")), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "sudobrain.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("sudobrain")

app = FastAPI(title="SudoBrain", version="0.4.0")

# ── Authentication Middleware ──

API_TOKEN = os.getenv("SUDOBRAIN_API_TOKEN", "")
TRUST_LOCALHOST = os.getenv("SUDOBRAIN_TRUST_LOCALHOST", "true").strip().lower() not in {"0", "false", "no", "off"}

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/fathom/webhook"}

REQUEST_METRICS = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "total_requests": 0,
    "by_path": {},
    "by_status": {},
    "recent": [],
}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Collect local-only request metrics without external telemetry."""

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            path = request.url.path
            REQUEST_METRICS["total_requests"] += 1
            REQUEST_METRICS["by_path"][path] = REQUEST_METRICS["by_path"].get(path, 0) + 1
            status_key = str(status_code)
            REQUEST_METRICS["by_status"][status_key] = REQUEST_METRICS["by_status"].get(status_key, 0) + 1
            recent = REQUEST_METRICS["recent"]
            recent.append({
                "method": request.method,
                "path": path,
                "status": status_code,
                "elapsed_ms": elapsed_ms,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            del recent[:-200]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small local quota guard for open-source/default deployments."""

    def __init__(self, app, requests_per_minute: int | None = None):
        super().__init__(app)
        try:
            raw_limit = requests_per_minute if requests_per_minute is not None else int(os.getenv("SUDOBRAIN_RATE_LIMIT_PER_MINUTE", "120"))
        except ValueError:
            raw_limit = 120
        self.requests_per_minute = max(0, raw_limit)
        self.window_seconds = 60
        self._hits: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        if self.requests_per_minute <= 0 or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = request.headers.get("Authorization", "")
        client_host = request.client.host if request.client else "unknown"
        identity = hashlib.sha256(f"{client_host}:{token}".encode("utf-8")).hexdigest()
        now = time.time()
        window_start = now - self.window_seconds
        hits = [ts for ts in self._hits.get(identity, []) if ts >= window_start]

        if len(hits) >= self.requests_per_minute:
            retry_after = max(1, int(self.window_seconds - (now - hits[0])))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"detail": "Rate limit exceeded", "retry_after_seconds": retry_after},
            )

        hits.append(now)
        self._hits[identity] = hits
        return await call_next(request)


class RBACMiddleware(BaseHTTPMiddleware):
    """Enforce coarse local roles when auth mode is configured beyond owner."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        role = os.getenv("SUDOBRAIN_LOCAL_ROLE", "owner").strip().lower() or "owner"
        if role == "owner":
            return await call_next(request)
        method = request.method.upper()
        if role == "viewer" and method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse(status_code=403, content={"detail": "Viewer role is read-only"})
        if role == "editor" and request.url.path.startswith(("/admin", "/security")):
            return JSONResponse(status_code=403, content={"detail": "Editor role cannot access admin/security endpoints"})
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths
        if path in PUBLIC_PATHS or not API_TOKEN:
            return await call_next(request)

        # Check bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {API_TOKEN}":
            return await call_next(request)

        # Allow localhost without token for Swift app/browser-extension compatibility.
        client_host = request.client.host if request.client else ""
        if TRUST_LOCALHOST and client_host in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RBACMiddleware)
app.add_middleware(ObservabilityMiddleware)


CONFIG_PATH = Path(DATA_DIR if "DATA_DIR" in globals() else os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain"))) / "config.json"


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _load_local_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        logger.warning("Could not read local config: %s", e)
    return {}


def _save_local_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True))


@app.on_event("startup")
def startup_event():
    """Start heartbeat scheduler and initialize services."""
    from backend.heartbeat.engine import start_scheduler
    start_scheduler()
    from backend.storage.resilience import check_database_integrity
    integrity = check_database_integrity()
    logger.info("DB integrity: %s, %d tables", integrity["integrity"], integrity["tables"])

    # Initialize Neo4j schema if available
    try:
        from backend.graph.neo4j_client import init_schema, is_available as neo4j_ok
        if neo4j_ok():
            init_schema()
            logger.info("Neo4j knowledge graph connected")
        else:
            logger.info("Neo4j not available — graph features disabled")
    except Exception as e:
        logger.warning("Neo4j init skipped: %s", e)

    # Initialize Slack tables
    try:
        from backend.slack.schema import init_slack_tables
        init_slack_tables()
        logger.info("Slack tables initialized")
    except Exception as e:
        logger.warning("Slack init skipped: %s", e)

    # Initialize Gmail tables
    try:
        from backend.gmail.ingest import init_gmail_tables
        init_gmail_tables()
        logger.info("Gmail tables initialized")
    except Exception as e:
        logger.warning("Gmail init skipped: %s", e)

    # Initialize Linear tables
    try:
        from backend.linear.ingest import init_linear_tables
        init_linear_tables()
        logger.info("Linear tables initialized")
    except Exception as e:
        logger.warning("Linear init skipped: %s", e)

    # Detect available Ollama models for routing
    try:
        from backend.ai.model_router import _get_available_models
        models = _get_available_models()
        logger.info("Ollama models available: %s", sorted(models))
    except Exception as e:
        logger.warning("Model router init skipped: %s", e)


@app.on_event("shutdown")
def shutdown_event():
    """Stop heartbeat scheduler and close connections."""
    from backend.heartbeat.engine import stop_scheduler
    stop_scheduler()
    try:
        from backend.graph.neo4j_client import close as close_neo4j
        close_neo4j()
    except Exception:
        pass

DATA_DIR = os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain"))
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")


def _save_promise(transcript_id: str, item: dict):
    """Save a promise to the database."""
    conn = db.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id TEXT,
                promised_by_name TEXT,
                promised_to_name TEXT,
                description TEXT NOT NULL,
                detected_text TEXT,
                due_date DATE,
                status TEXT DEFAULT 'pending',
                reminder_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing = conn.execute(
            """
            SELECT id FROM promises
            WHERE transcript_id = ?
              AND LOWER(REGEXP_REPLACE(COALESCE(description, ''), '\\s+', ' ', 'g')) =
                  LOWER(REGEXP_REPLACE(COALESCE(?, ''), '\\s+', ' ', 'g'))
              AND COALESCE(LOWER(promised_by_name), '') = COALESCE(LOWER(?), '')
              AND COALESCE(LOWER(promised_to_name), '') = COALESCE(LOWER(?), '')
            LIMIT 1
            """,
            (
                transcript_id,
                item.get("text", ""),
                item.get("promised_by", ""),
                item.get("promised_to", ""),
            ),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """INSERT INTO promises (transcript_id, promised_by_name, promised_to_name, description, due_date)
            VALUES (?, ?, ?, ?, ?)""",
            (
                transcript_id,
                item.get("promised_by", ""),
                item.get("promised_to", ""),
                item.get("text", ""),
                item.get("due_date"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── Request/Response Models ──

VALID_MODES = {"voice_note", "meeting", "fathom_meeting"}


class ProcessRequest(BaseModel):
    audio_path: str
    mode: str = "voice_note"
    num_speakers: Optional[int] = Field(None, ge=1, le=20)


class ProcessResponse(BaseModel):
    recording_id: str
    transcript_id: str
    status: str
    transcript_preview: str
    knowledge: Optional[dict] = None


class SystemControlRequest(BaseModel):
    reason: Optional[str] = None


@app.get("/health")
def health():
    from backend.ai.ollama_engine import is_available as ollama_ok
    return {"status": "ok", "version": "0.5.0", "ollama": ollama_ok()}


@app.get("/ollama/status")
def ollama_status():
    """Check Ollama availability and list models."""
    from backend.ai.ollama_engine import is_available, list_models
    return {"available": is_available(), "models": list_models()}


@app.post("/ollama/classify")
def ollama_classify(text: str, categories: str):
    """Classify text using local LLM. Categories as comma-separated string."""
    from backend.ai.ollama_engine import classify
    cats = [c.strip() for c in categories.split(",")]
    return {"category": classify(text, cats)}


@app.post("/ollama/summarize")
def ollama_summarize(text: str, max_words: int = 50):
    """Summarize text using local LLM."""
    from backend.ai.ollama_engine import summarize
    return {"summary": summarize(text, max_words)}


# ── Insights Endpoints ──

@app.get("/insights/overview")
def insights_overview():
    """Get high-level stats across all data."""
    from backend.insights.analyzer import get_overview_stats
    return get_overview_stats()

@app.get("/insights/weekly")
def insights_weekly():
    """Get weekly activity breakdown."""
    from backend.insights.analyzer import get_weekly_activity
    return get_weekly_activity()

@app.get("/insights/projects")
def insights_projects():
    """Get project health scores."""
    from backend.insights.analyzer import get_project_health
    return get_project_health()

@app.get("/insights/people")
def insights_people():
    """Get people interaction summary."""
    from backend.insights.analyzer import get_people_interaction_summary
    return get_people_interaction_summary()


# ── Quick Capture ──

class CaptureRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    source_url: Optional[str] = Field(None, max_length=2000)
    source_title: Optional[str] = Field(None, max_length=500)
    project: Optional[str] = Field(None, max_length=200)
    person: Optional[str] = Field(None, max_length=200)
    channel: Optional[str] = Field(None, max_length=100)

@app.post("/capture")
def quick_capture(request: CaptureRequest):
    """Quick capture — auto-classify and route to correct storage.

    Prefixes: todo:, remind:, idea:, spent:, habit:
    Without prefix: auto-classify via keyword matching.
    """
    text = request.text.strip()
    lower = text.lower()

    import re
    import time

    def _db_write(sql, params):
        """Write with retry for locked DB."""
        for attempt in range(3):
            try:
                conn = db.get_connection()
                try:
                    conn.execute(sql, params)
                    conn.commit()
                finally:
                    conn.close()
                return True
            except Exception as e:
                logger.warning("DB write retry %d: %s", attempt + 1, e)
                time.sleep(0.5)
        logger.error("DB write failed after 3 retries")
        return False

    if lower.startswith("todo:") or lower.startswith("task:"):
        task_text = text.split(":", 1)[1].strip()
        _db_write(
            "INSERT INTO action_items (transcript_id, text, assignee, project, status) VALUES (?, ?, ?, ?, 'pending')",
            ("manual", task_text, request.person, request.project),
        )
        return {"type": "task", "text": task_text}

    elif lower.startswith("decision:"):
        decision_text = text.split(":", 1)[1].strip()
        context = f"Captured from {request.source_url}" if request.source_url else "Manual quick capture"
        try:
            from backend.intelligence.decisions import save_decision_journal
            decision_id = save_decision_journal(
                transcript_id="manual",
                text=decision_text,
                reasoning=context,
                confidence=5,
                domain="work",
                source="quick_capture",
            )
            _db_write(
                "INSERT INTO decisions (transcript_id, text, context) VALUES (?, ?, ?)",
                ("manual", decision_text, context),
            )
            return {"type": "decision", "id": decision_id, "text": decision_text}
        except Exception as e:
            logger.warning("Decision capture failed: %s", e)
            _db_write(
                "INSERT INTO decisions (transcript_id, text, context) VALUES (?, ?, ?)",
                ("manual", decision_text, context),
            )
            return {"type": "decision", "text": decision_text}

    elif lower.startswith("idea:"):
        idea_text = text.split(":", 1)[1].strip()
        from backend.life.manager import init_life_tables
        init_life_tables()
        context = " | ".join(part for part in [request.source_title, request.source_url] if part)
        _db_write("INSERT INTO ideas (text, context, category, status) VALUES (?, ?, ?, 'parked')", (idea_text, context, request.project))
        return {"type": "idea", "text": idea_text}

    elif lower.startswith("spent:") or lower.startswith("expense:") or lower.startswith("spent "):
        parts = text.split(":", 1)[1].strip() if ":" in text else text[6:].strip()
        match = re.match(r'(\d+)\s*(?:on\s+)?(.+)?', parts)
        if match:
            amount = float(match.group(1))
            desc = (match.group(2) or "").strip()
            from backend.life.manager import init_life_tables
            init_life_tables()
            _db_write("INSERT INTO expenses (amount, description, date) VALUES (?, ?, date('now'))", (amount, desc))
            return {"type": "expense", "amount": amount, "description": desc}
        return {"type": "expense", "error": "Could not parse amount"}

    elif lower.startswith("habit:"):
        habit_text = text.split(":", 1)[1].strip()
        from backend.life.manager import create_habit
        habit_id = create_habit(habit_text)
        return {"type": "habit", "id": habit_id, "text": habit_text}

    elif lower.startswith("remind:") or lower.startswith("reminder:"):
        reminder_text = text.split(":", 1)[1].strip()
        _db_write("INSERT INTO reminders (transcript_id, text, status) VALUES (?, ?, 'pending')", ("manual", reminder_text))
        return {"type": "reminder", "text": reminder_text}

    else:
        from backend.life.manager import init_life_tables
        init_life_tables()
        _db_write("INSERT INTO ideas (text, category, status) VALUES (?, 'uncategorized', 'parked')", (text,))
        return {"type": "idea", "text": text, "note": "Auto-classified as idea."}


@app.post("/capture/mobile")
def mobile_capture(request: CaptureRequest):
    """Mobile/non-Mac quick capture wrapper."""
    result = quick_capture(request)
    result["capture_surface"] = "mobile"
    return result


@app.post("/capture/channel/{channel_name}")
def channel_capture(channel_name: str, request: CaptureRequest):
    """Telegram/Discord-style chat-channel capture adapter."""
    payload = request.dict()
    payload["channel"] = channel_name
    result = quick_capture(CaptureRequest(**payload))
    result["capture_surface"] = "channel"
    result["channel"] = channel_name
    return result


# ── Inbox / Dashboard ──

@app.get("/inbox")
def inbox():
    """Get all items needing attention — the unified inbox."""
    items = []

    conn = db.get_connection()
    try:
        unprocessed = conn.execute(
            "SELECT id, mode, created_at FROM recordings WHERE status NOT IN ('completed', 'failed') ORDER BY created_at DESC"
        ).fetchall()
        for r in unprocessed:
            items.append({"type": "unprocessed_recording", "id": r["id"], "mode": r["mode"], "date": r["created_at"]})

        try:
            contradictions = conn.execute(
                "SELECT id, description, severity FROM cross_references WHERE status = 'open' AND type = 'contradiction'"
            ).fetchall()
            for c in contradictions:
                items.append({"type": "contradiction", "id": c["id"], "description": c["description"], "severity": c["severity"]})
        except Exception as e:
            logger.debug("Cross-references table not ready: %s", e)

        try:
            evals = conn.execute(
                "SELECT id, text, evaluation_date FROM decisions_journal WHERE status = 'tracked' AND evaluation_date <= date('now')"
            ).fetchall()
            for e in evals:
                items.append({"type": "pending_evaluation", "id": e["id"], "text": e["text"], "date": e["evaluation_date"]})
        except Exception as e:
            logger.debug("Decisions journal table not ready: %s", e)

        try:
            overdue = conn.execute(
                "SELECT id, description, promised_to_name, due_date FROM promises WHERE status = 'pending' AND due_date < date('now')"
            ).fetchall()
            for o in overdue:
                items.append({"type": "overdue_promise", "id": o["id"], "description": o["description"],
                             "to": o["promised_to_name"], "due": o["due_date"]})
        except Exception as e:
            logger.debug("Promises table not ready: %s", e)

        try:
            approvals = conn.execute(
                "SELECT id, action_type, description FROM action_log WHERE status = 'pending'"
            ).fetchall()
            for a in approvals:
                items.append({"type": "pending_approval", "id": a["id"], "action": a["action_type"], "description": a["description"]})
        except Exception as e:
            logger.debug("Action log table not ready: %s", e)
    finally:
        conn.close()

    return {"items": items, "total": len(items)}


@app.get("/stats")
def system_stats():
    """Get system statistics."""
    from backend.storage.resilience import check_database_integrity
    integrity = check_database_integrity()
    return {
        "version": "0.4.0",
        "database": integrity,
    }


@app.get("/resilience/status")
def resilience_status(live_checks: bool = Query(default=False)):
    """Return graceful-degradation level and component readiness."""
    from backend.storage.resilience import get_degradation_status
    return get_degradation_status(live_checks=live_checks)


@app.get("/network/status")
def network_status(live_checks: bool = Query(default=False)):
    """Return local/offline readiness plus optional short network probes."""
    from backend.storage.resilience import get_degradation_status
    status = get_degradation_status(live_checks=live_checks)
    return {
        "level": status["level"],
        "name": status["name"],
        "network": status["components"]["network"],
        "sarvam": status["components"]["sarvam"],
        "local_core_ok": status["local_core_ok"],
    }


@app.post("/backup")
def create_backup():
    """Create a database backup."""
    from backend.storage.resilience import backup_database
    path = backup_database()
    return {"status": "backed_up", "path": path}


@app.post("/archive/audio")
def archive_audio(
    older_than_days: int = Query(default=30, ge=1, le=3650),
    limit: int = Query(default=10, ge=1, le=100),
    dry_run: bool = Query(default=False),
    recording_id: Optional[str] = None,
):
    """Archive old local WAV recordings to AAC/M4A."""
    from backend.storage.resilience import archive_old_audio
    return archive_old_audio(
        older_than_days=older_than_days,
        limit=limit,
        dry_run=dry_run,
        recording_id=recording_id,
    )


@app.get("/queue")
def list_queue():
    """Get pending processing queue items."""
    from backend.storage.resilience import get_queued_items
    return get_queued_items()


@app.post("/queue/process")
def process_queue(limit: int = Query(default=3, ge=1, le=20), recording_id: Optional[str] = None):
    """Process queued recordings locally, oldest first."""
    from backend.storage.resilience import get_queued_items, mark_completed, mark_failed, mark_processing

    processed = []
    failed = []
    items = get_queued_items()
    if recording_id:
        items = [item for item in items if item.get("recording_id") == recording_id]

    for item in items[:limit]:
        queue_id = item["id"]
        recording_id = item["recording_id"]
        try:
            mark_processing(queue_id)
            result = _process_saved_recording(
                recording_id=recording_id,
                audio_path=item["audio_path"],
                mode=item.get("mode") or "voice_note",
                num_speakers=None,
            )
            mark_completed(queue_id)
            processed.append({"queue_id": queue_id, "recording_id": recording_id, "transcript_id": result.transcript_id})
        except Exception as e:
            mark_failed(queue_id, str(e))
            _mark_recording_failed(recording_id)
            failed.append({"queue_id": queue_id, "recording_id": recording_id, "error": str(e)})

    return {"processed": processed, "failed": failed, "total_processed": len(processed), "total_failed": len(failed)}


def _mark_recording_failed(recording_id: str):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE recordings SET status = 'failed' WHERE id = ?", (recording_id,))
        conn.commit()
    finally:
        conn.close()


def _mark_recording_processing(recording_id: str):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE recordings SET status = 'processing' WHERE id = ?", (recording_id,))
        conn.commit()
    finally:
        conn.close()


def _process_saved_recording(recording_id: str, audio_path: str, mode: str, num_speakers: Optional[int] = None) -> ProcessResponse:
    """Run the full processing pipeline for an existing recording row."""
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {VALID_MODES}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    _mark_recording_processing(recording_id)

    audio_to_process = audio_path
    if mode == "meeting":
        recording_dir = os.path.dirname(audio_path)
        system_audio = os.path.join(recording_dir, "system_audio.wav")
        if os.path.exists(system_audio):
            mixed_path = os.path.join(recording_dir, "mixed_audio.wav")
            audio_to_process = mix_meeting_audio(audio_path, system_audio, mixed_path)

    processed_dir = os.path.join(RECORDINGS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_{recording_id[:8]}")
    processed_path = process_audio(audio_to_process, processed_dir)

    if mode == "meeting":
        transcript = transcribe_meeting(processed_path, num_speakers)
    else:
        transcript = transcribe_short(processed_path)

    # Sarvam builds transcript metadata from the processed file path; keep
    # the persisted transcript linked to the API recording row instead.
    transcript["id"] = f"transcript_{recording_id}"
    transcript["recording_id"] = recording_id
    db.save_transcript(transcript)

    knowledge = None
    try:
        transcript_text = transcript.get("full_transcript", "")
        if transcript_text and len(transcript_text) > 20:
            logger.info("Extracting knowledge with local reasoning engine...")
            knowledge = local_llm_extract(transcript_text)
            _persist_extracted_knowledge(recording_id, transcript, knowledge, mode)
    except Exception as e:
        logger.error("Knowledge extraction failed: %s", e)

    transcript_text = transcript.get("full_transcript", "")
    if transcript_text and len(transcript_text) > 50:
        try:
            from backend.intelligence.sentiment import analyze_transcript_sentiment
            sentiment = analyze_transcript_sentiment(
                transcript_text[:2000],
                recording_id=recording_id,
                transcript_id=transcript["id"],
            )
            logger.info("Sentiment: %s (score: %s)", sentiment.get("label"), sentiment.get("score"))
        except Exception as e:
            logger.warning("Sentiment analysis failed: %s", e)

    preview = transcript.get("full_transcript", "")[:500]
    return ProcessResponse(
        recording_id=recording_id,
        transcript_id=transcript["id"],
        status="completed",
        transcript_preview=preview,
        knowledge=knowledge,
    )


def _persist_extracted_knowledge(recording_id: str, transcript: dict, knowledge: Optional[dict], mode: str):
    if not knowledge:
        return

    transcript_id = transcript["id"]
    for item in knowledge.get("action_items", []):
        db.save_action_item(
            transcript_id=transcript_id,
            text=item.get("text", ""),
            assignee=item.get("assignee"),
            project=knowledge.get("project"),
            due_date=item.get("due_date"),
        )
    for item in knowledge.get("decisions", []):
        db.save_decision(
            transcript_id=transcript_id,
            text=item.get("text", ""),
            made_by=item.get("made_by"),
            context=item.get("context"),
            project=knowledge.get("project"),
        )
        try:
            from backend.intelligence.decisions import save_decision_journal
            save_decision_journal(
                transcript_id=transcript_id,
                text=item.get("text", ""),
                made_by=item.get("made_by"),
                reasoning=item.get("context"),
                confidence=7,
                domain="work",
                project_name=knowledge.get("project"),
            )
        except Exception as e:
            logger.warning("Failed to save decision journal entry: %s", e)

    for item in knowledge.get("promises", []):
        _save_promise(transcript_id, item)

    try:
        from backend.intelligence.cross_reference import track_recurring_topics
        topic_names = [t.get("title", "") for t in knowledge.get("topics", [])]
        track_recurring_topics(topic_names)
    except Exception as e:
        logger.warning("Failed to track recurring topics: %s", e)

    logger.info(
        "Extracted: %d actions, %d decisions, %d promises",
        len(knowledge.get("action_items", [])),
        len(knowledge.get("decisions", [])),
        len(knowledge.get("promises", [])),
    )

    if mode == "meeting":
        try:
            from backend.intelligence.meeting_score import score_meeting
            score = score_meeting(recording_id, knowledge, transcript.get("duration_seconds", 0))
            logger.info("Meeting score: %s/100", score["overall_score"])
        except Exception as e:
            logger.warning("Meeting scoring failed: %s", e)

    try:
        from backend.intelligence.cross_reference import check_contradictions
        findings = check_contradictions(transcript.get("full_transcript", ""))
        if findings:
            logger.info("Cross-reference: %d findings", len(findings))
    except Exception as e:
        logger.warning("Cross-reference check failed: %s", e)

    try:
        from backend.graph.neo4j_client import ingest_knowledge
        participants = [p.get("label", p.get("speaker_id", "")) for p in transcript.get("participants", [])]
        ingest_knowledge(
            knowledge,
            transcript_id,
            meeting_date=datetime.now().isoformat(),
            participants=participants,
        )
    except Exception as e:
        logger.warning("Graph ingestion skipped: %s", e)


@app.post("/process", response_model=ProcessResponse)
def process_recording(request: ProcessRequest):
    """Full pipeline: preprocess -> transcribe -> extract knowledge."""
    if request.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode '{request.mode}'. Must be one of: {VALID_MODES}")
    if not os.path.exists(request.audio_path):
        raise HTTPException(status_code=404, detail=f"Audio file not found: {request.audio_path}")

    recording_id = _stable_local_recording_id(request.mode, request.audio_path)
    db.save_recording(recording_id, request.mode, request.audio_path)

    try:
        return _process_saved_recording(recording_id, request.audio_path, request.mode, request.num_speakers)
    except Exception as e:
        _mark_recording_failed(recording_id)
        try:
            from backend.storage.resilience import queue_for_processing
            queue_for_processing(recording_id, request.audio_path, request.mode)
        except Exception as queue_error:
            logger.warning("Failed to queue recording %s: %s", recording_id, queue_error)
        logger.error("Processing failed for recording %s: %s", recording_id, e)
        raise HTTPException(status_code=500, detail=str(e))


def _stable_local_recording_id(mode: str, audio_path: str) -> str:
    path = Path(audio_path).expanduser().resolve()
    stat = path.stat()
    key = f"{mode}|{path}|{stat.st_size}|{stat.st_mtime_ns}"
    return f"local_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"


@app.get("/recordings")
def list_recordings(limit: int = Query(default=10, ge=1, le=100)):
    """List recent recordings with their transcripts."""
    return db.get_recent_recordings(min(limit, 100))


@app.get("/transcript/{recording_id}")
def get_transcript(recording_id: str):
    """Get full transcript for a recording."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT transcript_json FROM transcripts WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return json.loads(row["transcript_json"])


# ── Decision Journal Endpoints ──

@app.get("/decisions")
def list_decisions(status: Optional[str] = None, domain: Optional[str] = None):
    """List all decisions in the journal."""
    from backend.intelligence.decisions import get_all_decisions, migrate_existing_decisions
    migrate_existing_decisions()
    return get_all_decisions(status, domain)


@app.get("/decisions/pending-evaluation")
def pending_evaluations():
    """Get decisions due for outcome evaluation."""
    from backend.intelligence.decisions import get_pending_evaluations
    return get_pending_evaluations()


@app.get("/decisions/calibration")
def calibration():
    """Get calibration data: confidence vs actual accuracy."""
    from backend.intelligence.decisions import get_calibration
    return get_calibration()


@app.get("/decisions/{decision_id}")
def get_decision_detail(decision_id: int):
    """Get a single decision with full details."""
    from backend.intelligence.decisions import get_decision
    d = get_decision(decision_id)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")
    return d


class EvaluateRequest(BaseModel):
    outcome: str  # positive, negative, mixed, neutral
    outcome_notes: Optional[str] = Field(None, max_length=2000)
    was_correct: Optional[bool] = None


@app.post("/decisions/{decision_id}/evaluate")
def evaluate(decision_id: int, request: EvaluateRequest):
    """Record the outcome of a decision."""
    from backend.intelligence.decisions import evaluate_decision
    if evaluate_decision(decision_id, request.outcome, request.outcome_notes, request.was_correct):
        return {"status": "evaluated"}
    raise HTTPException(status_code=404, detail="Decision not found")


# ── Cross-Reference Endpoints ──

@app.get("/cross-references")
def list_cross_references():
    """Get open contradictions and connections."""
    from backend.intelligence.cross_reference import get_open_cross_references
    return get_open_cross_references()


@app.get("/cross-references/recurring")
def recurring_topics():
    """Get topics discussed 3+ times without resolution."""
    from backend.intelligence.cross_reference import get_recurring_unresolved
    return get_recurring_unresolved()


class ResolveRequest(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=2000)


@app.post("/cross-references/{ref_id}/resolve")
def resolve_ref(ref_id: int, request: ResolveRequest):
    """Resolve a cross-reference finding."""
    from backend.intelligence.cross_reference import resolve_cross_reference
    if resolve_cross_reference(ref_id, request.resolution):
        return {"status": "resolved"}
    raise HTTPException(status_code=404, detail="Cross-reference not found")


# ── Writing Assistant Endpoints ──

@app.get("/recordings/{recording_id}/minutes")
def generate_minutes(recording_id: str):
    """Generate formatted meeting minutes from a recording's transcript."""
    from backend.ai.local_llm_engine import ask

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT transcript_json FROM transcripts WHERE recording_id = ?", (recording_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    transcript = json.loads(row["transcript_json"])
    text = transcript.get("full_transcript", "")

    if not text or len(text) < 20:
        return {"minutes": "Transcript too short to generate minutes."}

    prompt = f"""Generate professional meeting minutes from this transcript.

Format:
# Meeting Minutes — [Date]
## Attendees
## Discussion Summary
## Decisions Made
## Action Items (with assignee and due date)
## Promises/Commitments
## Next Steps

Keep it concise and actionable.

Transcript:
{text[:3000]}"""

    minutes = ask(prompt, max_wait=60)
    return {"recording_id": recording_id, "minutes": minutes}


@app.get("/generate/standup")
def generate_standup():
    """Auto-generate standup update from recent activity."""
    from backend.ai.local_llm_engine import ask

    # Gather recent data
    action_items = db.get_pending_action_items()
    conn = db.get_connection()
    try:
        recent = conn.execute(
            "SELECT full_text, processed_at FROM transcripts ORDER BY processed_at DESC LIMIT 3"
        ).fetchall()
        decisions = conn.execute(
            "SELECT text, created_at FROM decisions ORDER BY rowid DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    context = ""
    if recent:
        context += "Recent meetings:\n" + "\n".join(f"- {r['full_text'][:100]}" for r in recent) + "\n\n"
    if decisions:
        context += "Recent decisions:\n" + "\n".join(f"- {d['text']}" for d in decisions) + "\n\n"
    if action_items:
        context += "Pending tasks:\n" + "\n".join(f"- {a['text']} (assignee: {a.get('assignee', '?')})" for a in action_items[:5])

    prompt = f"""Generate a concise standup update based on this activity data.

Format:
**Yesterday:** (what was done)
**Today:** (what's planned)
**Blockers:** (if any)

Keep it under 100 words.

Activity:
{context}"""

    standup = ask(prompt, max_wait=60)
    return {"standup": standup}


@app.get("/search")
def search(query: str = Query(..., min_length=1, max_length=500), limit: int = 20):
    """Full-text search across all transcripts."""
    return db.search_transcripts(query, min(limit, 100))


class MeetingPrepRequest(BaseModel):
    attendees: list[str] = Field(..., min_length=1)
    meeting_title: str = ""


@app.post("/meeting-prep")
def meeting_prep(request: MeetingPrepRequest):
    """Generate pre-meeting preparation briefing for attendees."""
    from backend.intelligence.meeting_prep import prepare_for_meeting
    return prepare_for_meeting(request.attendees, request.meeting_title)


@app.post("/meeting-prep/summary")
def meeting_prep_summary(request: MeetingPrepRequest):
    """Generate a human-readable pre-meeting prep summary."""
    from backend.intelligence.meeting_prep import generate_prep_summary
    summary = generate_prep_summary(request.attendees, request.meeting_title)
    return {"summary": summary, "attendees": request.attendees}


@app.post("/chat/react")
def chat_react(request: ChatRequest):
    """Advanced chat with multi-step reasoning (ReACT agent).

    The agent autonomously decides which tools to call, chains multiple
    searches, and synthesizes a comprehensive answer.
    """
    from backend.ai.react_agent import react_chat
    result = react_chat(request.query)
    return result


@app.get("/briefing/morning")
def morning_briefing():
    """Generate and return today's morning briefing."""
    from backend.heartbeat.engine import generate_morning_briefing
    return generate_morning_briefing()


@app.get("/notifications")
def get_notifs():
    """Get pending notifications from heartbeat."""
    from backend.heartbeat.engine import get_notifications
    return get_notifications()


@app.post("/heartbeat/trigger")
def trigger_heartbeat():
    """Manually trigger a heartbeat check."""
    from backend.heartbeat.engine import run_heartbeat, get_notifications
    run_heartbeat()
    return {"triggered": True, "notifications": get_notifications()}


@app.get("/scheduler/status")
def scheduled_agent_status():
    """Return heartbeat and scheduled intelligence job status."""
    from backend.heartbeat.engine import scheduler_status
    return scheduler_status()


# ── Onboarding / Configuration ──

@app.get("/onboarding/status")
def onboarding_status():
    """Summarize setup readiness for the desktop onboarding flow."""
    checks = []

    def add(key, label, ok, detail=""):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail})

    add("backend", "Backend API", True, "FastAPI is responding")
    add("local_storage", "Local storage", os.access(DATA_DIR, os.W_OK), DATA_DIR)
    try:
        from backend.storage.resilience import check_database_integrity
        integrity = check_database_integrity()
        add("postgres", "Postgres", integrity.get("integrity") == "ok", f"{integrity.get('tables', 0)} tables")
    except Exception as e:
        add("postgres", "Postgres", False, str(e))
    try:
        from backend.graph.neo4j_client import is_available as neo4j_ok
        add("neo4j", "Neo4j", neo4j_ok(), "Relationship graph")
    except Exception as e:
        add("neo4j", "Neo4j", False, str(e))
    try:
        from backend.storage.chroma_store import is_available as chroma_ok
        add("chroma", "Chroma", chroma_ok(), "Vector collection ready")
    except Exception as e:
        add("chroma", "Chroma", False, str(e))
    try:
        from backend.ai.model_router import _get_available_models
        models = sorted(_get_available_models())
        add("models", "Local models", bool(models), ", ".join(models[:5]) or "No models detected")
    except Exception as e:
        add("models", "Local models", False, str(e))

    for key, label, env_name in [
        ("gmail", "Gmail", "SUDOBRAIN_SYNC_GMAIL"),
        ("slack", "Slack", "SUDOBRAIN_SYNC_SLACK"),
        ("fathom", "Fathom", "SUDOBRAIN_SYNC_FATHOM"),
        ("linear", "Linear", "LINEAR_API_TOKEN"),
        ("calendar", "Google Calendar", "GCAL_TOKEN_FILE"),
        ("project_context", "Local repositories", "SUDOBRAIN_SYNC_PROJECT_CONTEXT"),
    ]:
        add(key, label, _truthy_env(env_name, False) or bool(os.getenv(env_name)), f"{env_name} configured")

    demo_rows = 0
    try:
        conn = db.get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM transcripts WHERE id LIKE 'demo-%'").fetchone()
            demo_rows = int(row["total"]) if row else 0
        finally:
            conn.close()
    except Exception:
        demo_rows = 0
    add("demo_data", "Demo data", demo_rows > 0, f"{demo_rows} demo transcripts")

    return {
        "complete": all(c["ok"] for c in checks if c["key"] in {"backend", "postgres"}),
        "checks": checks,
        "config_path": str(CONFIG_PATH),
    }


class LocalConfigRequest(BaseModel):
    values: dict = Field(default_factory=dict)


class ProviderRoutingRequest(BaseModel):
    rules: list[dict] = Field(default_factory=list)


@app.get("/config/status")
def config_status():
    """Return safe runtime/config fields for Settings and integration setup."""
    local_config = _load_local_config()
    env_names = [
        "SUDOBRAIN_API_TOKEN", "SUDOBRAIN_TRUST_LOCALHOST", "SUDOBRAIN_DATA_DIR",
        "SUDOBRAIN_LLM_PROVIDER", "SUDOBRAIN_LLM_MODEL", "SUDOBRAIN_LLM_COMMAND",
        "SUDOBRAIN_SYNC_GMAIL", "SUDOBRAIN_SYNC_SLACK", "SUDOBRAIN_SYNC_FATHOM",
        "SUDOBRAIN_SYNC_PROJECT_CONTEXT", "SUDOBRAIN_SLACK_INCLUDE_DMS",
        "SUDOBRAIN_AUTO_SOURCE_SYNC", "SUDOBRAIN_SOURCE_SYNC_INTERVAL_MINUTES",
        "GMAIL_CREDENTIALS_FILE", "GMAIL_TOKEN_FILE", "GCAL_TOKEN_FILE",
        "SLACK_USER_TOKEN", "LINEAR_API_TOKEN", "FATHOM_API_TOKEN",
        "SUDOBRAIN_OPENAI_COMPAT_BASE_URL", "SUDOBRAIN_OPENAI_COMPAT_MODEL",
        "SUDOBRAIN_OPENAI_COMPAT_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL", "GROQ_API_KEY", "GROQ_MODEL", "AWS_PROFILE",
        "BEDROCK_MODEL", "LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL",
        "SUDOBRAIN_PROJECTS_ROOT", "SUDOBRAIN_PROJECT_ALIASES_JSON",
        "SUDOBRAIN_PERSON_ALIASES_JSON",
    ]
    values = {}
    for name in env_names:
        raw = local_config.get(name, os.getenv(name, ""))
        secret = any(token in name for token in ["TOKEN", "PASSWORD", "SECRET", "CREDENTIAL"])
        values[name] = {
            "configured": bool(raw),
            "value": "••••••••" if secret and raw else raw,
            "secret": secret,
            "source": "local_config" if name in local_config else "environment",
        }
    return {"values": values, "config_path": str(CONFIG_PATH)}


@app.post("/config/save")
def save_config(request: LocalConfigRequest):
    """Save local app config outside the repository. Does not edit .env."""
    allowed = set(config_status()["values"].keys())
    incoming = {k: v for k, v in request.values.items() if k in allowed}
    existing = _load_local_config()
    for key, value in incoming.items():
        if value is None or value == "":
            existing.pop(key, None)
        elif value != "••••••••":
            existing[key] = value
    _save_local_config(existing)
    return {"status": "saved", "config_path": str(CONFIG_PATH), "keys": sorted(incoming.keys())}


@app.get("/models/routing-rules")
def model_routing_rules():
    """Return safe per-task provider routing rules."""
    from backend.ai.providers import load_routing_rules
    return load_routing_rules()


@app.post("/models/routing-rules")
def save_model_routing_rules(request: ProviderRoutingRequest):
    """Save per-model/provider routing rules outside the repository."""
    from backend.ai.providers import save_routing_rules
    return save_routing_rules(request.rules)


@app.get("/models/route")
def model_route(task: str = "chat", privacy: str = "local"):
    """Preview which provider would be used for a task/privacy combination."""
    from backend.ai.providers import choose_provider_for
    return choose_provider_for(task=task, privacy=privacy)


@app.get("/review/queue")
def review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    kind: Optional[str] = None,
    source: Optional[str] = None,
    project: Optional[str] = None,
    min_confidence: Optional[float] = Query(default=None, ge=0, le=1),
    max_age_days: Optional[int] = Query(default=None, ge=1, le=3650),
):
    """Unified review queue for extracted knowledge."""
    conn = db.get_connection()
    items = []
    try:
        specs = [
            ("task", "action_items", "text", "status = 'pending'"),
            ("decision", "decisions", "text", "TRUE"),
            ("promise", "promises", "description", "status = 'pending'"),
            ("reminder", "reminders", "text", "status = 'pending'"),
        ]
        for kind, table, text_col, where in specs:
            try:
                rows = conn.execute(
                    f"SELECT *, '{kind}' AS review_kind, {text_col} AS review_text FROM {table} WHERE {where} ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    item["confidence"] = _confidence_for_row(table, item)["score"]
                    item["source"] = item.get("transcript_id") or item.get("recording_id") or table
                    items.append(item)
            except Exception as e:
                logger.debug("Review source skipped %s: %s", table, e)
        if kind:
            items = [item for item in items if item.get("review_kind") == kind]
        if source:
            needle = source.lower()
            items = [item for item in items if needle in str(item.get("source", "")).lower()]
        if project:
            needle = project.lower()
            items = [item for item in items if needle in str(item.get("project", "")).lower()]
        if min_confidence is not None:
            items = [item for item in items if float(item.get("confidence") or 0) >= min_confidence]
        if max_age_days is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
            filtered = []
            for item in items:
                raw = str(item.get("created_at") or "")
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if parsed.timestamp() >= cutoff:
                        filtered.append(item)
                except Exception:
                    filtered.append(item)
            items = filtered
        items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return {
            "items": items[:limit],
            "total": len(items),
            "filters": {
                "kind": kind,
                "source": source,
                "project": project,
                "min_confidence": min_confidence,
                "max_age_days": max_age_days,
            },
        }
    finally:
        conn.close()


@app.post("/review/{kind}/{item_id}/accept")
def accept_review_item(kind: str, item_id: int):
    action_id = _record_review_action(kind, item_id, "accepted")
    return {"status": "accepted", "kind": kind, "id": item_id, "action_id": action_id}


@app.post("/review/{kind}/{item_id}/dismiss")
def dismiss_review_item(kind: str, item_id: int):
    table_map = {"task": "action_items", "promise": "promises", "reminder": "reminders"}
    table = table_map.get(kind)
    if not table:
        action_id = _record_review_action(kind, item_id, "dismissed")
        return {"status": "dismissed", "kind": kind, "id": item_id, "action_id": action_id}
    conn = db.get_connection()
    try:
        previous = conn.execute(f"SELECT status FROM {table} WHERE id = ?", (item_id,)).fetchone()
        conn.execute(f"UPDATE {table} SET status = 'dismissed' WHERE id = ?", (item_id,))
        action_id = _record_review_action(kind, item_id, "dismissed", previous_status=previous["status"] if previous else None, conn=conn)
        conn.commit()
        return {"status": "dismissed", "kind": kind, "id": item_id, "action_id": action_id}
    finally:
        conn.close()


def _init_review_actions(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_actions (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            previous_status TEXT,
            undone BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            undone_at TIMESTAMP
        )
    """)


def _record_review_action(kind: str, item_id: int, action: str, previous_status: str | None = None, conn=None) -> int | None:
    own_conn = conn is None
    conn = conn or db.get_connection()
    try:
        _init_review_actions(conn)
        cursor = conn.execute(
            "INSERT INTO review_actions (kind, item_id, action, previous_status) VALUES (?, ?, ?, ?)",
            (kind, item_id, action, previous_status),
        )
        if own_conn:
            conn.commit()
        return getattr(cursor, "lastrowid", None)
    finally:
        if own_conn:
            conn.close()


@app.get("/review/actions")
def review_actions(limit: int = Query(default=100, ge=1, le=500)):
    """Return review accept/dismiss actions so extraction decisions are auditable."""
    conn = db.get_connection()
    try:
        _init_review_actions(conn)
        rows = conn.execute("SELECT * FROM review_actions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.post("/review/actions/{action_id}/undo")
def undo_review_action(action_id: int):
    """Undo a review action when SudoBrain can safely restore the previous local status."""
    table_map = {"task": "action_items", "promise": "promises", "reminder": "reminders"}
    conn = db.get_connection()
    try:
        _init_review_actions(conn)
        row = conn.execute("SELECT * FROM review_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Review action not found")
        action = dict(row)
        if action.get("undone"):
            return {"status": "already_undone", "action_id": action_id}
        restored = False
        table = table_map.get(action.get("kind"))
        previous_status = action.get("previous_status")
        if table and previous_status:
            conn.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (previous_status, action["item_id"]))
            restored = True
        conn.execute("UPDATE review_actions SET undone = TRUE, undone_at = CURRENT_TIMESTAMP WHERE id = ?", (action_id,))
        conn.commit()
        return {"status": "undone", "action_id": action_id, "restored_status": restored}
    finally:
        conn.close()


def _review_bundle_payload(limit: int, kind: Optional[str] = None, min_confidence: Optional[float] = None) -> dict:
    queue = review_queue(limit=limit, kind=kind, min_confidence=min_confidence)
    items = queue.get("items", [])
    bundle_items = []
    for item in items:
        review_kind = item.get("review_kind", "")
        item_id = item.get("id")
        provenance = {}
        if review_kind and item_id is not None:
            try:
                provenance = knowledge_provenance(review_kind, str(item_id))
            except Exception:
                provenance = {}
        bundle_items.append({
            "kind": review_kind,
            "id": item_id,
            "text": item.get("review_text") or item.get("text") or item.get("description") or "",
            "source": item.get("source", ""),
            "confidence": item.get("confidence"),
            "created_at": item.get("created_at", ""),
            "accept_url": f"/review/{review_kind}/{item_id}/accept",
            "dismiss_url": f"/review/{review_kind}/{item_id}/dismiss",
            "provenance": provenance,
        })
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "filters": {"kind": kind, "min_confidence": min_confidence, "limit": limit},
        "total": len(bundle_items),
        "items": bundle_items,
    }


def _review_bundle_markdown(bundle: dict) -> str:
    lines = [
        "# SudoBrain Review Approval Bundle",
        "",
        f"Created at: {bundle.get('created_at', '')}",
        f"Items: {bundle.get('total', 0)}",
        "",
    ]
    for item in bundle.get("items", []):
        lines.extend([
            f"## {str(item.get('kind') or 'item').title()} #{item.get('id')}",
            "",
            str(item.get("text") or "").strip(),
            "",
            f"- Source: {item.get('source') or 'unknown'}",
            f"- Confidence: {item.get('confidence')}",
            f"- Accept: `{item.get('accept_url')}`",
            f"- Dismiss: `{item.get('dismiss_url')}`",
            "",
        ])
        provenance = item.get("provenance") or {}
        if provenance:
            lines.extend(["### Provenance", ""])
            lines.append(f"- Confidence signals: {', '.join((provenance.get('confidence') or {}).get('signals', []))}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


@app.get("/review/bundle")
def review_approval_bundle(
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    limit: int = Query(default=100, ge=1, le=500),
    kind: Optional[str] = None,
    min_confidence: Optional[float] = Query(default=None, ge=0, le=1),
):
    """Export a human-reviewable approval bundle for pending extracted knowledge."""
    bundle = _review_bundle_payload(limit=limit, kind=kind, min_confidence=min_confidence)
    if format == "markdown":
        return PlainTextResponse(_review_bundle_markdown(bundle), media_type="text/markdown")
    return bundle


@app.get("/people")
def list_people():
    """List all people with their stats."""
    from backend.people.graph import get_all_people, populate_from_knowledge
    populate_from_knowledge()
    return get_all_people()


@app.get("/people/{person_id}")
def get_person(person_id: int):
    """Get detailed person profile."""
    from backend.people.graph import get_person_detail
    detail = get_person_detail(person_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Person not found")
    return detail


@app.get("/promises")
def list_promises():
    """List all pending promises."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM promises WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


class PromiseUpdateRequest(BaseModel):
    status: Optional[str] = None
    promised_by_name: Optional[str] = None
    promised_to_name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    note: Optional[str] = None


def _record_promise_event(conn, promise_id: int, event_type: str, note: str = ""):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS promise_events (
            id SERIAL PRIMARY KEY,
            promise_id INTEGER,
            event_type TEXT NOT NULL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO promise_events (promise_id, event_type, note) VALUES (?, ?, ?)",
        (promise_id, event_type, note),
    )


@app.patch("/promises/{promise_id}")
def update_promise(promise_id: int, request: PromiseUpdateRequest):
    fields = []
    params = []
    for key in ["status", "promised_by_name", "promised_to_name", "description", "due_date"]:
        value = getattr(request, key)
        if value is not None:
            fields.append(f"{key} = ?")
            params.append(value)
    if not fields:
        return {"status": "unchanged"}
    params.append(promise_id)
    conn = db.get_connection()
    try:
        result = conn.execute(f"UPDATE promises SET {', '.join(fields)} WHERE id = ?", tuple(params))
        _record_promise_event(conn, promise_id, "updated", request.note or "")
        conn.commit()
        if result.rowcount <= 0:
            raise HTTPException(status_code=404, detail="Promise not found")
        return {"status": "updated"}
    finally:
        conn.close()


@app.post("/promises/{promise_id}/{action}")
def promise_action(promise_id: int, action: str, request: PromiseUpdateRequest = None):
    allowed = {
        "complete": "completed",
        "remind": "pending",
        "follow-up": "pending",
        "dispute": "disputed",
    }
    if action not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported promise action")
    note = request.note if request else ""
    conn = db.get_connection()
    try:
        if action in {"complete", "dispute"}:
            result = conn.execute("UPDATE promises SET status = ? WHERE id = ?", (allowed[action], promise_id))
        elif action == "remind":
            result = conn.execute(
                "UPDATE promises SET reminder_count = COALESCE(reminder_count, 0) + 1 WHERE id = ?",
                (promise_id,),
            )
        else:
            result = conn.execute("SELECT id FROM promises WHERE id = ?", (promise_id,))
        if result.rowcount <= 0 and action != "follow-up":
            raise HTTPException(status_code=404, detail="Promise not found")
        _record_promise_event(conn, promise_id, action, note or "")
        conn.commit()
        return {"status": action}
    finally:
        conn.close()


@app.get("/promises/{promise_id}/history")
def promise_history(promise_id: int):
    conn = db.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promise_events (
                id SERIAL PRIMARY KEY,
                promise_id INTEGER,
                event_type TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        rows = conn.execute("SELECT * FROM promise_events WHERE promise_id = ? ORDER BY created_at DESC", (promise_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    source_lang: str = "ta-IN"
    target_lang: str = "en-IN"


@app.post("/translate")
def translate(request: TranslateRequest):
    """Translate text between languages using Sarvam AI."""
    from backend.transcription.sarvam_client import translate_text
    translated = translate_text(request.text, request.source_lang, request.target_lang)
    return {"original": request.text, "translated": translated, "source": request.source_lang, "target": request.target_lang}


@app.get("/semantic-search")
def semantic_search_endpoint(query: str, limit: int = 10):
    """Semantic similarity search across all knowledge."""
    from backend.storage.vectors import semantic_search
    return semantic_search(query, top_k=min(limit, 50))


@app.get("/action-items")
def list_action_items(project: Optional[str] = None):
    """List pending action items, optionally filtered by project."""
    return db.get_pending_action_items(project)


class TaskUpdateRequest(BaseModel):
    text: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    project: Optional[str] = None
    status: Optional[str] = None


@app.patch("/action-items/{task_id}")
def update_action_item(task_id: int, request: TaskUpdateRequest):
    fields = []
    params = []
    for key in ["text", "assignee", "due_date", "project", "status"]:
        value = getattr(request, key)
        if value is not None:
            fields.append(f"{key} = ?")
            params.append(value)
    if not fields:
        return {"status": "unchanged"}
    params.append(task_id)
    conn = db.get_connection()
    try:
        result = conn.execute(f"UPDATE action_items SET {', '.join(fields)} WHERE id = ?", tuple(params))
        conn.commit()
        if result.rowcount <= 0:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "updated"}
    finally:
        conn.close()


@app.post("/action-items/{task_id}/complete")
def complete_action_item(task_id: int):
    return update_action_item(task_id, TaskUpdateRequest(status="completed"))


@app.post("/action-items/{task_id}/snooze")
def snooze_action_item(task_id: int, days: int = Query(default=1, ge=1, le=365)):
    from datetime import date, timedelta
    due = (date.today() + timedelta(days=days)).isoformat()
    return update_action_item(task_id, TaskUpdateRequest(due_date=due, status="pending"))


# ── Chat Endpoint ──

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    offline: bool = False
    session_id: Optional[str] = None
    collection: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    sources: list
    confidence: str


class ChatSessionRequest(BaseModel):
    title: str = "New chat"
    collection: str = "general"


def _init_chat_tables(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            collection TEXT DEFAULT 'general',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            text TEXT,
            source_json TEXT,
            confidence TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


def _save_chat_message(session_id: str | None, role: str, text: str, sources: list | None = None, confidence: str = "") -> str | None:
    if not session_id:
        return None
    conn = db.get_connection()
    try:
        _init_chat_tables(conn)
        row = conn.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO chat_sessions (id, title, collection) VALUES (?, ?, ?)", (session_id, "Chat", "general"))
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, text, source_json, confidence) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, text, json.dumps(sources or []), confidence),
        )
        conn.execute("UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
        conn.commit()
        return session_id
    finally:
        conn.close()


@app.post("/chat/sessions")
def create_chat_session(request: ChatSessionRequest):
    session_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        _init_chat_tables(conn)
        conn.execute(
            "INSERT INTO chat_sessions (id, title, collection) VALUES (?, ?, ?)",
            (session_id, request.title, request.collection),
        )
        conn.commit()
        return {"id": session_id, "title": request.title, "collection": request.collection}
    finally:
        conn.close()


@app.get("/chat/sessions")
def list_chat_sessions(collection: Optional[str] = None, limit: int = 100):
    conn = db.get_connection()
    try:
        _init_chat_tables(conn)
        if collection:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE collection = ? ORDER BY updated_at DESC LIMIT ?",
                (collection, min(limit, 500)),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?", (min(limit, 500),)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str):
    conn = db.get_connection()
    try:
        _init_chat_tables(conn)
        session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        messages = conn.execute("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,)).fetchall()
        return {"session": dict(session), "messages": [dict(row) for row in messages]}
    finally:
        conn.close()


def _build_chat_knowledge_context(query: str, include_semantic: bool = True) -> list[dict]:
    """Gather local knowledge snippets for chat without requiring an LLM."""
    knowledge_context = []
    seen_texts = set()

    transcript_results = db.search_transcripts(query, limit=5)
    for r in transcript_results:
        text = r.get("text", "")
        if text and text not in seen_texts:
            seen_texts.add(text)
            knowledge_context.append({
                "text": text,
                "source": f"Transcript ({r.get('mode', 'recording')})",
                "date": r.get("recording_date", ""),
                "speaker_label": r.get("speaker_label", ""),
                "source_table": "segments",
                "source_id": r.get("id"),
                "transcript_id": r.get("transcript_id"),
                "recording_id": r.get("recording_id"),
            })

    if include_semantic:
        try:
            from backend.storage.vectors import semantic_search
            vector_results = semantic_search(query, top_k=5, min_score=0.3)
        except Exception as e:
            logger.debug("Semantic chat search skipped: %s", e)
            vector_results = []

        for r in vector_results:
            text = r.get("text", "")
            if text and text not in seen_texts:
                seen_texts.add(text)
                knowledge_context.append({
                    "text": text,
                    "source": f"Semantic match ({r.get('source_table', 'unknown')}, score: {r.get('score', 0):.2f})",
                    "date": "",
                    "speaker_label": "",
                    "source_table": (r.get("metadata") or {}).get("source_table", r.get("source_table", "vectors")),
                    "source_id": (r.get("metadata") or {}).get("source_id", r.get("id")),
                    "score": r.get("score"),
                })

    action_items = db.get_pending_action_items()
    if action_items:
        items_text = "\n".join(
            f"- {a['text']} (assignee: {a.get('assignee', 'unassigned')}, due: {a.get('due_date', 'no date')}, status: {a.get('status', 'pending')})"
            for a in action_items[:10]
        )
        knowledge_context.append({
            "text": f"Pending action items:\n{items_text}",
            "source": "Task Database",
            "date": "",
            "speaker_label": "System",
            "source_table": "action_items",
            "source_id": ",".join(str(a.get("id")) for a in action_items[:10] if a.get("id") is not None),
        })

    conn = db.get_connection()
    try:
        decisions = conn.execute(
            "SELECT id, text, made_by, context, created_at FROM decisions ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    if decisions:
        dec_text = "\n".join(f"- {d['text']} (by: {d['made_by']}, context: {d['context']})" for d in decisions)
        knowledge_context.append({
            "text": f"Recent decisions:\n{dec_text}",
            "source": "Decision Database",
            "date": "",
            "speaker_label": "System",
            "source_table": "decisions",
            "source_id": ",".join(str(d.get("id")) for d in decisions if d.get("id") is not None),
        })

    conn = db.get_connection()
    try:
        promises = conn.execute(
            "SELECT id, promised_by_name, promised_to_name, description, due_date, status FROM promises WHERE status = 'pending' LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    if promises:
        prom_text = "\n".join(
            f"- {p['promised_by_name']} promised {p['promised_to_name']}: {p['description']} (due: {p['due_date'] or 'no date'})"
            for p in promises
        )
        knowledge_context.append({
            "text": f"Pending promises:\n{prom_text}",
            "source": "Promise Database",
            "date": "",
            "speaker_label": "System",
            "source_table": "promises",
            "source_id": ",".join(str(p.get("id")) for p in promises if p.get("id") is not None),
        })

    return knowledge_context


def _offline_chat_response(query: str, knowledge_context: list[dict]) -> dict:
    """Return a deterministic local-search answer when local reasoning engine is unavailable."""
    sources = []
    lines = []
    for i, entry in enumerate(knowledge_context[:8], start=1):
        text = " ".join((entry.get("text") or "").split())
        if not text:
            continue
        speaker = entry.get("speaker_label") or "Source"
        source = entry.get("source") or "Local knowledge"
        excerpt = text[:500]
        lines.append(f"[{i}] {speaker}: {excerpt}")
        sources.append({
            "index": i,
            "source": source,
            "date": entry.get("date", ""),
            "text": excerpt[:100],
            "source_table": entry.get("source_table", ""),
            "source_id": entry.get("source_id", ""),
            "transcript_id": entry.get("transcript_id", ""),
            "recording_id": entry.get("recording_id", ""),
            "score": entry.get("score"),
        })

    if not lines:
        return {
            "answer": "Offline search mode: I couldn't find anything matching this query in the local knowledge base.",
            "sources": [],
            "confidence": "low",
        }

    return {
        "answer": "Offline search mode: I found these local matches without using local reasoning engine synthesis:\n\n" + "\n\n".join(lines),
        "sources": sources,
        "confidence": "medium",
    }


def _llm_answer_unavailable(answer: str) -> bool:
    markers = (
        "Local reasoning CLI is not configured",
        "Local reasoning CLI not found",
        "Local reasoning CLI timed out",
        "Error invoking local reasoning CLI",
        "Error from local reasoning CLI",
    )
    return any(marker in answer for marker in markers)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Ask SudoBrain a question. Falls back to local search when local reasoning engine is unavailable."""
    from backend.ai.local_llm_engine import ask_with_knowledge
    from backend.storage.vectors import embed_all

    # Auto-embed any new items
    try:
        if not request.offline:
            embed_all()
    except Exception as e:
        logger.debug("Auto-embed skipped: %s", e)

    knowledge_context = _build_chat_knowledge_context(request.query, include_semantic=True)
    _save_chat_message(request.session_id, "user", request.query)

    if request.offline:
        result = _offline_chat_response(request.query, knowledge_context)
        _save_chat_message(request.session_id, "assistant", result["answer"], result["sources"], result["confidence"])
        return ChatResponse(answer=result["answer"], sources=result["sources"], confidence=result["confidence"])

    if request.provider:
        from backend.ai.providers import complete_with_provider
        context = "\n\n".join(f"[{i+1}] {entry.get('source')}: {entry.get('text')}" for i, entry in enumerate(knowledge_context[:8]))
        provider_result = complete_with_provider(
            prompt=f"Answer using this local SudoBrain context. Cite source numbers when possible.\n\n{context}\n\nQuestion: {request.query}",
            provider=request.provider,
            max_tokens=512,
        )
        if provider_result.get("status") == "ok" and provider_result.get("text"):
            result = {
                "answer": provider_result["text"],
                "sources": _offline_chat_response(request.query, knowledge_context)["sources"],
                "confidence": "medium",
            }
        else:
            result = {"answer": f"Provider unavailable: {provider_result.get('error')}", "sources": [], "confidence": "low"}
    else:
        # Ask local reasoning engine with full context
        result = ask_with_knowledge(request.query, knowledge_context)

    if _llm_answer_unavailable(result.get("answer", "")):
        logger.info("local reasoning engine unavailable for chat; falling back to offline search response")
        result = _offline_chat_response(request.query, knowledge_context)

    # Check if user message is a correction and learn from it
    try:
        from backend.intelligence.self_improve import process_chat_for_corrections
        learned = process_chat_for_corrections(request.query, result["answer"])
        if learned and learned.get("learned"):
            result["answer"] += f"\n\n---\n*Learned: {learned['rule']}*"
    except Exception as e:
        logger.debug("Self-improvement check skipped: %s", e)

    _save_chat_message(request.session_id, "assistant", result["answer"], result["sources"], result["confidence"])
    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        confidence=result["confidence"],
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """Stream a chat response as server-sent events for web and app clients."""
    result = chat(request)

    def events():
        metadata = {"type": "metadata", "sources": result.sources, "confidence": result.confidence}
        yield f"data: {json.dumps(metadata)}\n\n"
        for token in re.findall(r"\S+\s*", result.answer):
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


# ── Daily Life Endpoints ──

class HabitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    target: str = "daily"

class HabitLog(BaseModel):
    completed: bool = True
    note: Optional[str] = Field(None, max_length=500)

class ExpenseCreate(BaseModel):
    amount: float = Field(..., gt=0, le=10_000_000)
    category: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    date: Optional[str] = None

class IdeaCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    context: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, max_length=100)

@app.get("/habits")
def list_habits():
    from backend.life.manager import get_habits_with_streaks
    return get_habits_with_streaks()

@app.post("/habits")
def create_habit_endpoint(request: HabitCreate):
    from backend.life.manager import create_habit
    return {"id": create_habit(request.name, request.category, request.target)}

@app.post("/habits/{habit_id}/log")
def log_habit_endpoint(habit_id: int, request: HabitLog):
    from backend.life.manager import log_habit
    log_habit(habit_id, request.completed, request.note)
    return {"status": "logged"}

@app.get("/expenses")
def list_expenses(month: Optional[str] = None):
    from backend.life.manager import get_expenses
    return get_expenses(month)

@app.get("/expenses/summary")
def expense_summary(month: Optional[str] = None):
    from backend.life.manager import get_expense_summary
    return get_expense_summary(month)

@app.post("/expenses")
def add_expense_endpoint(request: ExpenseCreate):
    from backend.life.manager import add_expense
    return {"id": add_expense(request.amount, request.category, request.description, request.date)}

@app.get("/ideas")
def list_ideas(status: Optional[str] = None):
    from backend.life.manager import get_ideas
    return get_ideas(status)

@app.post("/ideas")
def add_idea_endpoint(request: IdeaCreate):
    from backend.life.manager import add_idea
    return {"id": add_idea(request.text, request.context, request.category)}

@app.patch("/ideas/{idea_id}")
def update_idea(idea_id: int, status: str):
    from backend.life.manager import update_idea_status
    if update_idea_status(idea_id, status):
        return {"status": "updated"}
    raise HTTPException(status_code=404, detail="Idea not found")


# ── Self-Improving Rules Endpoints ──

@app.get("/rules")
def list_rules():
    """Get all learned rules."""
    from backend.intelligence.self_improve import get_all_rules
    return get_all_rules()


@app.get("/rules/corrections")
def list_corrections():
    """Get recent correction log."""
    from backend.intelligence.self_improve import get_correction_log
    return get_correction_log()


# ── Guardrails Endpoints ──

@app.get("/actions/pending")
def pending_actions():
    """List pending approval requests."""
    from backend.ai.guardrails import get_pending_actions
    return get_pending_actions()


@app.post("/actions/{action_id}/approve")
def approve(action_id: int):
    """Approve a pending action."""
    from backend.ai.guardrails import approve_action
    if approve_action(action_id):
        return {"status": "approved"}
    raise HTTPException(status_code=404, detail="Action not found or already processed")


@app.post("/actions/{action_id}/reject")
def reject(action_id: int):
    """Reject a pending action."""
    from backend.ai.guardrails import reject_action
    if reject_action(action_id):
        return {"status": "rejected"}
    raise HTTPException(status_code=404, detail="Action not found or already processed")


@app.get("/system/status")
def system_status():
    """Return local safety-control and scheduler status."""
    from backend.ai.guardrails import get_system_control_status
    from backend.heartbeat.engine import scheduler_status
    status = get_system_control_status()
    status["scheduler"] = scheduler_status()
    return status


@app.post("/system/emergency-stop")
def emergency_stop(request: SystemControlRequest = None):
    """Pause proactive jobs and reject queued hard actions."""
    from backend.ai.guardrails import set_emergency_stop
    from backend.heartbeat.engine import stop_scheduler, is_scheduler_running
    reason = request.reason if request and request.reason else "Emergency stop requested"
    status = set_emergency_stop(True, reason)
    stop_scheduler()
    status["scheduler"] = {"running": is_scheduler_running()}
    return status


@app.post("/system/resume")
def resume_system(request: SystemControlRequest = None):
    """Resume proactive jobs after an emergency stop."""
    from backend.ai.guardrails import set_emergency_stop
    from backend.heartbeat.engine import start_scheduler, is_scheduler_running
    reason = request.reason if request and request.reason else "Resumed by user"
    status = set_emergency_stop(False, reason)
    start_scheduler()
    status["scheduler"] = {"running": is_scheduler_running()}
    return status


# ── Local Admin / Observability ──

@app.get("/admin/dashboard")
def admin_dashboard():
    """Local admin/debug dashboard summary."""
    return {
        "health": health(),
        "sync": unified_sync_status(),
        "freshness": source_freshness(),
        "retention": retention_policy(),
        "models": models_status(),
    }


@app.get("/admin/audit-log")
def admin_audit_log(limit: int = 100):
    """Return local audit events from workflow and feedback tables."""
    conn = db.get_connection()
    events = []
    try:
        try:
            rows = conn.execute(
                "SELECT id, rule_name, action_type, result, created_at FROM workflow_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            events.extend({"type": "workflow", **dict(row)} for row in rows)
        except Exception:
            pass
        try:
            rows = conn.execute(
                "SELECT id, rating, comment, created_at FROM chat_feedback ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            events.extend({"type": "chat_feedback", **dict(row)} for row in rows)
        except Exception:
            pass
        return sorted(events, key=lambda item: str(item.get("created_at", "")), reverse=True)[:limit]
    finally:
        conn.close()


@app.get("/admin/request-log")
def admin_request_log(limit: int = 100):
    """Return recent local backend log lines for debugging."""
    log_path = Path(LOG_DIR) / "sudobrain.log"
    if not log_path.exists():
        return {"path": str(log_path), "lines": []}
    lines = log_path.read_text(errors="replace").splitlines()[-limit:]
    return {"path": str(log_path), "lines": lines}


@app.get("/usage/analytics")
def usage_analytics():
    """Local usage counts without sending telemetry."""
    conn = db.get_connection()
    try:
        counts = {}
        for table in [
            "recordings", "transcripts", "action_items", "decisions", "promises",
            "people", "projects", "workflow_rules", "workflow_log", "chat_feedback",
            "document_library", "bookmarks",
        ]:
            try:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"] if row else 0)
            except Exception:
                counts[table] = 0
        trends = {}
        for table, column in [
            ("recordings", "created_at"),
            ("action_items", "created_at"),
            ("decisions", "created_at"),
            ("promises", "created_at"),
            ("workflow_log", "created_at"),
            ("chat_feedback", "created_at"),
        ]:
            try:
                row = conn.execute(
                    f"""SELECT
                    COUNT(*) FILTER (WHERE {column} >= CURRENT_TIMESTAMP - INTERVAL '7 days') AS last_7_days,
                    COUNT(*) FILTER (WHERE {column} >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS last_30_days
                    FROM {table}"""
                ).fetchone()
                trends[table] = dict(row) if row else {}
            except Exception:
                trends[table] = {}
        return {
            "local_only": True,
            "counts": counts,
            "trends": trends,
            "quality": {
                "feedback_items": counts.get("chat_feedback", 0),
                "pending_reviews": len(review_queue(limit=200)["items"]),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        conn.close()


@app.get("/observability/status")
def observability_status():
    """Report local observability capabilities."""
    return {
        "logs": {"enabled": True, "path": str(Path(LOG_DIR) / "sudobrain.log")},
        "metrics": {"usage_analytics": "/usage/analytics", "request_metrics": "/observability/metrics"},
        "traces": {"workflow_trace": "/workflows/trace"},
        "opentelemetry": {"enabled": _truthy_env("SUDOBRAIN_OTEL_ENABLED", False), "env": "SUDOBRAIN_OTEL_ENABLED"},
    }


@app.get("/observability/metrics")
def observability_metrics(limit: int = Query(default=50, ge=1, le=200)):
    """Return local in-process request metrics and recent request timings."""
    top_paths = sorted(
        REQUEST_METRICS["by_path"].items(),
        key=lambda item: item[1],
        reverse=True,
    )[:25]
    recent = REQUEST_METRICS["recent"][-limit:]
    return {
        "local_only": True,
        "started_at": REQUEST_METRICS["started_at"],
        "total_requests": REQUEST_METRICS["total_requests"],
        "by_status": REQUEST_METRICS["by_status"],
        "top_paths": [{"path": path, "count": count} for path, count in top_paths],
        "recent": recent,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/security/policy")
def security_policy_status():
    """Return local RBAC, SSO, quota, and secrets policy status."""
    from backend.security.policy import security_policy
    return security_policy()


class LocalSecretRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    value: str = Field(..., min_length=1, max_length=20000)


class LocalMarkdownPreviewRequest(BaseModel):
    root: str = Field(..., min_length=1, max_length=2000)
    glob: str = "**/*.md"
    limit: int = Field(default=25, ge=1, le=100)


class GitHubPreviewRequest(BaseModel):
    repo: str = Field(..., min_length=3, max_length=300, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    token: Optional[str] = Field(None, max_length=500)
    limit: int = Field(default=25, ge=1, le=100)


class NotionPreviewRequest(BaseModel):
    token: Optional[str] = Field(None, max_length=500)
    limit: int = Field(default=25, ge=1, le=100)


class GoogleDrivePreviewRequest(BaseModel):
    token: Optional[str] = Field(None, max_length=500)
    query: Optional[str] = Field(None, max_length=1000)
    limit: int = Field(default=25, ge=1, le=100)


class ConfluencePreviewRequest(BaseModel):
    base_url: Optional[str] = Field(None, max_length=1000)
    email: Optional[str] = Field(None, max_length=320)
    token: Optional[str] = Field(None, max_length=500)
    bearer_token: Optional[str] = Field(None, max_length=1000)
    space_id: Optional[str] = Field(None, max_length=120)
    limit: int = Field(default=25, ge=1, le=100)


class JiraPreviewRequest(BaseModel):
    base_url: Optional[str] = Field(None, max_length=1000)
    email: Optional[str] = Field(None, max_length=320)
    token: Optional[str] = Field(None, max_length=500)
    bearer_token: Optional[str] = Field(None, max_length=1000)
    jql: Optional[str] = Field(None, max_length=1000)
    limit: int = Field(default=25, ge=1, le=100)


class AsanaPreviewRequest(BaseModel):
    token: Optional[str] = Field(None, max_length=500)
    workspace_gid: Optional[str] = Field(None, max_length=120)
    project_gid: Optional[str] = Field(None, max_length=120)
    limit: int = Field(default=25, ge=1, le=100)


class TrelloPreviewRequest(BaseModel):
    api_key: Optional[str] = Field(None, max_length=500)
    token: Optional[str] = Field(None, max_length=500)
    board_id: Optional[str] = Field(None, max_length=120)
    limit: int = Field(default=25, ge=1, le=100)


class ClickUpPreviewRequest(BaseModel):
    token: Optional[str] = Field(None, max_length=500)
    team_id: Optional[str] = Field(None, max_length=120)
    list_id: Optional[str] = Field(None, max_length=120)
    limit: int = Field(default=25, ge=1, le=100)


class IntelligencePreviewRequest(BaseModel):
    documents: list[dict] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=100)


class WorkflowActionPreviewRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


class MCPToolPreviewRequest(BaseModel):
    server: str = "sudobrain"
    name: str = Field(..., min_length=1, max_length=200)
    arguments: dict = Field(default_factory=dict)


@app.get("/security/secrets/status")
def local_secrets_status():
    """Return encrypted local secret-store status without secret values."""
    from backend.security.secrets import status
    return status()


@app.post("/security/secrets/key")
def local_secrets_generate_key():
    """Generate a Fernet key for SUDOBRAIN_SECRETS_KEY without storing it."""
    from backend.security.secrets import generate_key
    return {"key": generate_key(), "store_this_in": "SUDOBRAIN_SECRETS_KEY"}


@app.get("/security/secrets")
def local_secrets_list():
    """List encrypted local secret names without values."""
    from backend.security.secrets import list_secret_names
    try:
        return {"secrets": list_secret_names()}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/security/secrets")
def local_secrets_put(request: LocalSecretRequest):
    """Store a secret in the encrypted local store."""
    from backend.security.secrets import put_secret
    try:
        return put_secret(request.name, request.value)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/security/secrets/{name}")
def local_secrets_delete(name: str):
    """Delete a secret from the encrypted local store."""
    from backend.security.secrets import delete_secret
    try:
        return delete_secret(name)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/plugins")
def plugin_registry():
    """List built-in and discovered plugin manifests."""
    from backend.plugins.registry import discover_plugins
    return discover_plugins()


@app.get("/extensions")
def extension_runtime_registry():
    """List extension SDK examples that can run in safe preview mode."""
    from backend.extensions.runtime import list_extensions
    return list_extensions()


@app.get("/sources/catalog")
def source_connector_catalog(category: Optional[str] = None, status: Optional[str] = None):
    """List source connector contracts for supported and planned integrations."""
    from backend.connectors.catalog import connector_categories, list_source_connectors
    return {
        "sources": list_source_connectors(category=category, status=status),
        "categories": connector_categories(),
        "read_only_default": True,
    }


@app.post("/extensions/connectors/local-markdown/preview")
def extension_local_markdown_preview(request: LocalMarkdownPreviewRequest):
    """Preview the built-in local Markdown connector without ingesting data."""
    from backend.extensions.runtime import local_markdown_preview
    return local_markdown_preview(request.root, glob=request.glob, limit=request.limit)


@app.post("/extensions/connectors/github/preview")
def extension_github_preview(request: GitHubPreviewRequest):
    """Preview the read-only GitHub connector without ingesting data."""
    from backend.extensions.runtime import github_preview
    return github_preview(request.repo, limit=request.limit, token=request.token)


@app.post("/extensions/connectors/notion/preview")
def extension_notion_preview(request: NotionPreviewRequest):
    """Preview the read-only Notion connector without ingesting data."""
    from backend.extensions.runtime import notion_preview
    return notion_preview(limit=request.limit, token=request.token)


@app.post("/extensions/connectors/google-drive/preview")
def extension_google_drive_preview(request: GoogleDrivePreviewRequest):
    """Preview the read-only Google Drive connector without ingesting data."""
    from backend.extensions.runtime import google_drive_preview
    return google_drive_preview(limit=request.limit, token=request.token, query=request.query)


@app.post("/extensions/connectors/confluence/preview")
def extension_confluence_preview(request: ConfluencePreviewRequest):
    """Preview the read-only Confluence connector without ingesting data."""
    from backend.extensions.runtime import confluence_preview
    return confluence_preview(
        base_url=request.base_url,
        email=request.email,
        token=request.token,
        bearer_token=request.bearer_token,
        space_id=request.space_id,
        limit=request.limit,
    )


@app.post("/extensions/connectors/jira/preview")
def extension_jira_preview(request: JiraPreviewRequest):
    """Preview the read-only Jira connector without ingesting data."""
    from backend.extensions.runtime import jira_preview
    return jira_preview(
        base_url=request.base_url,
        email=request.email,
        token=request.token,
        bearer_token=request.bearer_token,
        jql=request.jql,
        limit=request.limit,
    )


@app.post("/extensions/connectors/asana/preview")
def extension_asana_preview(request: AsanaPreviewRequest):
    """Preview the read-only Asana connector without ingesting data."""
    from backend.extensions.runtime import asana_preview
    return asana_preview(
        token=request.token,
        workspace_gid=request.workspace_gid,
        project_gid=request.project_gid,
        limit=request.limit,
    )


@app.post("/extensions/connectors/trello/preview")
def extension_trello_preview(request: TrelloPreviewRequest):
    """Preview the read-only Trello connector without ingesting data."""
    from backend.extensions.runtime import trello_preview
    return trello_preview(
        api_key=request.api_key,
        token=request.token,
        board_id=request.board_id,
        limit=request.limit,
    )


@app.post("/extensions/connectors/clickup/preview")
def extension_clickup_preview(request: ClickUpPreviewRequest):
    """Preview the read-only ClickUp connector without ingesting data."""
    from backend.extensions.runtime import clickup_preview
    return clickup_preview(
        token=request.token,
        team_id=request.team_id,
        list_id=request.list_id,
        limit=request.limit,
    )


@app.post("/extensions/intelligence/keyword-risk/preview")
def extension_keyword_risk_preview(request: IntelligencePreviewRequest):
    """Preview the sample intelligence module without writing extracted knowledge."""
    from backend.extensions.runtime import keyword_risk_preview
    return keyword_risk_preview(request.documents, limit=request.limit)


@app.post("/extensions/actions/draft-notification/preview")
def extension_action_preview(request: WorkflowActionPreviewRequest):
    """Preview the sample workflow action in dry-run mode."""
    from backend.extensions.runtime import workflow_action_preview
    return workflow_action_preview(request.payload)


@app.get("/mcp/client/status")
def mcp_client_status():
    """Report configured external MCP servers without starting them."""
    from backend.mcp_client import load_mcp_servers
    return load_mcp_servers()


@app.get("/mcp/client/tools")
def mcp_client_tools():
    """List built-in and configured MCP tools without starting external servers."""
    from backend.mcp_client import list_mcp_tools
    return list_mcp_tools()


@app.post("/mcp/client/tools/preview")
def mcp_client_tool_preview(request: MCPToolPreviewRequest):
    """Preview an MCP tool call without executing it."""
    from backend.mcp_client import preview_tool_call
    return preview_tool_call(request.name, request.arguments, server=request.server)


# ── Fathom Integration Endpoints ──


@app.get("/fathom/status")
def fathom_status():
    """Check if Fathom integration is configured."""
    from backend.fathom.client import is_configured
    return {"configured": is_configured()}


@app.get("/fathom/meetings")
def fathom_meetings(limit: int = 25):
    """List meetings from Fathom."""
    from backend.fathom.client import is_configured, list_meetings
    if not is_configured():
        raise HTTPException(status_code=400, detail="FATHOM_API_TOKEN not configured in .env")
    limit = min(limit, 100)
    try:
        return list_meetings(limit=limit)
    except Exception as e:
        logger.error("Failed to list Fathom meetings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class FathomProcessRequest(BaseModel):
    share_url: str = ""
    recording_id: str = ""
    num_speakers: Optional[int] = Field(None, ge=1, le=20)


@app.post("/fathom/process")
def fathom_process(request: FathomProcessRequest, background_tasks: BackgroundTasks):
    """Trigger the Fathom -> SudoBrain pipeline for a specific recording."""
    from backend.fathom.client import is_configured, list_meetings as fm_list
    from backend.fathom.pipeline import run_fathom_pipeline

    if not is_configured():
        raise HTTPException(status_code=400, detail="FATHOM_API_TOKEN not configured in .env")

    share_url = request.share_url
    recording_id = request.recording_id

    if not share_url and not recording_id:
        raise HTTPException(status_code=400, detail="Provide share_url or recording_id")

    if not share_url:
        try:
            meetings = fm_list(limit=100)
            for m in meetings.get("items", []):
                if str(m.get("recording_id", "")) == recording_id:
                    share_url = m.get("share_url") or m.get("url", "")
                    break
            if not share_url:
                raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found in Fathom")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Failed to look up Fathom recording %s: %s", recording_id, e)
            raise HTTPException(status_code=500, detail=str(e))

    if not recording_id:
        recording_id = share_url.rstrip("/").split("/")[-1]

    background_tasks.add_task(run_fathom_pipeline, recording_id, share_url, request.num_speakers)
    return {
        "status": "accepted",
        "recording_id": recording_id,
        "message": "Fathom pipeline started in background",
    }


@app.post("/fathom/webhook")
async def fathom_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Fathom webhook events and auto-process recordings."""
    from backend.fathom.webhook import verify_webhook, parse_webhook_event
    from backend.fathom.pipeline import run_fathom_pipeline

    body = await request.body()

    webhook_id = request.headers.get("webhook-id", "")
    webhook_timestamp = request.headers.get("webhook-timestamp", "")
    webhook_signature = request.headers.get("webhook-signature", "")

    # Enforce signature verification when webhook secret is configured
    webhook_secret = os.getenv("FATHOM_WEBHOOK_SECRET", "")
    if webhook_secret:
        if not webhook_id or not webhook_signature:
            logger.warning("Fathom webhook received without signature headers")
            raise HTTPException(status_code=401, detail="Missing webhook signature headers")
        if not verify_webhook(body, webhook_id, webhook_timestamp, webhook_signature):
            logger.warning("Fathom webhook signature verification failed")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    else:
        logger.warning("FATHOM_WEBHOOK_SECRET not set — webhook signature not verified")

    payload = await request.json()
    event = parse_webhook_event(payload)

    logger.info("Fathom webhook received: %s for recording %s (%s)",
                event["event_type"], event["recording_id"], event["title"])

    share_url = event["share_url"] or event["url"]
    if not share_url:
        return JSONResponse(
            status_code=200,
            content={"status": "skipped", "reason": "no share_url in webhook payload"},
        )

    background_tasks.add_task(run_fathom_pipeline, event["recording_id"], share_url)

    return {
        "status": "accepted",
        "recording_id": event["recording_id"],
        "title": event["title"],
        "message": "Fathom pipeline started in background",
    }


@app.post("/fathom/sync")
def fathom_sync(limit: int = 5, background_tasks: BackgroundTasks = None):
    """Sync recent Fathom meetings that haven't been processed yet."""
    from backend.fathom.client import is_configured, list_meetings as fm_list
    from backend.fathom.pipeline import run_fathom_pipeline

    if not is_configured():
        raise HTTPException(status_code=400, detail="FATHOM_API_TOKEN not configured in .env")

    limit = min(limit, 25)
    meetings = fm_list(limit=limit)
    # Fathom can return more rows than requested; never queue more than caller asked.
    items = meetings.get("items", [])[:limit]

    # Find which Fathom recording IDs have already gone through the
    # Sarvam-backed audio pipeline. Lightweight Fathom transcript imports do not
    # satisfy the full requirement because Tamil/code-mixed audio needs Sarvam
    # translation.
    conn = db.get_connection()
    try:
        existing = conn.execute(
            "SELECT transcript_json FROM transcripts WHERE full_text IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    processed_fathom_ids = set()
    for row in existing:
        try:
            t = json.loads(row["transcript_json"])
            fathom_data = t.get("fathom", {})
            fid = fathom_data.get("fathom_recording_id", "")
            source = t.get("source", "")
            engine = (t.get("processing") or {}).get("engine", "")
            if fid and (source == "fathom_meeting" or engine == "sarvam"):
                processed_fathom_ids.add(fid)
        except (json.JSONDecodeError, TypeError):
            pass

    queued = []
    skipped = []
    for m in items:
        rid = str(m.get("recording_id", ""))
        share_url = m.get("share_url") or m.get("url", "")
        title = m.get("title", "Untitled")

        if rid in processed_fathom_ids:
            skipped.append({"recording_id": rid, "title": title, "reason": "already processed"})
            continue

        if not share_url:
            skipped.append({"recording_id": rid, "title": title, "reason": "no share_url"})
            continue

        if background_tasks:
            background_tasks.add_task(run_fathom_pipeline, rid, share_url)
        queued.append({"recording_id": rid, "title": title})

    logger.info("Fathom sync: %d queued, %d skipped out of %d", len(queued), len(skipped), len(items))
    return {
        "queued": queued,
        "skipped": skipped,
        "total_found": len(items),
        "total_queued": len(queued),
        "total_skipped": len(skipped),
    }


# ── Knowledge Graph Endpoints ──


@app.post("/graph/reset")
def graph_reset():
    """Wipe all Neo4j data — used for re-ingestion after name fixes."""
    from backend.graph.neo4j_client import get_driver
    driver = get_driver()
    if not driver:
        raise HTTPException(status_code=503, detail="Neo4j not available")
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    logger.info("Neo4j graph reset")
    return {"status": "reset"}


@app.post("/graph/reingest")
def graph_reingest():
    """Re-ingest all SQLite knowledge into Neo4j graph.

    Use after name resolution fixes or graph reset.
    """
    from backend.graph.neo4j_client import ingest_knowledge
    conn = db.get_connection()
    try:
        # Get all transcripts with extracted knowledge
        trans = conn.execute(
            "SELECT id, recording_id, transcript_json FROM transcripts"
        ).fetchall()
        ingested = 0
        for t in trans:
            try:
                tj = json.loads(t["transcript_json"])
            except Exception:
                continue

            tid = t["id"]
            ais = conn.execute(
                "SELECT text, assignee, due_date, project FROM action_items WHERE transcript_id = ?", (tid,)
            ).fetchall()
            decs = conn.execute(
                "SELECT text, made_by, context, project FROM decisions WHERE transcript_id = ?", (tid,)
            ).fetchall()
            try:
                proms = conn.execute(
                    "SELECT description, promised_by_name, promised_to_name, due_date FROM promises WHERE transcript_id = ?",
                    (tid,),
                ).fetchall()
            except Exception:
                proms = []

            # Find the project (from any item)
            project = None
            for a in ais:
                if a["project"]:
                    project = a["project"]
                    break
            if not project:
                for d in decs:
                    if d["project"]:
                        project = d["project"]
                        break

            knowledge = {
                "action_items": [{"text": a["text"], "assignee": a["assignee"],
                                  "due_date": a["due_date"]} for a in ais],
                "decisions": [{"text": d["text"], "made_by": d["made_by"],
                               "context": d["context"]} for d in decs],
                "promises": [{"text": p["description"], "promised_by": p["promised_by_name"],
                              "promised_to": p["promised_to_name"], "due_date": p["due_date"]} for p in proms],
                "topics": [],
                "project": project,
            }

            participants = [p.get("label", p.get("speaker_id", ""))
                            for p in tj.get("participants", [])]
            fathom_data = tj.get("fathom", {})
            meeting_date = fathom_data.get("recording_start_time", "")

            ingest_knowledge(knowledge, tid, meeting_date=meeting_date, participants=participants)
            ingested += 1
    finally:
        conn.close()

    return {"status": "reingested", "count": ingested}


@app.post("/people/cleanup")
def people_cleanup():
    """Clean up duplicate and junk person entries."""
    from backend.people.name_resolver import cleanup_junk_people
    result = cleanup_junk_people()
    return result


@app.get("/graph/status")
def graph_status():
    """Check Neo4j availability and graph statistics."""
    from backend.graph.neo4j_client import graph_stats
    return graph_stats()


@app.get("/graph/person/{name}")
def graph_person(name: str):
    """Get a person's full knowledge network."""
    from backend.graph.neo4j_client import get_person_network
    return get_person_network(name)


@app.get("/graph/project/{name}")
def graph_project(name: str):
    """Get everything connected to a project."""
    from backend.graph.neo4j_client import get_project_graph
    return get_project_graph(name)


@app.get("/graph/bottlenecks")
def graph_bottlenecks():
    """Find people blocking the most action items."""
    from backend.graph.neo4j_client import find_bottlenecks
    return find_bottlenecks()


@app.get("/graph/orphaned")
def graph_orphaned():
    """Find items not connected to any project."""
    from backend.graph.neo4j_client import find_orphaned_items
    return find_orphaned_items()


@app.get("/graph/canvas")
def graph_canvas(limit: int = Query(default=80, ge=10, le=300), q: Optional[str] = None):
    """Return a lightweight node-link graph for desktop visualization."""
    conn = db.get_connection()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(node_id: str, label: str, kind: str, **props):
        nodes[node_id] = {"id": node_id, "label": label or node_id, "kind": kind, **props}
        return node_id

    def edge(source: str, target: str, kind: str, **props):
        if source and target:
            edges.append({"source": source, "target": target, "kind": kind, **props})

    try:
        term = f"%{q.lower()}%" if q else None
        task_sql = "SELECT * FROM action_items WHERE status != 'dismissed'"
        params: list = []
        if term:
            task_sql += " AND LOWER(text) LIKE ?"
            params.append(term)
        task_sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        for r in conn.execute(task_sql, tuple(params)).fetchall():
            tid = node(f"task:{r['id']}", r["text"], "task", status=r.get("status"), due_date=r.get("due_date"))
            if r.get("assignee"):
                pid = node(f"person:{r['assignee'].lower()}", r["assignee"], "person")
                edge(pid, tid, "assigned")
            if r.get("project"):
                prid = node(f"project:{r['project'].lower()}", r["project"], "project")
                edge(tid, prid, "belongs_to")

        for r in conn.execute("SELECT * FROM promises WHERE status != 'dismissed' ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall():
            pid = node(f"promise:{r['id']}", r["description"], "promise", status=r.get("status"), due_date=r.get("due_date"))
            if r.get("promised_by_name"):
                by = node(f"person:{r['promised_by_name'].lower()}", r["promised_by_name"], "person")
                edge(by, pid, "promised")
            if r.get("promised_to_name"):
                to = node(f"person:{r['promised_to_name'].lower()}", r["promised_to_name"], "person")
                edge(pid, to, "to")

        for r in conn.execute("SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall():
            did = node(f"decision:{r['id']}", r["text"], "decision", project=r.get("project"))
            if r.get("project"):
                prid = node(f"project:{r['project'].lower()}", r["project"], "project")
                edge(did, prid, "belongs_to")
            if r.get("made_by"):
                person = node(f"person:{r['made_by'].lower()}", r["made_by"], "person")
                edge(person, did, "made")
    finally:
        conn.close()
    return {"nodes": list(nodes.values())[:limit], "edges": edges[:limit * 2], "total_nodes": len(nodes), "total_edges": len(edges)}


# ── Document Ingestion Endpoint ──


@app.post("/ingest")
async def ingest_document(request: Request):
    """Ingest a document (PDF, DOCX, TXT, MD) into the knowledge base.

    Extracts text, runs knowledge extraction, stores in DB + graph.
    Accepts multipart form upload.
    """
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    filename = file.filename
    content = await file.read()

    # Save uploaded file
    upload_dir = os.path.join(DATA_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{filename}")
    with open(file_path, "wb") as f:
        f.write(content)

    # Extract text based on file type
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    text = ""

    try:
        if ext == "pdf":
            import fitz
            doc = fitz.open(file_path)
            text = "\n\n".join(page.get_text() for page in doc)
            doc.close()
        elif ext == "docx":
            from docx import Document
            doc = Document(file_path)
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        elif ext in ("txt", "md", "markdown", "text"):
            text = content.decode("utf-8", errors="replace")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to extract text from %s: %s", filename, e)
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {e}")

    if not text or len(text.strip()) < 20:
        return {"status": "skipped", "reason": "File has no meaningful text content"}

    # Create a recording entry for the document
    recording_id = str(uuid.uuid4())
    db.save_recording(recording_id, "document", file_path)

    # Run knowledge extraction
    knowledge = None
    try:
        logger.info("Extracting knowledge from document: %s", filename)
        knowledge = local_llm_extract(text[:8000])

        if knowledge:
            transcript_id = str(uuid.uuid4())

            # Save as transcript entry
            transcript_data = {
                "id": transcript_id,
                "recording_id": recording_id,
                "source": "document",
                "created_at": datetime.now().isoformat(),
                "duration_seconds": 0,
                "language": {"primary": "en", "detected": ["en"], "is_code_mixed": False},
                "participants": [],
                "segments": [{"speaker_id": "document", "start_seconds": 0, "end_seconds": 0,
                              "text": text[:5000], "language": "en"}],
                "full_transcript": text[:5000],
                "processing": {"engine": "document", "model": "n/a",
                               "processed_at": datetime.now().isoformat(),
                               "audio_preprocessing": []},
            }
            db.save_transcript(transcript_data)

            for item in knowledge.get("action_items", []):
                db.save_action_item(
                    transcript_id=transcript_id, text=item.get("text", ""),
                    assignee=item.get("assignee"), project=knowledge.get("project"),
                    due_date=item.get("due_date"),
                )
            for item in knowledge.get("decisions", []):
                db.save_decision(
                    transcript_id=transcript_id, text=item.get("text", ""),
                    made_by=item.get("made_by"), context=item.get("context"),
                    project=knowledge.get("project"),
                )
            for item in knowledge.get("promises", []):
                _save_promise(transcript_id, item)

            # Ingest into graph
            try:
                from backend.graph.neo4j_client import ingest_knowledge
                ingest_knowledge(knowledge, transcript_id)
            except Exception as e:
                logger.warning("Graph ingestion skipped for document: %s", e)

            logger.info(
                "Document ingested: %s — %d actions, %d decisions, %d promises",
                filename,
                len(knowledge.get("action_items", [])),
                len(knowledge.get("decisions", [])),
                len(knowledge.get("promises", [])),
            )

    except Exception as e:
        logger.error("Document knowledge extraction failed: %s", e)

    return {
        "status": "completed",
        "filename": filename,
        "recording_id": recording_id,
        "text_length": len(text),
        "knowledge": knowledge,
    }


@app.get("/documents/library")
def document_library(limit: int = 100):
    """List locally registered documents."""
    from backend.documents.library import list_documents
    return list_documents(min(limit, 500))


@app.post("/documents/library")
async def register_library_document(request: Request):
    """Register a local document or extracted text record."""
    from backend.documents.library import register_document
    payload = await request.json()
    return register_document(
        path=payload.get("path", ""),
        text=payload.get("text", ""),
        title=payload.get("title"),
        source_type=payload.get("source_type", "file"),
        metadata_json=json.dumps(payload.get("metadata", {})),
    )


@app.get("/documents/watch-folders")
def watched_folders():
    """List local folders configured for document watch mode."""
    from backend.documents.library import list_watched_folders
    return list_watched_folders()


@app.post("/documents/watch-folders")
async def add_watch_folder(request: Request):
    """Register a folder for future watch-mode ingestion."""
    from backend.documents.library import add_watched_folder
    payload = await request.json()
    return add_watched_folder(payload.get("path", ""), payload.get("glob", "**/*"))


@app.get("/bookmarks")
def bookmarks(limit: int = 100):
    """List archived bookmarks."""
    from backend.documents.library import list_bookmarks
    return list_bookmarks(min(limit, 500))


@app.post("/bookmarks")
async def add_bookmark_capture(request: Request):
    """Archive a bookmark or webpage summary."""
    from backend.documents.library import add_bookmark
    payload = await request.json()
    return add_bookmark(
        url=payload.get("url", ""),
        title=payload.get("title", ""),
        summary=payload.get("summary", ""),
        metadata_json=json.dumps(payload.get("metadata", {})),
    )


@app.post("/webpage/summarize")
async def summarize_webpage_capture(request: Request):
    """Summarize provided webpage text without fetching remote content."""
    payload = await request.json()
    text = " ".join((payload.get("text") or "").split())
    summary = text[:700] + ("..." if len(text) > 700 else "")
    return {"title": payload.get("title", ""), "url": payload.get("url", ""), "summary": summary, "mode": "local_text_only"}


@app.post("/ocr/extract")
async def ocr_extract_capture(request: Request):
    """Register OCR/image ingestion text from a local client or OCR worker."""
    payload = await request.json()
    text = payload.get("text", "")
    if not text:
        return {"status": "needs_client_ocr", "message": "Send extracted text from the client or OCR worker."}
    from backend.documents.library import register_document
    return register_document(
        path=payload.get("path", "image://uploaded"),
        text=text,
        title=payload.get("title", "OCR capture"),
        source_type="ocr",
        metadata_json=json.dumps(payload.get("metadata", {})),
    )


# ── Smart Search (#9) ──

@app.get("/search/smart")
def smart_search(query: str = Query(..., min_length=1, max_length=500), top_k: int = 15):
    """InsightForge smart search — decomposes question into sub-queries."""
    from backend.intelligence.smart_search import insight_search
    return insight_search(query, min(top_k, 50))


# ── Email Draft (#10) ──

@app.get("/recordings/{recording_id}/email-draft")
def email_draft(recording_id: str):
    """Generate follow-up email draft from a meeting recording."""
    from backend.intelligence.email_drafter import draft_followup_email
    return draft_followup_email(recording_id)


@app.get("/recordings/{recording_id}/rich")
def rich_recording_detail(recording_id: str):
    """Unified meeting detail: transcript, minutes, extracted items and follow-up draft."""
    conn = db.get_connection()
    try:
        transcript_row = conn.execute(
            "SELECT id, full_text, transcript_json FROM transcripts WHERE recording_id = ? LIMIT 1",
            (recording_id,),
        ).fetchone()
        transcript_id = transcript_row["id"] if transcript_row else None
        tasks = decisions = promises = []
        if transcript_id:
            tasks = [dict(r) for r in conn.execute("SELECT * FROM action_items WHERE transcript_id = ? ORDER BY created_at DESC", (transcript_id,)).fetchall()]
            decisions = [dict(r) for r in conn.execute("SELECT * FROM decisions WHERE transcript_id = ? ORDER BY created_at DESC", (transcript_id,)).fetchall()]
            promises = [dict(r) for r in conn.execute("SELECT * FROM promises WHERE transcript_id = ? ORDER BY created_at DESC", (transcript_id,)).fetchall()]
    finally:
        conn.close()

    minutes = {}
    draft = {}
    try:
        minutes = generate_minutes(recording_id)
    except Exception as e:
        minutes = {"error": str(e)}
    try:
        draft = email_draft(recording_id)
    except Exception as e:
        draft = {"error": str(e)}
    return {
        "recording_id": recording_id,
        "transcript_id": transcript_id,
        "transcript": json.loads(transcript_row["transcript_json"]) if transcript_row and transcript_row.get("transcript_json") else {},
        "full_text": transcript_row["full_text"] if transcript_row else "",
        "minutes": minutes,
        "email_draft": draft,
        "tasks": tasks,
        "decisions": decisions,
        "promises": promises,
    }


# ── Workflows (#11) ──

@app.get("/workflows")
def list_workflows():
    """List all workflow rules."""
    from backend.intelligence.workflows import list_rules
    return list_rules()


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    trigger_type: str
    action_type: str
    condition: Optional[dict] = None
    action_params: Optional[dict] = None


@app.post("/workflows")
def create_workflow(request: WorkflowCreateRequest):
    """Create a new workflow rule."""
    from backend.intelligence.workflows import create_rule
    rule_id = create_rule(request.name, request.trigger_type, request.action_type,
                          request.condition, request.action_params)
    return {"id": rule_id, "status": "created"}


@app.delete("/workflows/{rule_id}")
def delete_workflow(rule_id: int):
    """Delete a workflow rule."""
    from backend.intelligence.workflows import delete_rule
    delete_rule(rule_id)
    return {"status": "deleted"}


class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    trigger_type: Optional[str] = None
    action_type: Optional[str] = None
    condition: Optional[dict] = None
    action_params: Optional[dict] = None
    enabled: Optional[bool] = None


@app.patch("/workflows/{rule_id}")
def update_workflow(rule_id: int, request: WorkflowUpdateRequest):
    """Update a workflow rule, including enable/disable."""
    from backend.intelligence.workflows import update_rule
    if update_rule(rule_id, request.name, request.trigger_type, request.action_type,
                   request.condition, request.action_params, request.enabled):
        return {"status": "updated"}
    raise HTTPException(status_code=404, detail="Workflow not found or unchanged")


@app.post("/workflows/{rule_id}/toggle")
def toggle_workflow(rule_id: int, enabled: bool = Query(...)):
    from backend.intelligence.workflows import toggle_rule
    if toggle_rule(rule_id, enabled):
        return {"status": "updated", "enabled": enabled}
    raise HTTPException(status_code=404, detail="Workflow not found")


@app.post("/workflows/dry-run")
def dry_run_workflow(request: WorkflowCreateRequest):
    """Preview workflow matches without executing actions."""
    from backend.intelligence.workflows import preview_rule
    return preview_rule(trigger_type=request.trigger_type, condition=request.condition or {})


@app.get("/workflows/{rule_id}/dry-run")
def dry_run_saved_workflow(rule_id: int):
    from backend.intelligence.workflows import preview_rule
    return preview_rule(rule_id=rule_id)


@app.get("/workflows/templates")
def workflow_template_list():
    """List reusable workflow templates."""
    from backend.intelligence.workflows import workflow_templates
    return workflow_templates()


@app.get("/workflows/graph")
def workflow_graph():
    """Return workflow rules as a node-link graph for visual builders."""
    from backend.intelligence.workflows import list_rules, workflow_templates
    rules = list_rules()
    nodes = []
    edges = []
    for rule in rules:
        rid = f"rule:{rule['id']}"
        trigger_id = f"trigger:{rule['trigger_type']}"
        action_id = f"action:{rule['action_type']}"
        nodes.extend([
            {"id": trigger_id, "type": "trigger", "label": rule["trigger_type"]},
            {"id": rid, "type": "rule", "label": rule["name"], "enabled": rule.get("enabled")},
            {"id": action_id, "type": "action", "label": rule["action_type"]},
        ])
        edges.extend([
            {"source": trigger_id, "target": rid, "type": "activates"},
            {"source": rid, "target": action_id, "type": "executes"},
        ])
    return {
        "nodes": list({node["id"]: node for node in nodes}.values()),
        "edges": edges,
        "templates": workflow_templates(),
    }


@app.post("/workflows/evaluate")
def evaluate_workflows():
    """Manually trigger workflow evaluation."""
    from backend.intelligence.workflows import evaluate_rules
    return {"triggered": evaluate_rules()}


@app.get("/workflows/log")
def workflow_log(limit: int = 50):
    """Get workflow execution history."""
    from backend.intelligence.workflows import get_workflow_log
    return get_workflow_log(min(limit, 200))


@app.get("/workflows/trace")
def workflow_trace(limit: int = 100):
    """Get workflow tool-call and action trace history."""
    from backend.intelligence.workflows import get_workflow_trace
    return get_workflow_trace(min(limit, 500))


@app.get("/workflows/log/{log_id}/replay")
def workflow_replay(log_id: int):
    """Reconstruct a workflow run for read-only debugging/replay."""
    from backend.intelligence.workflows import get_workflow_replay
    replay = get_workflow_replay(log_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return replay


@app.get("/workflows/approvals")
def workflow_approvals(status: str = "pending", limit: int = 100):
    """List workflow actions waiting for approval."""
    from backend.intelligence.workflows import list_approvals
    return list_approvals(status=status, limit=min(limit, 500))


@app.get("/workflows/outbox")
def workflow_outbox(status: Optional[str] = None, limit: int = 100):
    """List approved workflow write artifacts kept in the local outbox."""
    from backend.intelligence.workflows import list_outbox
    return list_outbox(status=status, limit=min(limit, 500))


@app.post("/workflows/approvals/{approval_id}/approve")
def approve_workflow_action(approval_id: int):
    from backend.intelligence.workflows import decide_approval
    if decide_approval(approval_id, True):
        return {"status": "approved"}
    raise HTTPException(status_code=404, detail="Approval not found")


@app.post("/workflows/approvals/{approval_id}/reject")
def reject_workflow_action(approval_id: int):
    from backend.intelligence.workflows import decide_approval
    if decide_approval(approval_id, False):
        return {"status": "rejected"}
    raise HTTPException(status_code=404, detail="Approval not found")


@app.post("/workflows/defaults")
def create_default_workflows():
    """Create default workflow rules."""
    from backend.intelligence.workflows import create_default_rules
    create_default_rules()
    return {"status": "defaults_created"}


# ── Intelligence Reports (#12) ──

@app.get("/reports/weekly")
def weekly_report():
    """Generate weekly intelligence report."""
    from backend.intelligence.reports import generate_weekly_report
    return generate_weekly_report()


@app.get("/reports/monthly")
def monthly_report():
    """Generate monthly intelligence report."""
    from backend.intelligence.reports import generate_monthly_report
    return generate_monthly_report()


def _report_markdown(report: dict) -> str:
    lines = [
        f"# SudoBrain {str(report.get('period', '')) .title()} Report",
        "",
        f"Period: {report.get('start_date', '')} to {report.get('end_date', '')}",
        "",
        "## Summary",
        "",
        str(report.get("narrative", "")),
        "",
        "## Metrics",
        "",
    ]
    for key in [
        "meetings", "total_recording_hours", "decisions_made", "tasks_created",
        "tasks_pending", "promises_made", "promises_kept", "promises_broken",
        "promise_rate", "people_interacted",
    ]:
        lines.append(f"- {key.replace('_', ' ').title()}: {report.get(key, '')}")
    lines.extend(["", "## Recent Decisions", ""])
    for decision in report.get("recent_decisions", []):
        lines.append(f"- {decision.get('text', '')} ({decision.get('project') or 'no project'})")
    return "\n".join(lines).strip() + "\n"


@app.get("/reports/{period}/export")
def export_report(period: str, format: str = Query(default="markdown", pattern="^(json|markdown)$")):
    """Export weekly or monthly report as JSON or Markdown."""
    if period == "weekly":
        report = weekly_report()
    elif period == "monthly":
        report = monthly_report()
    else:
        raise HTTPException(status_code=400, detail="period must be weekly or monthly")
    if format == "json":
        return report
    return PlainTextResponse(_report_markdown(report), media_type="text/markdown")


@app.post("/reports/{period}/share")
def share_report(period: str):
    """Create a local share artifact instead of publishing externally."""
    if period not in {"weekly", "monthly"}:
        raise HTTPException(status_code=400, detail="period must be weekly or monthly")
    report = weekly_report() if period == "weekly" else monthly_report()
    share_dir = Path(DATA_DIR) / "shared_reports"
    share_dir.mkdir(parents=True, exist_ok=True)
    target = share_dir / f"{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target.write_text(_report_markdown(report))
    return {"status": "stored", "path": str(target), "external_publish": False}


# ── Sentiment Tracking (#13) ──

@app.get("/sentiment/trend")
def sentiment_trend(days: int = 30):
    """Get sentiment trend over last N days."""
    from backend.intelligence.sentiment import get_sentiment_trend
    return get_sentiment_trend(min(days, 365))


@app.get("/sentiment/person/{name}")
def sentiment_by_person(name: str):
    """Get sentiment for meetings involving a person."""
    from backend.intelligence.sentiment import get_sentiment_by_person
    return get_sentiment_by_person(name)


@app.post("/sentiment/analyze")
def analyze_sentiment_endpoint(text: str = Query(..., min_length=10)):
    """Analyze sentiment of text."""
    from backend.intelligence.sentiment import analyze_transcript_sentiment
    return analyze_transcript_sentiment(text)


# ── Personal CRM (#14) ──

@app.get("/crm/health")
def crm_health():
    """Get all contacts with relationship health scores."""
    from backend.intelligence.crm import get_relationship_health
    return get_relationship_health()


@app.get("/crm/stale")
def crm_stale(days: int = 30):
    """Get contacts you haven't interacted with in N days."""
    from backend.intelligence.crm import get_stale_contacts
    return get_stale_contacts(days)


@app.get("/crm/top-contacts")
def crm_top(limit: int = 10, days: int = 30):
    """Get most frequent contacts in the last N days."""
    from backend.intelligence.crm import get_top_contacts
    return get_top_contacts(min(limit, 50), days)


@app.get("/crm/contact/{name}")
def crm_contact(name: str):
    """Get full interaction history with a person."""
    from backend.intelligence.crm import get_contact_history
    return get_contact_history(name)


# ── Task Dependencies (#15) ──

class TaskDepRequest(BaseModel):
    blocker_task_id: int
    blocked_task_id: int


@app.post("/tasks/dependency")
def add_task_dep(request: TaskDepRequest):
    """Mark that one task blocks another."""
    from backend.intelligence.task_deps import add_dependency
    add_dependency(request.blocker_task_id, request.blocked_task_id)
    return {"status": "dependency_added"}


@app.delete("/tasks/dependency")
def remove_task_dep(request: TaskDepRequest):
    """Remove a task dependency."""
    from backend.intelligence.task_deps import remove_dependency
    remove_dependency(request.blocker_task_id, request.blocked_task_id)
    return {"status": "dependency_removed"}


@app.get("/tasks/blocked")
def blocked_tasks():
    """Get all tasks blocked by other tasks."""
    from backend.intelligence.task_deps import get_blocked_tasks
    return get_blocked_tasks()


@app.get("/tasks/critical-path")
def critical_path():
    """Get the critical path of dependent tasks."""
    from backend.intelligence.task_deps import get_critical_path
    return get_critical_path()


@app.get("/tasks/blocking-summary")
def blocking_summary():
    """Get summary of who's blocking what."""
    from backend.intelligence.task_deps import get_blocking_summary
    return get_blocking_summary()


# ── Meeting Scoring Trends (#18) ──

@app.get("/meetings/score-trend")
def meeting_score_trend(days: int = 30):
    """Get meeting effectiveness trend."""
    from backend.intelligence.meeting_trends import get_score_trend
    return get_score_trend(min(days, 365))


@app.get("/meetings/worst")
def worst_meetings(limit: int = 5):
    """Get lowest scoring meetings for reflection."""
    from backend.intelligence.meeting_trends import get_worst_meetings
    return get_worst_meetings(min(limit, 20))


# ── ChromaDB Vector Store (#6) ──

@app.get("/vectors/status")
def vector_status():
    """Get vector store status."""
    from backend.storage.chroma_store import is_available, count
    return {"available": is_available(), "count": count()}


@app.post("/vectors/sync")
def vector_sync():
    """Sync all SQLite data into ChromaDB."""
    from backend.storage.chroma_store import sync_from_sqlite
    synced = sync_from_sqlite()
    return {"synced": synced}


# ── Local Whisper (#7) ──

@app.get("/whisper/status")
def whisper_status():
    """Check if local Whisper is available."""
    from backend.transcription.whisper_client import is_available
    return {"available": is_available()}


# ── Slack Integration ──


@app.get("/slack/status")
def slack_status():
    """Get Slack integration status and sync stats."""
    from backend.slack.client import is_available
    from backend.slack.sync import get_sync_status
    return {
        "available": is_available(),
        "stats": get_sync_status(),
    }


@app.post("/slack/sync/channels")
def slack_sync_channels():
    """Sync the list of Slack channels (no messages)."""
    from backend.slack.sync import sync_channels
    return sync_channels()


@app.post("/slack/sync/users")
def slack_sync_users():
    """Sync active Slack users and merge with people graph."""
    from backend.slack.sync import sync_users
    return sync_users()


class SlackSyncRequest(BaseModel):
    channels: Optional[list[str]] = None
    messages_per_channel: int = Field(default=50, ge=1, le=500)
    days: int = Field(default=30, ge=1, le=365)
    extract_knowledge: bool = True


@app.post("/slack/sync")
def slack_sync(request: SlackSyncRequest = None):
    """Run a full Slack sync (last 30 days of messages).

    Excludes alerts/bot channels automatically.
    """
    from backend.slack.sync import sync_all
    req = request or SlackSyncRequest()
    return sync_all(
        channel_filter=req.channels,
        messages_per_channel=req.messages_per_channel,
        days=req.days,
        extract_knowledge=req.extract_knowledge,
    )


@app.get("/slack/channels")
def slack_list_channels(enabled_only: bool = True):
    """List all stored Slack channels."""
    conn = db.get_connection()
    try:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM slack_channels WHERE sync_enabled = TRUE ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM slack_channels ORDER BY name").fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/slack/messages/{channel_id}")
def slack_channel_messages(channel_id: str, limit: int = Query(50, ge=1, le=500)):
    """Get stored messages from a channel."""
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            SELECT m.*, c.name as channel_name
            FROM slack_messages m
            LEFT JOIN slack_channels c ON c.id = m.channel_id
            WHERE m.channel_id = ?
            ORDER BY m.ts DESC LIMIT ?
        """, (channel_id, limit)).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/slack/pending")
def slack_pending_tasks():
    """Get pending items from Slack — unanswered @-mentions, questions, promises."""
    from backend.slack.analysis import get_pending_items
    return get_pending_items()


@app.get("/slack/channel-health")
def slack_channel_health():
    """Get health metrics per channel."""
    from backend.slack.analysis import get_channel_health
    return get_channel_health()


@app.get("/slack/engagement")
def slack_engagement(days: int = 30):
    """Get engagement metrics across all channels."""
    from backend.slack.analysis import get_engagement_metrics
    return get_engagement_metrics(days)


@app.get("/slack/summary/{channel_id}")
def slack_channel_summary(channel_id: str, limit: int = 50):
    """Generate a conversation summary for a channel."""
    from backend.slack.analysis import get_conversation_summary
    return get_conversation_summary(channel_id, min(limit, 200))


@app.post("/slack/extract/{channel_id}")
def slack_extract_channel(
    channel_id: str,
    batch_size: int = Query(default=20, ge=1, le=100),
    max_messages: int = Query(default=100, ge=1, le=1000),
    max_batches: int = Query(default=1, ge=1, le=20),
):
    """Run bounded knowledge extraction on stored messages in a channel."""
    from backend.slack.ingest import extract_from_messages
    count = extract_from_messages(
        channel_id,
        batch_size=batch_size,
        max_messages=max_messages,
        max_batches=max_batches,
    )
    return {"channel_id": channel_id, "messages_processed": count}


@app.post("/slack/extract-all")
def slack_extract_all(
    channel_limit: int = Query(default=5, ge=1, le=50),
    batch_size: int = Query(default=20, ge=1, le=100),
    max_messages_per_channel: int = Query(default=100, ge=1, le=1000),
    max_batches_per_channel: int = Query(default=1, ge=1, le=20),
):
    """Run bounded knowledge extraction across enabled Slack channels."""
    from backend.slack.ingest import extract_pending_messages
    return extract_pending_messages(
        channel_limit=channel_limit,
        batch_size=batch_size,
        max_messages_per_channel=max_messages_per_channel,
        max_batches_per_channel=max_batches_per_channel,
    )


@app.post("/slack/validate")
def slack_validate(limit: int = Query(default=5000, ge=1, le=50000)):
    """Backfill Slack message validation for stored rows."""
    from backend.slack.ingest import backfill_message_validation
    return backfill_message_validation(limit=limit)


# ── Health Correlation (#20) ──

@app.get("/health-correlation")
def health_correlation(days: int = 30):
    """Get habit/health vs productivity correlation."""
    from backend.intelligence.health_correlation import get_habit_productivity_correlation
    return get_habit_productivity_correlation(min(days, 365))


class HealthDataRequest(BaseModel):
    data_type: str = Field(..., min_length=1, max_length=50)
    value: float
    date: Optional[str] = None


@app.post("/health-data")
def store_health_data(request: HealthDataRequest):
    """Store health data from HealthKit or manual entry."""
    from backend.intelligence.health_correlation import store_health_data
    store_health_data(request.data_type, request.value, request.date)
    return {"status": "stored"}


# ── Whisper Transcription (#7) ──

@app.post("/transcribe/whisper")
def transcribe_with_whisper(audio_path: str):
    """Transcribe audio using local Whisper model."""
    from backend.transcription.whisper_client import transcribe, is_available
    if not is_available():
        raise HTTPException(status_code=400, detail="faster-whisper not available")
    import os
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return transcribe(audio_path)


# ── Gmail Integration ──


@app.get("/gmail/status")
def gmail_status():
    """Check email integration availability and sync stats."""
    from backend.gmail.client import is_available
    from backend.gmail.ingest import get_email_stats
    return {"available": is_available(), "stats": get_email_stats()}


@app.post("/gmail/sync")
def gmail_sync(days: int = 30, max_results: int = 30, background_tasks: BackgroundTasks = None):
    """Fetch recent important emails with full body and extract knowledge.

    Runs in background and extracts knowledge locally.
    Check /gmail/status to see progress.
    """
    from backend.gmail.ingest import init_gmail_tables
    init_gmail_tables()

    def _do_sync():
        from backend.gmail.client import get_smart_emails
        from backend.gmail.ingest import store_message, extract_from_emails

        logger.info("Gmail sync: fetching via direct API (last %d days)...", days)

        # Direct API — fetches full bodies instantly, no LLM call per email fetch
        emails = get_smart_emails(days=days, max_results=min(max_results, 100))
        logger.info("Gmail sync: got %d human emails (filtered automated noise)", len(emails))

        stored = 0
        for email in emails:
            if store_message(email):
                stored += 1

        extracted = extract_from_emails(limit=stored)
        logger.info("Gmail sync complete: %d stored, %d extracted", stored, extracted)

    if background_tasks:
        background_tasks.add_task(_do_sync)
        return {"status": "accepted", "message": "Gmail sync started in background"}
    else:
        _do_sync()
        from backend.gmail.ingest import get_email_stats
        return get_email_stats()


@app.get("/gmail/pending")
def gmail_pending(max_results: int = 20):
    """Get unread emails likely needing action."""
    from backend.gmail.client import get_action_emails
    return get_action_emails(max_results=min(max_results, 100))


@app.get("/gmail/search")
def gmail_search(q: str = Query(..., min_length=1), max_results: int = 20):
    """Search Gmail with a query string."""
    from backend.gmail.client import search_emails
    return search_emails(q, max_results=min(max_results, 100))


# ── Calendar Integration ──


@app.get("/calendar/status")
def calendar_status():
    """Check Google Calendar API availability (direct path)."""
    from backend.calendar.direct_client import is_available
    return {"available": is_available()}


@app.get("/calendar/today")
def calendar_today():
    """Get today's events (direct API)."""
    from backend.calendar.direct_client import get_todays_events
    return get_todays_events()


@app.get("/calendar/upcoming")
def calendar_upcoming(days: int = 3):
    """Get upcoming events for the next N days (direct API)."""
    from backend.calendar.direct_client import get_upcoming_events
    return get_upcoming_events(min(days, 60))


@app.get("/calendar/past")
def calendar_past(days: int = 30):
    """Get past events for the last N days (direct API)."""
    from backend.calendar.direct_client import get_past_events
    return get_past_events(min(days, 90))


@app.get("/calendar/next-meeting")
def calendar_next_meeting():
    """Get the next upcoming meeting and pre-meeting prep context."""
    from backend.calendar.direct_client import get_next_meeting
    event = get_next_meeting()
    if not event:
        return {"event": None, "message": "No upcoming meetings"}
    # Compose lightweight prep context using attendee_emails to look up canonical people
    from backend.storage.database import get_connection
    conn = get_connection()
    try:
        emails = event.get("attendee_emails") or []
        people = []
        for em in emails:
            r = conn.execute(
                "SELECT id, name, email, organization FROM people WHERE LOWER(email) = ?",
                (em,),
            ).fetchone()
            if r:
                p = dict(r._row)
                # pull pending promises and tasks
                pr = conn.execute(
                    "SELECT description, due_date FROM promises "
                    "WHERE promised_to_name = ? AND status = 'pending' LIMIT 5",
                    (p["name"],),
                ).fetchall()
                ai = conn.execute(
                    "SELECT text FROM action_items WHERE assignee = ? AND status = 'pending' LIMIT 5",
                    (p["name"],),
                ).fetchall()
                p["pending_promises_to_them"] = [dict(x._row) for x in pr]
                p["pending_tasks"] = [dict(x._row) for x in ai]
                people.append(p)
    finally:
        conn.close()
    return {"event": event, "attendees": people}


# ── Model Router ──


@app.get("/models/status")
def models_status():
    """Get available models and their tier assignments."""
    from backend.ai.model_router import _get_available_models, TIER_MAP, get_model
    from backend.ai.providers import configured_providers
    available = list(_get_available_models())
    assignments = {task: get_model(task) for task in TIER_MAP}
    return {"available_models": available, "task_assignments": assignments, "provider_config": configured_providers()}


@app.get("/models/providers/health")
def model_provider_health():
    """Return safe provider health/configuration status."""
    from backend.ai.providers import provider_health
    return provider_health()


@app.post("/models/providers/test")
async def model_provider_test(request: Request):
    """Run an opt-in provider completion test."""
    from backend.ai.providers import complete_with_provider
    payload = await request.json()
    prompt = payload.get("prompt", "Reply with the word ok.")
    provider = payload.get("provider")
    return complete_with_provider(prompt=prompt[:2000], provider=provider, max_tokens=min(int(payload.get("max_tokens", 64)), 512))


@app.post("/models/refresh")
def models_refresh():
    """Refresh available model detection (run after pulling new models)."""
    from backend.ai.model_router import invalidate_cache, _get_available_models
    invalidate_cache()
    models = list(_get_available_models())
    return {"available_models": models, "count": len(models)}


# ── Linear Integration ──


@app.get("/linear/status")
def linear_status():
    """Check Linear API availability and sync stats."""
    from backend.linear.client import is_available, get_viewer
    from backend.linear.ingest import get_issue_stats, init_linear_tables
    init_linear_tables()
    available = is_available()
    stats = get_issue_stats() if available else {}
    viewer = get_viewer() if available else {}
    return {"available": available, "viewer": viewer, "stats": stats}


@app.post("/linear/sync")
def linear_sync(days: int = 30, include_done: bool = False,
                background_tasks: BackgroundTasks = None):
    """Sync all Linear issues, projects and members."""
    from backend.linear.ingest import init_linear_tables
    init_linear_tables()

    def _do_sync():
        from backend.linear.client import get_issues, get_projects, get_members
        from backend.linear.ingest import store_issue, store_project, store_member, extract_from_issues

        logger.info("Linear sync: fetching members...")
        members = get_members()
        for m in members:
            store_member(m)
        logger.info("Linear: %d members stored", len(members))

        logger.info("Linear sync: fetching projects...")
        projects = get_projects()
        for p in projects:
            store_project(p)
        logger.info("Linear: %d projects stored", len(projects))

        logger.info("Linear sync: fetching issues (last %d days)...", days)
        issues = get_issues(days=days, include_done=include_done)
        for issue in issues:
            store_issue(issue)
        logger.info("Linear: %d issues stored", len(issues))

        extracted = extract_from_issues()
        logger.info("Linear: %d issues extracted", extracted)

    if background_tasks:
        background_tasks.add_task(_do_sync)
        return {"status": "accepted", "message": "Linear sync started in background"}
    else:
        _do_sync()
        from backend.linear.ingest import get_issue_stats
        return get_issue_stats()


@app.get("/linear/issues")
def linear_issues(state: Optional[str] = None, assignee: Optional[str] = None,
                  project: Optional[str] = None, limit: int = 50):
    """Get stored Linear issues with optional filters."""
    from backend.linear.ingest import init_linear_tables
    init_linear_tables()
    conn = db.get_connection()
    try:
        filters = ["state_type != 'cancelled'"]
        params = []
        if state:
            filters.append("state_name = ?")
            params.append(state)
        if assignee:
            filters.append("(assignee_name LIKE ? OR assignee_email LIKE ?)")
            params.extend([f"%{assignee}%", f"%{assignee}%"])
        if project:
            filters.append("project_name LIKE ?")
            params.append(f"%{project}%")

        where = " AND ".join(filters)
        params.append(min(limit, 200))

        rows = conn.execute(
            f"SELECT id, title, state_name, state_type, assignee_name, project_name, priority_label, due_date, url FROM linear_issues WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/linear/projects")
def linear_projects():
    """Get all stored Linear projects."""
    from backend.linear.ingest import init_linear_tables
    init_linear_tables()
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM linear_projects ORDER BY name"
        ).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/linear/bottlenecks")
def linear_bottlenecks():
    """Find people with most open issues in Linear."""
    from backend.linear.ingest import init_linear_tables
    init_linear_tables()
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            SELECT assignee_name, assignee_email,
                   COUNT(*) as open_count,
                   COUNT(CASE WHEN due_date < CURRENT_DATE THEN 1 END) as overdue_count,
                   COUNT(CASE WHEN priority <= 2 THEN 1 END) as urgent_count
            FROM linear_issues
            WHERE state_type IN ('unstarted', 'started')
              AND assignee_name IS NOT NULL AND assignee_name != ''
            GROUP BY assignee_name, assignee_email
            ORDER BY overdue_count DESC, open_count DESC
        """).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/linear/overdue")
def linear_overdue():
    """Get overdue Linear issues."""
    from backend.linear.ingest import init_linear_tables
    init_linear_tables()
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            SELECT id, title, assignee_name, project_name, due_date, priority_label, url
            FROM linear_issues
            WHERE due_date IS NOT NULL
              AND due_date < CURRENT_DATE
              AND state_type NOT IN ('completed', 'cancelled')
            ORDER BY due_date ASC
        """).fetchall()
        return [dict(r._row) for r in rows]
    finally:
        conn.close()


@app.get("/sync/status")
def unified_sync_status():
    """Unified sync status across all data sources."""
    conn = db.get_connection()
    try:
        def q1(sql):
            try:
                r = conn.execute(sql).fetchone()
                return dict(r._row) if r else {}
            except Exception:
                return {}

        slack = q1("""
            SELECT COUNT(*) total, COUNT(*) FILTER (WHERE extracted) extracted,
                   MAX(message_at) AT TIME ZONE 'Asia/Kolkata' latest
            FROM slack_messages
        """)
        gmail = q1("""
            SELECT COUNT(*) total, COUNT(*) FILTER (WHERE extracted) extracted,
                   MAX(date) AT TIME ZONE 'Asia/Kolkata' latest
            FROM gmail_messages
        """)
        linear = q1("""
            SELECT COUNT(*) total, COUNT(*) FILTER (WHERE extracted) extracted,
                   MAX(updated_at) AT TIME ZONE 'Asia/Kolkata' latest
            FROM linear_issues
        """)
        slack_channels = q1("SELECT COUNT(*) total, COUNT(*) FILTER (WHERE sync_enabled) enabled FROM slack_channels")
        linear_projects = q1("SELECT COUNT(*) total FROM linear_projects")
        slack_users = q1("SELECT COUNT(*) total FROM slack_users")
        people = q1("SELECT COUNT(*) total, COUNT(*) FILTER (WHERE email IS NOT NULL AND email != '') with_email FROM people")
        source_sync = []
        try:
            rows = conn.execute("""
                SELECT DISTINCT ON (source) source, status, detail, completed_at
                FROM source_sync_log
                ORDER BY source, completed_at DESC
            """).fetchall()
            source_sync = [dict(r._row) for r in rows]
        except Exception:
            source_sync = []

        return {
            "slack": {**slack, "channels": slack_channels, "users": slack_users["total"]},
            "gmail": gmail,
            "linear": {**linear, "projects": linear_projects["total"]},
            "graph": {"people": people},
            "source_sync": source_sync,
        }
    finally:
        conn.close()


@app.get("/sync/audit")
def source_ingestion_audit():
    """DB/Neo4j-only audit for source ingestion health and dedupe."""
    from backend.source_audit import collect_source_audit
    return collect_source_audit()


def _knowledge_export_bundle(limit: int = 5000) -> dict:
    """Build a portable, non-secret knowledge export with provenance hints."""
    tables = [
        "projects", "people", "recordings", "transcripts", "segments",
        "action_items", "decisions", "promises", "reminders",
    ]
    conn = db.get_connection()
    bundle = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "format": "sudobrain-knowledge-export",
        "tables": {},
    }
    try:
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
                bundle["tables"][table] = [dict(r) for r in rows]
            except Exception as e:
                bundle["tables"][table] = {"error": str(e)}
    finally:
        conn.close()
    return bundle


def _knowledge_export_markdown(bundle: dict) -> str:
    lines = [
        "# SudoBrain Knowledge Export",
        "",
        f"Exported at: {bundle['exported_at']}",
        "",
    ]

    def rows(table: str) -> list[dict]:
        value = bundle["tables"].get(table, [])
        return value if isinstance(value, list) else []

    for project in rows("projects"):
        lines.extend([
            f"## Project: {project.get('name', 'Untitled')}",
            "",
            project.get("description") or "",
            "",
            f"Status: {project.get('status', 'unknown')}",
            "",
        ])

    for title, table, text_key in [
        ("Decisions", "decisions", "text"),
        ("Promises", "promises", "description"),
        ("Action Items", "action_items", "text"),
        ("People", "people", "name"),
    ]:
        lines.extend([f"## {title}", ""])
        for row in rows(table):
            source = row.get("transcript_id") or row.get("email") or row.get("id") or "unknown"
            detail = row.get(text_key) or ""
            metadata = []
            for key in ("project", "made_by", "assignee", "promised_by_name", "promised_to_name", "due_date", "status"):
                if row.get(key):
                    metadata.append(f"{key}: {row[key]}")
            suffix = f" ({'; '.join(metadata)})" if metadata else ""
            lines.append(f"- {detail}{suffix}")
            lines.append(f"  - Source: {source}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


@app.get("/knowledge/export")
def export_knowledge(format: str = Query(default="json", pattern="^(json|markdown)$"), limit: int = Query(default=5000, ge=1, le=20000)):
    """Export reviewable local knowledge as JSON or Markdown."""
    bundle = _knowledge_export_bundle(limit=limit)
    if format == "markdown":
        return PlainTextResponse(_knowledge_export_markdown(bundle), media_type="text/markdown")
    return bundle


def _safe_vault_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value or "").strip().replace(" ", "-")
    return (value or fallback)[:80]


@app.post("/knowledge/vault/export")
def export_knowledge_vault(limit: int = Query(default=5000, ge=1, le=20000)):
    """Write an editable Markdown/JSON knowledge vault under the local data directory."""
    bundle = _knowledge_export_bundle(limit=limit)
    export_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    vault_dir = Path(DATA_DIR) / "knowledge_vault" / export_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "sudobrain-export.json").write_text(json.dumps(bundle, indent=2, default=str))
    (vault_dir / "README.md").write_text(_knowledge_export_markdown(bundle))

    tables = bundle.get("tables", {})
    written = ["sudobrain-export.json", "README.md"]
    for table_name in ("projects", "people", "decisions", "promises", "action_items"):
        rows = tables.get(table_name, [])
        if not isinstance(rows, list):
            continue
        table_dir = vault_dir / table_name
        table_dir.mkdir(parents=True, exist_ok=True)
        for index, row in enumerate(rows, start=1):
            title = row.get("name") or row.get("text") or row.get("description") or row.get("email") or str(row.get("id") or index)
            filename = f"{index:04d}-{_safe_vault_name(str(title), table_name)}.md"
            frontmatter = {
                "sudobrain_table": table_name,
                "sudobrain_id": row.get("id"),
                "exported_at": bundle.get("exported_at"),
            }
            body = [
                "---",
                *[f"{key}: {json.dumps(value, default=str)}" for key, value in frontmatter.items()],
                "---",
                "",
                f"# {title}",
                "",
            ]
            for key, value in row.items():
                if value not in (None, ""):
                    body.append(f"- **{key}**: {value}")
            (table_dir / filename).write_text("\n".join(body).strip() + "\n")
            written.append(str(Path(table_name) / filename))

    return {
        "status": "exported",
        "path": str(vault_dir),
        "files": written,
        "obsidian_compatible": True,
    }


def _table_row(table: str, item_id: str) -> dict | None:
    allowed = {"action_items", "decisions", "promises", "people", "projects", "segments", "transcripts", "recordings"}
    if table not in allowed:
        return None
    conn = db.get_connection()
    try:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ? LIMIT 1", (item_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _confidence_for_row(kind: str, row: dict) -> dict:
    signals = []
    score = 0.55
    if row.get("transcript_id") or row.get("recording_id"):
        score += 0.15
        signals.append("linked_to_transcript")
    if row.get("source_start") is not None or row.get("source_end") is not None:
        score += 0.1
        signals.append("timestamped_source")
    if row.get("project"):
        score += 0.05
        signals.append("project_context")
    if row.get("due_date"):
        score += 0.05
        signals.append("dated_commitment")
    if kind == "people" and row.get("email"):
        score += 0.15
        signals.append("email_identity")
    score = max(0.05, min(score, 0.98))
    return {"score": round(score, 2), "signals": signals or ["stored_local_record"]}


@app.get("/knowledge/provenance/{kind}/{item_id}")
def knowledge_provenance(kind: str, item_id: str):
    """Explain where a knowledge item came from and how confident SudoBrain should be."""
    table_map = {
        "action": "action_items",
        "task": "action_items",
        "decision": "decisions",
        "promise": "promises",
        "person": "people",
        "project": "projects",
        "segment": "segments",
    }
    table = table_map.get(kind, kind)
    row = _table_row(table, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    source = {}
    transcript_id = row.get("transcript_id")
    if transcript_id:
        transcript = _table_row("transcripts", transcript_id)
        if transcript:
            source["transcript"] = {
                "id": transcript.get("id"),
                "recording_id": transcript.get("recording_id"),
                "engine": transcript.get("engine"),
                "processed_at": transcript.get("processed_at"),
            }
            recording_id = transcript.get("recording_id")
            recording = _table_row("recordings", recording_id) if recording_id else None
            if recording:
                source["recording"] = {
                    "id": recording.get("id"),
                    "mode": recording.get("mode"),
                    "created_at": recording.get("created_at"),
                    "status": recording.get("status"),
                }

    return {
        "kind": kind,
        "table": table,
        "item": row,
        "source": source,
        "confidence": _confidence_for_row(table, row),
        "explanation": "This item is derived from local SudoBrain storage. Linked transcript and recording metadata are shown when available.",
    }


@app.get("/sources/freshness")
def source_freshness():
    """Summarize local source freshness for dashboard and onboarding use."""
    conn = db.get_connection()
    try:
        checks = []

        def add(source: str, sql: str, extracted_sql: str | None = None):
            try:
                row = conn.execute(sql).fetchone()
                data = dict(row) if row else {}
            except Exception as e:
                checks.append({"source": source, "ok": False, "error": str(e), "total": 0})
                return
            total = int(data.get("total") or 0)
            latest = data.get("latest")
            extracted = 0
            if extracted_sql:
                try:
                    extracted_row = conn.execute(extracted_sql).fetchone()
                    extracted = int((dict(extracted_row) if extracted_row else {}).get("extracted") or 0)
                except Exception:
                    extracted = 0
            checks.append({
                "source": source,
                "ok": total > 0,
                "total": total,
                "extracted": extracted,
                "latest": latest,
                "freshness": "has_data" if total > 0 else "empty",
            })

        add("recordings", "SELECT COUNT(*) AS total, MAX(created_at) AS latest FROM recordings")
        add("transcripts", "SELECT COUNT(*) AS total, MAX(processed_at) AS latest FROM transcripts")
        add("slack", "SELECT COUNT(*) AS total, MAX(message_at) AS latest FROM slack_messages", "SELECT COUNT(*) AS extracted FROM slack_messages WHERE extracted = TRUE")
        add("gmail", "SELECT COUNT(*) AS total, MAX(date) AS latest FROM gmail_messages", "SELECT COUNT(*) AS extracted FROM gmail_messages WHERE extracted = TRUE")
        add("linear", "SELECT COUNT(*) AS total, MAX(updated_at) AS latest FROM linear_issues", "SELECT COUNT(*) AS extracted FROM linear_issues WHERE extracted = TRUE")
        add("people", "SELECT COUNT(*) AS total, MAX(last_interaction) AS latest FROM people")
        add("projects", "SELECT COUNT(*) AS total, MAX(created_at) AS latest FROM projects")
        return {"sources": checks, "generated_at": datetime.now(timezone.utc).isoformat()}
    finally:
        conn.close()


@app.get("/graph/export")
def graph_export(format: str = Query(default="json", pattern="^(json|markdown)$")):
    """Export a human-reviewable graph artifact from local relational data."""
    conn = db.get_connection()
    try:
        nodes = []
        edges = []
        for table, label, name_col in [("people", "Person", "name"), ("projects", "Project", "name")]:
            try:
                rows = conn.execute(f"SELECT id, {name_col} AS name FROM {table} LIMIT 1000").fetchall()
                nodes.extend({"id": f"{label}:{r['id']}", "type": label, "label": r["name"]} for r in rows)
            except Exception:
                pass
        try:
            tasks = conn.execute("SELECT id, text, assignee, project FROM action_items LIMIT 1000").fetchall()
            for row in tasks:
                task_id = f"Task:{row['id']}"
                nodes.append({"id": task_id, "type": "Task", "label": row["text"]})
                if row.get("assignee"):
                    edges.append({"from": task_id, "to": row["assignee"], "type": "ASSIGNED_TO", "evidence": row["text"]})
                if row.get("project"):
                    edges.append({"from": task_id, "to": row["project"], "type": "BELONGS_TO", "evidence": row["text"]})
        except Exception:
            pass
        try:
            decisions = conn.execute("SELECT id, text, made_by, project FROM decisions LIMIT 1000").fetchall()
            for row in decisions:
                dec_id = f"Decision:{row['id']}"
                nodes.append({"id": dec_id, "type": "Decision", "label": row["text"]})
                if row.get("made_by"):
                    edges.append({"from": row["made_by"], "to": dec_id, "type": "MADE", "evidence": row["text"]})
                if row.get("project"):
                    edges.append({"from": dec_id, "to": row["project"], "type": "AFFECTS", "evidence": row["text"]})
        except Exception:
            pass
        try:
            promises = conn.execute("SELECT id, description, promised_by_name, promised_to_name FROM promises LIMIT 1000").fetchall()
            for row in promises:
                prom_id = f"Promise:{row['id']}"
                nodes.append({"id": prom_id, "type": "Promise", "label": row["description"]})
                if row.get("promised_by_name"):
                    edges.append({"from": row["promised_by_name"], "to": prom_id, "type": "PROMISED", "evidence": row["description"]})
                if row.get("promised_to_name"):
                    edges.append({"from": prom_id, "to": row["promised_to_name"], "type": "OWED_TO", "evidence": row["description"]})
        except Exception:
            pass
    finally:
        conn.close()

    artifact = {"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "nodes": nodes, "edges": edges}
    if format == "markdown":
        lines = ["# SudoBrain Graph Export", "", "## Nodes", ""]
        lines.extend(f"- {n['type']}: {n['label']} (`{n['id']}`)" for n in nodes)
        lines.extend(["", "## Edges", ""])
        lines.extend(f"- {e['from']} --{e['type']}--> {e['to']}: {e.get('evidence', '')}" for e in edges)
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/markdown")
    return artifact


@app.get("/graph/edge/explain")
def explain_graph_edge(source: str, target: str, relation: str = ""):
    """Explain a graph edge from the portable local graph artifact."""
    artifact = graph_export()
    matches = [
        edge for edge in artifact["edges"]
        if str(edge.get("from", "")).lower() == source.lower()
        and str(edge.get("to", "")).lower() == target.lower()
        and (not relation or str(edge.get("type", "")).lower() == relation.lower())
    ]
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "matches": matches,
        "explanation": "Edges are derived from local tasks, decisions, and promises. Evidence text is included for review.",
    }


@app.get("/knowledge/trust-report")
def knowledge_trust_report(limit: int = Query(default=200, ge=1, le=1000)):
    """Summarize provenance, confidence, freshness, portability, and retention coverage."""
    conn = db.get_connection()
    try:
        provenance = {}
        for kind, table in [
            ("decisions", "decisions"),
            ("promises", "promises"),
            ("tasks", "action_items"),
            ("people", "people"),
        ]:
            try:
                rows = conn.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
            except Exception:
                provenance[kind] = {"total": 0, "with_source": 0, "average_confidence": 0, "signals": []}
                continue
            confidences = []
            signals = set()
            with_source = 0
            for row in rows:
                item = dict(row)
                if item.get("transcript_id") or item.get("recording_id") or item.get("email"):
                    with_source += 1
                confidence = _confidence_for_row(table, item)
                confidences.append(float(confidence.get("score", 0)))
                signals.update(confidence.get("signals", []))
            total = len(rows)
            provenance[kind] = {
                "total": total,
                "with_source": with_source,
                "source_coverage": round(with_source / total, 3) if total else 0,
                "average_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
                "signals": sorted(signals),
            }
    finally:
        conn.close()

    graph = graph_export()
    freshness = source_freshness()
    retention = retention_policy()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance,
        "freshness": freshness,
        "portability": {
            "knowledge_export": "/knowledge/export",
            "vault_export": "/knowledge/vault/export",
            "graph_export": "/graph/export",
            "graph_nodes": len(graph.get("nodes", [])),
            "graph_edges": len(graph.get("edges", [])),
        },
        "review": {
            "pending_items": len(review_queue(limit=limit).get("items", [])),
            "approval_bundle": "/review/bundle",
            "review_actions": "/review/actions",
        },
        "retention": retention,
    }


@app.get("/privacy/retention")
def retention_policy():
    """Return local data-retention settings."""
    config = _load_local_config()
    return {
        "audio_retention_days": int(config.get("SUDOBRAIN_AUDIO_RETENTION_DAYS", 30) or 30),
        "transcript_retention_days": int(config.get("SUDOBRAIN_TRANSCRIPT_RETENTION_DAYS", 365) or 365),
        "source_retention_days": int(config.get("SUDOBRAIN_SOURCE_RETENTION_DAYS", 365) or 365),
        "auto_delete_enabled": _truthy_env("SUDOBRAIN_RETENTION_AUTO_DELETE", False) or str(config.get("SUDOBRAIN_RETENTION_AUTO_DELETE", "")).lower() == "true",
        "config_path": str(CONFIG_PATH),
    }


@app.post("/privacy/retention")
async def save_retention_policy(request: Request):
    """Save retention settings without deleting data."""
    payload = await request.json()
    allowed = {
        "SUDOBRAIN_AUDIO_RETENTION_DAYS",
        "SUDOBRAIN_TRANSCRIPT_RETENTION_DAYS",
        "SUDOBRAIN_SOURCE_RETENTION_DAYS",
        "SUDOBRAIN_RETENTION_AUTO_DELETE",
    }
    config = _load_local_config()
    for key, value in payload.items():
        if key in allowed:
            config[key] = str(value)
    _save_local_config(config)
    return retention_policy()


@app.get("/privacy/sources")
def source_privacy_controls():
    """Return per-source privacy controls."""
    config = _load_local_config()
    from backend.connectors.catalog import connector_keys
    sources = sorted(connector_keys() | {"slack", "gmail", "fathom", "linear", "projects", "documents"})
    controls = {}
    for source in sources:
        prefix = f"SUDOBRAIN_PRIVACY_{source.upper()}"
        controls[source] = {
            "enabled": str(config.get(f"{prefix}_ENABLED", "true")).lower() != "false",
            "store_raw": str(config.get(f"{prefix}_STORE_RAW", "true")).lower() != "false",
            "extract_knowledge": str(config.get(f"{prefix}_EXTRACT", "true")).lower() != "false",
            "include_in_chat": str(config.get(f"{prefix}_CHAT", "true")).lower() != "false",
        }
    return {"sources": controls, "config_path": str(CONFIG_PATH)}


@app.post("/privacy/sources")
async def save_source_privacy_controls(request: Request):
    """Save per-source privacy controls without deleting existing data."""
    payload = await request.json()
    config = _load_local_config()
    from backend.connectors.catalog import connector_keys
    allowed_sources = connector_keys() | {"slack", "gmail", "fathom", "linear", "projects", "documents"}
    allowed_keys = {"enabled": "ENABLED", "store_raw": "STORE_RAW", "extract_knowledge": "EXTRACT", "include_in_chat": "CHAT"}
    for source, controls in payload.get("sources", {}).items():
        if source not in allowed_sources or not isinstance(controls, dict):
            continue
        for key, env_suffix in allowed_keys.items():
            if key in controls:
                config[f"SUDOBRAIN_PRIVACY_{source.upper()}_{env_suffix}"] = "true" if bool(controls[key]) else "false"
    _save_local_config(config)
    return source_privacy_controls()


@app.get("/privacy/retention/preview")
def retention_preview():
    """Preview records that would be affected by retention settings."""
    policy = retention_policy()
    conn = db.get_connection()
    try:
        previews = {}
        for table, column, days in [
            ("recordings", "created_at", policy["audio_retention_days"]),
            ("transcripts", "processed_at", policy["transcript_retention_days"]),
            ("slack_messages", "message_at", policy["source_retention_days"]),
            ("gmail_messages", "date", policy["source_retention_days"]),
        ]:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE {column} < CURRENT_TIMESTAMP - INTERVAL '{int(days)} days'"
                ).fetchone()
                previews[table] = int(row["count"] if row else 0)
            except Exception as e:
                previews[table] = {"error": str(e)}
        return {"policy": policy, "would_delete": previews, "dry_run": True}
    finally:
        conn.close()


@app.post("/chat/feedback")
async def chat_feedback(request: Request):
    """Store answer quality feedback for later review."""
    payload = await request.json()
    conn = db.get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_feedback (
                id SERIAL PRIMARY KEY,
                query TEXT,
                answer TEXT,
                rating TEXT,
                comment TEXT,
                source_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO chat_feedback (query, answer, rating, comment, source_json) VALUES (?, ?, ?, ?, ?)",
            (
                payload.get("query", ""),
                payload.get("answer", ""),
                payload.get("rating", ""),
                payload.get("comment", ""),
                json.dumps(payload.get("sources", [])),
            ),
        )
        conn.commit()
        return {"status": "saved"}
    finally:
        conn.close()


@app.post("/sync/run")
def run_unified_source_sync():
    """Run one read-only source sync pass for Gmail, Slack, and Fathom."""
    from backend.source_sync import run_source_sync_once
    return run_source_sync_once()


@app.get("/sync/export")
def export_sync_bundle():
    """Export non-secret local knowledge for another desktop install."""
    tables = [
        "recordings", "transcripts", "action_items", "decisions", "promises",
        "reminders", "projects", "ideas", "habits", "expenses", "workflow_rules",
    ]
    conn = db.get_connection()
    bundle = {"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    try:
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table} LIMIT 5000").fetchall()
                bundle["tables"][table] = [dict(r) for r in rows]
            except Exception as e:
                bundle["tables"][table] = {"error": str(e)}
    finally:
        conn.close()
    return bundle


@app.post("/sync/import")
async def import_sync_bundle(request: Request, dry_run: bool = True):
    """Validate a sync bundle. Import is dry-run by default for safety."""
    payload = await request.json()
    tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
    summary = {
        table: len(rows) if isinstance(rows, list) else 0
        for table, rows in tables.items()
    }
    if dry_run:
        return {"status": "validated", "dry_run": True, "summary": summary}
    # The write path is intentionally conservative: only stores the received
    # bundle under DATA_DIR for manual review instead of merging records blindly.
    imports_dir = Path(DATA_DIR) / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    target = imports_dir / f"sync_bundle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    target.write_text(json.dumps(payload, indent=2, default=str))
    return {"status": "stored_for_review", "path": str(target), "summary": summary}


@app.post("/projects/context/sync")
def sync_local_project_context():
    """Scan configured local repos and update project/contributor knowledge."""
    from backend.projects.context import sync_project_context
    return sync_project_context()


@app.get("/projects/context")
def get_local_project_context():
    """List configured local project context stored in SudoBrain."""
    from backend.projects.context import list_project_context
    return list_project_context()


@app.get("/intelligence/overload")
def intelligence_overload():
    """Composite overload score for the user."""
    from backend.intelligence.overload import compute_overload
    return compute_overload()


class CommitRiskRequest(BaseModel):
    text: str
    due_date: Optional[str] = None


@app.post("/intelligence/commit-risk")
def intelligence_commit_risk(req: CommitRiskRequest):
    """Predict probability of delivering a proposed commitment."""
    from backend.intelligence.commit_risk import predict_commit_risk
    return predict_commit_risk(req.text, req.due_date)


@app.get("/intelligence/focus")
def intelligence_focus(days: int = 14):
    """Daily focus/fragmentation index over the last N days."""
    from backend.intelligence.focus import compute_focus_trend
    return compute_focus_trend(days=min(days, 60))


@app.get("/intelligence/trust-map")
def intelligence_trust_map(min_sample: int = 2):
    """Per-person promise fulfillment rate ranking."""
    from backend.intelligence.trust_map import compute_trust_map
    return compute_trust_map(min_sample=min_sample)


@app.get("/intelligence/relationship-decay")
def intelligence_relationship_decay(window_days: int = 14):
    """Detect cooling/silent relationships compared to prior window."""
    from backend.intelligence.relationship_decay import compute_relationship_decay
    return compute_relationship_decay(window_days=window_days)


@app.get("/intelligence/customer-pulse")
def intelligence_customer_pulse():
    """External org engagement status via Gmail."""
    from backend.intelligence.customer_pulse import compute_customer_pulse
    return compute_customer_pulse()


@app.get("/intelligence/bus-factor")
def intelligence_bus_factor():
    """Per-project knowledge concentration + single-expert risk."""
    from backend.intelligence.bus_factor import compute_bus_factor
    return compute_bus_factor()


@app.get("/intelligence/project-risk")
def intelligence_project_risk():
    """Velocity + composite risk score per Linear project."""
    from backend.intelligence.project_risk import compute_project_risk
    return compute_project_risk()


@app.get("/intelligence/silent-projects")
def intelligence_silent_projects(threshold_days: int = 14):
    """Projects with no recent Linear or Slack activity."""
    from backend.intelligence.silent_projects import compute_silent_projects
    return compute_silent_projects(threshold_days=threshold_days)


@app.get("/intelligence/stale-decisions")
def intelligence_stale_decisions(min_age_days: int = 21):
    """Old decisions whose project still has fresh activity."""
    from backend.intelligence.stale_decisions import compute_stale_decisions
    return compute_stale_decisions(min_age_days=min_age_days)


@app.get("/intelligence/task-age-audit")
def intelligence_task_age_audit(threshold_days: int = 30):
    """Urgent tasks open too long + heavily overdue + stale action items."""
    from backend.intelligence.task_age_audit import compute_task_age_audit
    return compute_task_age_audit(threshold_days=threshold_days)


@app.get("/intelligence/recurring-problems")
def intelligence_recurring_problems(min_cluster_size: int = 3,
                                    threshold: float = 0.75):
    """Cluster semantically-similar tasks/issues to find recurring problems."""
    from backend.intelligence.recurring_problems import compute_recurring_problems
    return compute_recurring_problems(
        min_cluster_size=min_cluster_size,
        similarity_threshold=threshold,
    )


@app.get("/intelligence/emerging-topics")
def intelligence_emerging_topics(window_days: int = 7):
    """Terms spiking in recent window vs prior baseline."""
    from backend.intelligence.emerging_topics import compute_emerging_topics
    return compute_emerging_topics(window_days=window_days)


@app.get("/intelligence/conflicts")
def intelligence_conflicts(max_pairs: int = 10, use_llm: bool = True):
    """Detect semantically-similar decisions with contradictory content via LLM."""
    from backend.intelligence.conflicts import compute_conflicts
    return compute_conflicts(max_pairs=max_pairs, use_llm=use_llm)


@app.get("/intelligence/anomalies")
def intelligence_anomalies(days: int = 30, sigma: float = 2.0):
    """Daily stats vs rolling baseline; flags >Nσ deviations."""
    from backend.intelligence.anomalies import compute_anomalies
    return compute_anomalies(days=days, sigma=sigma)


@app.get("/intelligence/meeting-roi")
def intelligence_meeting_roi(days: int = 30):
    """Meeting output vs attendee-minutes cost."""
    from backend.intelligence.meeting_roi import compute_meeting_roi
    return compute_meeting_roi(days=days)


@app.get("/intelligence/meeting-rot")
def intelligence_meeting_rot():
    """Standing meetings with large person-minute cost."""
    from backend.intelligence.meeting_rot import compute_meeting_rot
    return compute_meeting_rot()


class FlagMarkRequest(BaseModel):
    flag_key: str
    status: str
    outcome: Optional[str] = None


@app.get("/intelligence/self-score")
def intelligence_self_score():
    """Per-feature precision based on user feedback on raised flags."""
    from backend.intelligence.flag_outcomes import compute_self_score, init_flag_table
    init_flag_table()
    return compute_self_score()


@app.post("/intelligence/flag-mark")
def intelligence_flag_mark(req: FlagMarkRequest):
    """User marks a flag as true/false positive, acted, or dismissed."""
    from backend.intelligence.flag_outcomes import mark_flag
    ok = mark_flag(req.flag_key, req.status, req.outcome)
    return {"ok": ok}


class CorrectionRequest(BaseModel):
    entity_type: str
    entity_id: str
    field: str
    old_value: Optional[str] = None
    new_value: str
    explanation: Optional[str] = None


@app.post("/intelligence/correction")
def intelligence_correction(req: CorrectionRequest):
    """Record a user correction of an extracted field."""
    from backend.intelligence.learned_rules import record_correction
    rid = record_correction(
        req.entity_type, req.entity_id, req.field,
        req.old_value or "", req.new_value, req.explanation,
    )
    return {"id": rid}


@app.post("/intelligence/compile-rules")
def intelligence_compile_rules(min_cluster_size: int = 2):
    """Promote repeated corrections into learned rules."""
    from backend.intelligence.learned_rules import compile_rules_from_corrections
    return compile_rules_from_corrections(min_cluster_size=min_cluster_size)


@app.get("/intelligence/learned-rules")
def intelligence_learned_rules(limit: int = 20):
    """List active learned rules that steer future extractions."""
    from backend.intelligence.learned_rules import get_active_rules
    return get_active_rules(limit=limit)


@app.post("/fathom/ingest")
def fathom_ingest_lightweight(days_back: int = 60, limit: int = 25,
                              run_extract: bool = True):
    """Lightweight Fathom ingest — uses Fathom transcripts directly (no audio download)."""
    from backend.fathom.ingest import sync_recent
    return sync_recent(days_back=days_back, limit=limit, run_extract=run_extract)


@app.post("/intelligence/run-now")
def intelligence_run_now(group: str = "all"):
    """Manually trigger scheduled intelligence jobs.

    group: 'all' | 'morning' | 'nightly' | 'weekly'
    """
    from backend.intelligence import scheduler as isched
    fn = {
        "all": isched.run_all_intelligence,
        "morning": isched.run_morning_intelligence,
        "nightly": isched.run_nightly_intelligence,
        "weekly": isched.run_weekly_intelligence,
    }.get(group)
    if not fn:
        raise HTTPException(status_code=400, detail="invalid group")
    return fn()


@app.post("/linear/sync/cycles")
def linear_sync_cycles():
    """Fetch Linear cycles (sprints) and store them."""
    from backend.linear.client import get_cycles
    cycles = get_cycles()
    return {"fetched": len(cycles), "cycles": [
        {"name": c.get("name"), "number": c.get("number"),
         "starts_at": c.get("startsAt"), "ends_at": c.get("endsAt"),
         "team": (c.get("team") or {}).get("name")}
        for c in cycles
    ]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8420)

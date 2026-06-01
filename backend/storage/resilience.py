"""Offline resilience — processing queue, integrity checks, backup with retention."""

import importlib.util
import json
import logging
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.resilience")


DEGRADATION_LEVELS = {
    0: {
        "name": "full_service",
        "label": "Level 0: Full service",
        "behavior": "All core local services are available. External transcription can run when Sarvam is reachable.",
    },
    1: {
        "name": "sarvam_down",
        "label": "Level 1: Sarvam down",
        "behavior": "Recording and local chat continue. New transcription work is queued or handled by local Whisper where possible.",
    },
    2: {
        "name": "offline",
        "label": "Level 2: Offline",
        "behavior": "Local recording, database search, offline chat, and DB-first heartbeat continue. Network integrations are skipped.",
    },
    3: {
        "name": "critical",
        "label": "Level 3: Critical",
        "behavior": "Database access is unhealthy. Mutating processing should stop and recovery/backup actions take priority.",
    },
}


def init_queue_table():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT,
                audio_path TEXT,
                mode TEXT DEFAULT 'voice_note',
                status TEXT DEFAULT 'queued',
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                error_message TEXT,
                queued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)
        conn.commit()
    finally:
        conn.close()


def queue_for_processing(recording_id: str, audio_path: str, mode: str = "voice_note"):
    """Queue a recording for later processing (when offline)."""
    init_queue_table()
    conn = get_connection()
    try:
        existing = conn.execute(
            """SELECT id FROM processing_queue
            WHERE recording_id = ? AND status IN ('queued', 'processing')""",
            (recording_id,),
        ).fetchone()
        if existing:
            return existing["id"]

        cursor = conn.execute(
            "INSERT INTO processing_queue (recording_id, audio_path, mode) VALUES (?, ?, ?)",
            (recording_id, audio_path, mode),
        )
        queue_id = cursor.lastrowid
        conn.commit()
        return queue_id
    finally:
        conn.close()


def get_queued_items(include_failed: bool = False) -> list:
    """Get all queued items pending processing."""
    init_queue_table()
    conn = get_connection()
    try:
        if include_failed:
            rows = conn.execute(
                "SELECT * FROM processing_queue ORDER BY queued_at ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM processing_queue WHERE status = 'queued' AND retry_count < max_retries ORDER BY queued_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_processing(queue_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE processing_queue SET status = 'processing' WHERE id = ?",
            (queue_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_completed(queue_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE processing_queue SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), queue_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(queue_id: int, error: str):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE processing_queue
            SET retry_count = retry_count + 1,
                status = CASE WHEN retry_count + 1 >= max_retries THEN 'failed' ELSE 'queued' END,
                error_message = ?
            WHERE id = ?""",
            (error, queue_id),
        )
        conn.commit()
    finally:
        conn.close()


def check_database_integrity() -> dict:
    """Check database integrity and stats (Postgres-compatible)."""
    conn = get_connection()
    try:
        # Check connection and get table list
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()

        row_counts = {}
        for t in tables:
            tname = t["table_name"]
            try:
                count = conn.execute(f'SELECT COUNT(*) as c FROM "{tname}"').fetchone()
                row_counts[tname] = count["c"]
            except Exception:
                row_counts[tname] = -1

        return {
            "integrity": "ok",
            "tables": len(tables),
            "row_counts": row_counts,
            "checked_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("Database integrity check failed: %s", e)
        return {
            "integrity": "error",
            "tables": 0,
            "row_counts": {},
            "error": str(e),
            "checked_at": datetime.now().isoformat(),
        }
    finally:
        conn.close()


def is_online(timeout: float = 2.0) -> bool:
    """Return whether the machine appears to have outbound network access."""
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=timeout):
            return True
    except OSError:
        return False


def is_sarvam_configured() -> bool:
    """Return whether Sarvam can be attempted without exposing the key."""
    return bool(os.getenv("SARVAM_API_KEY"))


def is_sarvam_available(timeout: float = 5.0) -> bool:
    """Check Sarvam reachability with a short, non-transcription probe."""
    if not is_sarvam_configured():
        return False

    request = urllib.request.Request(
        "https://api.sarvam.ai/health",
        method="GET",
        headers={"User-Agent": "SudoBrain-local-resilience-check/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 500
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500
    except Exception:
        return False


def _check_local_llm() -> dict:
    import shutil as _shutil

    llm_command = os.getenv("SUDOBRAIN_LLM_COMMAND", "").strip()
    models = []
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            data = json.loads(response.read().decode())
            models = [
                item.get("name") or item.get("model")
                for item in data.get("models", [])
                if item.get("name") or item.get("model")
            ]
    except Exception as e:
        logger.debug("Ollama status probe failed: %s", e)

    llm_cli_available = bool(llm_command and _shutil.which(llm_command))
    return {
        "available": bool(models and llm_cli_available),
        "ollama_available": bool(models),
        "ollama_models": models,
        "llm_cli_available": llm_cli_available,
        "llm_cli_configured": bool(llm_command),
    }


def _check_vector_store() -> dict:
    sentence_transformers_available = importlib.util.find_spec("sentence_transformers") is not None
    chromadb_available = importlib.util.find_spec("chromadb") is not None
    try:
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()
            embedding_count = row["c"] if row else 0
        finally:
            conn.close()
        table_ok = True
    except Exception as e:
        embedding_count = 0
        table_ok = False
        error = str(e)
    else:
        error = None

    result = {
        "available": bool(sentence_transformers_available),
        "embedding_count": embedding_count,
        "embedding_table_accessible": table_ok,
        "sentence_transformers_available": sentence_transformers_available,
        "chromadb_package_available": chromadb_available,
    }
    if error:
        result["error"] = error
    return result


def _check_whisper() -> dict:
    try:
        from backend.transcription.whisper_client import is_available
        return {"available": is_available()}
    except Exception as e:
        return {"available": False, "error": str(e)}


def get_degradation_status(live_checks: bool = False) -> dict:
    """Return the current graceful-degradation level and component evidence.

    `live_checks=False` keeps this local-only and avoids external network calls.
    Set it to True for an explicit short network/Sarvam probe.
    """
    db_status = check_database_integrity()
    local_llm = _check_local_llm()
    vector_store = _check_vector_store()
    whisper = _check_whisper()

    network = {"checked": live_checks, "available": None}
    sarvam = {
        "configured": is_sarvam_configured(),
        "checked": live_checks,
        "available": None,
    }

    if live_checks:
        network["available"] = is_online()
        sarvam["available"] = is_sarvam_available() if network["available"] else False

    local_core_ok = (
        db_status.get("integrity") == "ok"
        and local_llm.get("available")
        and whisper.get("available")
        and vector_store.get("available")
    )

    if db_status.get("integrity") != "ok":
        level = 3
        reason = "Database integrity check failed."
    elif live_checks and not network["available"]:
        level = 2
        reason = "Network probe failed; operating from local database/search."
    elif not local_core_ok:
        level = 2
        reason = "One or more local core services are unavailable."
    elif not sarvam["configured"] or (live_checks and not sarvam["available"]):
        level = 1
        reason = "Sarvam transcription is not available; queue or local Whisper fallback should be used."
    else:
        level = 0
        reason = "Local core services are healthy."

    return {
        "level": level,
        **DEGRADATION_LEVELS[level],
        "reason": reason,
        "local_core_ok": bool(local_core_ok),
        "checked_at": datetime.now().isoformat(),
        "components": {
            "database": db_status,
            "local_llm": local_llm,
            "vector_store": vector_store,
            "whisper": whisper,
            "network": network,
            "sarvam": sarvam,
        },
    }


def backup_database() -> str:
    """Create a Postgres backup using pg_dump."""
    import subprocess

    data_dir = os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain"))
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    backup_name = f"sudobrain_{date.today().isoformat()}.sql"
    backup_path = os.path.join(backup_dir, backup_name)

    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_database = os.getenv("POSTGRES_DATABASE", "sudobrain")

    env = os.environ.copy()
    env["PGPASSWORD"] = pg_password

    try:
        with open(backup_path, "w") as f:
            subprocess.run(
                ["pg_dump", "-h", pg_host, "-p", pg_port, "-U", pg_user, "-d", pg_database, "--no-owner"],
                stdout=f,
                env=env,
                check=True,
                timeout=300,
            )
        logger.info("Postgres backup created: %s", backup_path)
    except Exception as e:
        logger.error("pg_dump failed: %s", e)
        raise

    _cleanup_old_backups(backup_dir, keep_days=7)
    return backup_path


def _is_under_data_dir(path: str) -> bool:
    data_dir = os.path.realpath(os.getenv("SUDOBRAIN_DATA_DIR", os.path.expanduser("~/.sudobrain")))
    real_path = os.path.realpath(path)
    try:
        return os.path.commonpath([data_dir, real_path]) == data_dir
    except ValueError:
        return False


def _audio_converter_command(source_path: str, target_path: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            source_path,
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            target_path,
        ]

    afconvert = shutil.which("afconvert")
    if afconvert:
        return [
            afconvert,
            "-f",
            "m4af",
            "-d",
            "aac",
            "-q",
            "127",
            source_path,
            target_path,
        ]

    raise RuntimeError("No local audio converter found. Install ffmpeg or use macOS afconvert.")


def archive_old_audio(
    older_than_days: int = 30,
    limit: int = 10,
    dry_run: bool = False,
    recording_id: str = None,
) -> dict:
    """Convert old local WAV recordings to AAC/M4A and update Postgres after success."""
    older_than_days = max(1, min(int(older_than_days), 3650))
    limit = max(1, min(int(limit), 100))
    cutoff = datetime.now() - timedelta(days=older_than_days)

    clauses = [
        "audio_path IS NOT NULL",
        "LOWER(audio_path) LIKE ?",
        "created_at < ?",
    ]
    params = ["%.wav", cutoff]
    if recording_id:
        clauses.append("id = ?")
        params.append(recording_id)

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""SELECT id, audio_path, created_at, status
            FROM recordings
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at ASC
            LIMIT ?""",
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()

    archived = []
    skipped = []
    failed = []

    for row in rows:
        rec_id = row["id"]
        source_path = row["audio_path"]
        source = Path(source_path)
        target = source.with_suffix(".m4a")

        if not source.exists():
            skipped.append({"recording_id": rec_id, "reason": "source_missing", "audio_path": source_path})
            continue
        if not _is_under_data_dir(str(source)):
            skipped.append({"recording_id": rec_id, "reason": "outside_data_dir", "audio_path": source_path})
            continue
        if target.exists():
            skipped.append({"recording_id": rec_id, "reason": "target_exists", "audio_path": source_path, "target_path": str(target)})
            continue

        item = {
            "recording_id": rec_id,
            "source_path": str(source),
            "target_path": str(target),
            "created_at": str(row["created_at"]),
        }
        if dry_run:
            skipped.append({**item, "reason": "dry_run"})
            continue

        try:
            cmd = _audio_converter_command(str(source), str(target))
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=180)
            if not target.exists() or target.stat().st_size <= 0:
                raise RuntimeError("audio converter did not create a non-empty target file")

            conn = get_connection()
            try:
                conn.execute("UPDATE recordings SET audio_path = ? WHERE id = ?", (str(target), rec_id))
                conn.commit()
            finally:
                conn.close()

            source.unlink(missing_ok=True)
            archived.append({**item, "bytes": target.stat().st_size})
        except Exception as e:
            failed.append({**item, "error": str(e)})
            try:
                if target.exists() and target.stat().st_size == 0:
                    target.unlink(missing_ok=True)
            except Exception:
                pass

    return {
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "total_candidates": len(rows),
        "total_archived": len(archived),
        "total_skipped": len(skipped),
        "total_failed": len(failed),
        "archived": archived,
        "skipped": skipped,
        "failed": failed,
    }


def _cleanup_old_backups(backup_dir: str, keep_days: int = 7):
    """Remove backups older than keep_days."""
    cutoff = date.today() - timedelta(days=keep_days)
    removed = 0

    for filename in os.listdir(backup_dir):
        if not filename.startswith("sudobrain_"):
            continue
        if not (filename.endswith(".db") or filename.endswith(".sql")):
            continue
        # Extract date from filename: sudobrain_2026-04-01.db
        try:
            date_str = filename.replace("sudobrain_", "").replace(".db", "").replace(".sql", "")
            file_date = date.fromisoformat(date_str)
            if file_date < cutoff:
                os.remove(os.path.join(backup_dir, filename))
                removed += 1
        except (ValueError, OSError):
            continue

    if removed:
        logger.info("Cleaned up %d old backups (kept last %d days)", removed, keep_days)

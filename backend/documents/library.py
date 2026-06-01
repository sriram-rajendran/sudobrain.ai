"""Local document and bookmark library scaffolding."""

from __future__ import annotations

import hashlib
from pathlib import Path

from backend.storage.database import get_connection


def init_document_tables() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_library (
                id SERIAL PRIMARY KEY,
                path TEXT,
                title TEXT,
                source_type TEXT DEFAULT 'file',
                content_hash TEXT,
                extracted_text TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watched_folders (
                id SERIAL PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                glob TEXT DEFAULT '**/*',
                enabled BOOLEAN DEFAULT TRUE,
                last_scanned_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id SERIAL PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                summary TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def register_document(path: str, text: str = "", title: str | None = None, source_type: str = "file", metadata_json: str = "{}") -> dict:
    init_document_tables()
    content_hash = hashlib.sha256((text or path).encode("utf-8", errors="ignore")).hexdigest()
    doc_title = title or Path(path).name
    conn = get_connection()
    try:
        row = conn.execute(
            """INSERT INTO document_library (path, title, source_type, content_hash, extracted_text, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (path, doc_title, source_type, content_hash, text, metadata_json),
        ).fetchone()
        conn.commit()
        return {"id": row["id"] if row else None, "title": doc_title, "content_hash": content_hash}
    finally:
        conn.close()


def list_documents(limit: int = 100) -> list[dict]:
    init_document_tables()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, path, title, source_type, content_hash, created_at FROM document_library ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_watched_folder(path: str, glob: str = "**/*") -> dict:
    init_document_tables()
    conn = get_connection()
    try:
        row = conn.execute(
            """INSERT INTO watched_folders (path, glob)
            VALUES (?, ?)
            ON CONFLICT (path) DO UPDATE SET glob = EXCLUDED.glob, enabled = TRUE
            RETURNING id""",
            (path, glob),
        ).fetchone()
        conn.commit()
        return {"id": row["id"] if row else None, "path": path, "glob": glob, "enabled": True}
    finally:
        conn.close()


def list_watched_folders() -> list[dict]:
    init_document_tables()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM watched_folders ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_bookmark(url: str, title: str = "", summary: str = "", metadata_json: str = "{}") -> dict:
    init_document_tables()
    conn = get_connection()
    try:
        row = conn.execute(
            """INSERT INTO bookmarks (url, title, summary, metadata_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, summary = EXCLUDED.summary, metadata_json = EXCLUDED.metadata_json
            RETURNING id""",
            (url, title or url, summary, metadata_json),
        ).fetchone()
        conn.commit()
        return {"id": row["id"] if row else None, "url": url, "title": title or url}
    finally:
        conn.close()


def list_bookmarks(limit: int = 100) -> list[dict]:
    init_document_tables()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM bookmarks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

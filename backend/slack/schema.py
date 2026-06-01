"""Slack data storage schema — channels, messages, threads, users."""

import logging
from backend.storage.database import get_connection

logger = logging.getLogger("sudobrain.slack.schema")


_INITIALIZED = False


def init_slack_tables():
    """Create all Slack tables and indexes (idempotent, cached per-process)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS slack_users (
                id TEXT PRIMARY KEY,
                name TEXT,
                real_name TEXT,
                email TEXT,
                title TEXT,
                timezone TEXT,
                is_bot BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                person_id INTEGER,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS slack_channels (
                id TEXT PRIMARY KEY,
                name TEXT,
                topic TEXT,
                purpose TEXT,
                is_private BOOLEAN DEFAULT FALSE,
                is_dm BOOLEAN DEFAULT FALSE,
                is_archived BOOLEAN DEFAULT FALSE,
                member_count INTEGER DEFAULT 0,
                last_synced_at DATETIME,
                sync_enabled BOOLEAN DEFAULT TRUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE slack_channels ADD COLUMN IF NOT EXISTS is_dm BOOLEAN DEFAULT FALSE;

            CREATE TABLE IF NOT EXISTS slack_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                message_at TIMESTAMPTZ,
                channel_id TEXT NOT NULL,
                user_id TEXT,
                user_name TEXT,
                text TEXT,
                thread_ts TEXT,
                is_thread_parent BOOLEAN DEFAULT FALSE,
                reply_count INTEGER DEFAULT 0,
                reaction_count INTEGER DEFAULT 0,
                mention_users TEXT,
                is_bot_message BOOLEAN DEFAULT FALSE,
                validation_status TEXT DEFAULT 'unvalidated',
                validation_reason TEXT,
                extracted BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, ts)
            );
            ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS message_at TIMESTAMPTZ;
            ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS validation_status TEXT DEFAULT 'unvalidated';
            ALTER TABLE slack_messages ADD COLUMN IF NOT EXISTS validation_reason TEXT;
            ALTER TABLE slack_messages ALTER COLUMN message_at TYPE TIMESTAMPTZ USING (to_timestamp(ts::float));
            CREATE INDEX IF NOT EXISTS idx_slack_msg_at ON slack_messages(message_at);

            CREATE TABLE IF NOT EXISTS slack_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER REFERENCES slack_messages(id),
                user_id TEXT,
                emoji TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS slack_files (
                id TEXT PRIMARY KEY,
                channel_id TEXT,
                message_ts TEXT,
                filename TEXT,
                filetype TEXT,
                mimetype TEXT,
                size INTEGER DEFAULT 0,
                url_private TEXT,
                extracted_text TEXT,
                char_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_slack_files_channel ON slack_files(channel_id);
            CREATE INDEX IF NOT EXISTS idx_slack_files_msg ON slack_files(message_ts);

            CREATE TABLE IF NOT EXISTS slack_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_name TEXT,
                messages_fetched INTEGER DEFAULT 0,
                threads_fetched INTEGER DEFAULT 0,
                knowledge_extracted INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            );

            CREATE INDEX IF NOT EXISTS idx_slack_msg_channel ON slack_messages(channel_id);
            CREATE INDEX IF NOT EXISTS idx_slack_msg_user ON slack_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_slack_msg_thread ON slack_messages(thread_ts);
            CREATE INDEX IF NOT EXISTS idx_slack_msg_extracted ON slack_messages(extracted);
            CREATE INDEX IF NOT EXISTS idx_slack_msg_validation ON slack_messages(validation_status);
            CREATE INDEX IF NOT EXISTS idx_slack_msg_ts ON slack_messages(ts);
            CREATE INDEX IF NOT EXISTS idx_slack_chan_name ON slack_channels(name);
            CREATE INDEX IF NOT EXISTS idx_slack_user_email ON slack_users(email);

            UPDATE slack_messages
            SET validation_status = 'valid',
                validation_reason = 'previously_extracted'
            WHERE extracted = TRUE
              AND (validation_status IS NULL OR validation_status = 'unvalidated');
        """)
        conn.commit()
    finally:
        conn.close()

    _INITIALIZED = True
    logger.info("Slack tables initialized")

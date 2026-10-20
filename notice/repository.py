"""SQLite 기반 공지·일정 저장소."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent.schemas import NoticeExtraction


SEOUL = ZoneInfo("Asia/Seoul")


class NoticeRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    cleaned_text TEXT NOT NULL,
                    target_json TEXT NOT NULL,
                    action_required_json TEXT NOT NULL,
                    application_method TEXT,
                    source_image_path TEXT NOT NULL,
                    source_image_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('confirmed', 'needs_review')),
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notice_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    date_text TEXT NOT NULL,
                    start_at TEXT,
                    end_at TEXT,
                    all_day INTEGER NOT NULL DEFAULT 0,
                    location TEXT,
                    evidence_text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('confirmed', 'needs_review')),
                    confidence REAL NOT NULL,
                    FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notice_embeddings (
                    notice_id INTEGER PRIMARY KEY,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notice_recruitment_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id INTEGER NOT NULL,
                    position_order INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    responsibilities_json TEXT NOT NULL,
                    preferred_qualifications_json TEXT NOT NULL,
                    FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_notice_events_start_at
                ON notice_events(start_at);
                CREATE INDEX IF NOT EXISTS idx_notice_events_type
                ON notice_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_recruitment_positions_notice
                ON notice_recruitment_positions(notice_id, position_order);
                """
            )

    def save_notice(
        self,
        *,
        request_id: str,
        extraction: NoticeExtraction,
        source_image_path: str,
        source_image_hash: str,
        status: str,
    ) -> tuple[int, bool]:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM notices WHERE request_id = ?", (request_id,)
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            cursor = connection.execute(
                """
                INSERT INTO notices (
                    request_id, title, raw_text, cleaned_text, target_json, action_required_json,
                    application_method, source_image_path, source_image_hash,
                    status, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    extraction.title,
                    extraction.raw_text,
                    extraction.cleaned_text,
                    json.dumps(extraction.target, ensure_ascii=False),
                    json.dumps(extraction.action_required, ensure_ascii=False),
                    extraction.application_method,
                    source_image_path,
                    source_image_hash,
                    status,
                    extraction.confidence,
                    datetime.now(SEOUL).isoformat(),
                ),
            )
            notice_id = int(cursor.lastrowid)
            for event in extraction.events:
                event_status = "confirmed" if event.start_at else "needs_review"
                connection.execute(
                    """
                    INSERT INTO notice_events (
                        notice_id, event_type, date_text, start_at, end_at, all_day,
                        location, evidence_text, status, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        event.event_type,
                        event.date_text,
                        event.start_at,
                        event.end_at,
                        int(event.all_day),
                        event.location,
                        event.evidence_text,
                        event_status,
                        event.confidence,
                    ),
                )
            for position_order, position in enumerate(extraction.recruitment_positions):
                connection.execute(
                    """
                    INSERT INTO notice_recruitment_positions (
                        notice_id, position_order, name, responsibilities_json,
                        preferred_qualifications_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        position_order,
                        position.name,
                        json.dumps(position.responsibilities, ensure_ascii=False),
                        json.dumps(position.preferred_qualifications, ensure_ascii=False),
                    ),
                )
            return notice_id, True

    def get_notice(self, notice_id: int) -> dict | None:
        with self._connect() as connection:
            notice = connection.execute(
                "SELECT * FROM notices WHERE id = ?", (notice_id,)
            ).fetchone()
            if notice is None:
                return None
            events = connection.execute(
                "SELECT * FROM notice_events WHERE notice_id = ? ORDER BY start_at, id",
                (notice_id,),
            ).fetchall()
            positions = connection.execute(
                """
                SELECT name, responsibilities_json, preferred_qualifications_json
                FROM notice_recruitment_positions
                WHERE notice_id = ?
                ORDER BY position_order, id
                """,
                (notice_id,),
            ).fetchall()
        result = dict(notice)
        result["target"] = json.loads(result.pop("target_json"))
        result["action_required"] = json.loads(result.pop("action_required_json"))
        result["events"] = [dict(row) for row in events]
        result["recruitment_positions"] = [
            {
                "name": row["name"],
                "responsibilities": json.loads(row["responsibilities_json"]),
                "preferred_qualifications": json.loads(
                    row["preferred_qualifications_json"]
                ),
            }
            for row in positions
        ]
        return result

    def list_notices(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    n.id,
                    n.request_id,
                    n.title,
                    n.status,
                    n.confidence,
                    n.created_at,
                    COUNT(e.id) AS event_count,
                    MIN(e.start_at) AS first_event_at
                FROM notices AS n
                LEFT JOIN notice_events AS e ON e.notice_id = n.id
                GROUP BY n.id
                ORDER BY n.created_at DESC, n.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]


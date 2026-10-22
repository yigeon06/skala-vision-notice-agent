"""SQLite 기반 공지·일정 저장소."""

from __future__ import annotations

import json
import sqlite3
from array import array
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

                CREATE TABLE IF NOT EXISTS notice_embedding_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id INTEGER NOT NULL,
                    chunk_type TEXT NOT NULL CHECK(chunk_type IN (
                        'structured', 'cleaned_text', 'raw_text'
                    )),
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE,
                    UNIQUE(notice_id, chunk_type, chunk_index, provider, model)
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

                CREATE TABLE IF NOT EXISTS notice_additional_information (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notice_id INTEGER NOT NULL,
                    information_order INTEGER NOT NULL,
                    category TEXT NOT NULL CHECK(category IN (
                        'preferred_certification', 'required_document',
                        'disqualification', 'notice', 'other'
                    )),
                    title TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    needs_review INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(notice_id) REFERENCES notices(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_notice_events_start_at
                ON notice_events(start_at);
                CREATE INDEX IF NOT EXISTS idx_notice_events_type
                ON notice_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_recruitment_positions_notice
                ON notice_recruitment_positions(notice_id, position_order);
                CREATE INDEX IF NOT EXISTS idx_additional_information_notice
                ON notice_additional_information(notice_id, information_order);
                CREATE INDEX IF NOT EXISTS idx_embedding_chunks_model
                ON notice_embedding_chunks(provider, model, notice_id);
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
                event_status = (
                    "confirmed"
                    if event.start_date and (
                        not event.end_date or event.end_date >= event.start_date
                    )
                    else "needs_review"
                )
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
                        f"{event.start_date}T00:00:00+09:00" if event.start_date else None,
                        f"{event.end_date}T23:59:59+09:00" if event.end_date else None,
                        1,
                        event.location,
                        event.evidence_text,
                        event_status,
                        extraction.confidence,
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
            for information_order, information in enumerate(
                extraction.additional_information
            ):
                connection.execute(
                    """
                    INSERT INTO notice_additional_information (
                        notice_id, information_order, category, title, items_json,
                        evidence_text, confidence, needs_review
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        information_order,
                        information.category,
                        information.title,
                        json.dumps(information.items, ensure_ascii=False),
                        information.evidence_text,
                        information.confidence,
                        int(information.needs_review),
                    ),
                )
            return notice_id, True

    def save_embedding_chunks(
        self,
        *,
        notice_id: int,
        provider: str,
        model: str,
        chunks: list,
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("청크와 임베딩 벡터 개수가 일치해야 합니다.")
        now = datetime.now(SEOUL).isoformat()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM notice_embedding_chunks WHERE notice_id = ? AND provider = ? AND model = ?",
                (notice_id, provider, model),
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                connection.execute(
                    """
                    INSERT INTO notice_embedding_chunks (
                        notice_id, chunk_type, chunk_index, content, content_hash,
                        provider, model, dimensions, vector, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        chunk.chunk_type,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.content_hash,
                        provider,
                        model,
                        len(vector),
                        array("f", vector).tobytes(),
                        now,
                    ),
                )

    def list_embedding_chunks(self, *, provider: str, model: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT notice_id, chunk_type, chunk_index, content, dimensions, vector
                FROM notice_embedding_chunks
                WHERE provider = ? AND model = ?
                ORDER BY notice_id, chunk_type, chunk_index
                """,
                (provider, model),
            ).fetchall()
        result = []
        for row in rows:
            vector = array("f")
            vector.frombytes(row["vector"])
            if len(vector) != row["dimensions"]:
                continue
            result.append({**dict(row), "vector": list(vector)})
        return result

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
            additional_information = connection.execute(
                """
                SELECT category, title, items_json, evidence_text, confidence,
                       needs_review
                FROM notice_additional_information
                WHERE notice_id = ?
                ORDER BY information_order, id
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
        result["additional_information"] = [
            {
                "category": row["category"],
                "title": row["title"],
                "items": json.loads(row["items_json"]),
                "evidence_text": row["evidence_text"],
                "confidence": row["confidence"],
                "needs_review": bool(row["needs_review"]),
            }
            for row in additional_information
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

    def list_calendar_events(self, month_start: str, next_month_start: str) -> dict:
        """시작·종료일이 해당 월에 있는 일정과 날짜 미확정 일정을 조회한다."""
        effective_at = (
            "CASE WHEN e.event_type IN ('application_deadline', 'submission_deadline') "
            "AND e.end_at IS NOT NULL THEN e.end_at ELSE e.start_at END"
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.id, e.notice_id, n.title AS notice_title,
                       n.action_required_json,
                       n.status AS notice_status, e.event_type, e.date_text,
                       e.start_at, e.end_at, e.all_day, e.location,
                       e.evidence_text, e.status, {effective_at} AS effective_at
                FROM notice_events AS e
                JOIN notices AS n ON n.id = e.notice_id
                WHERE {effective_at} IS NULL
                   OR (substr(e.start_at, 1, 10) >= ?
                       AND substr(e.start_at, 1, 10) < ?)
                   OR (substr(COALESCE(e.end_at, e.start_at), 1, 10) >= ?
                       AND substr(COALESCE(e.end_at, e.start_at), 1, 10) < ?)
                ORDER BY effective_at IS NULL, effective_at, e.id
                """,
                (
                    month_start, next_month_start,
                    month_start, next_month_start,
                ),
            ).fetchall()
        events = [
            {
                **{key: row[key] for key in row.keys() if key != "action_required_json"},
                "action_required": json.loads(row["action_required_json"]),
                "all_day": bool(row["all_day"]),
            }
            for row in rows
        ]
        return {
            "items": [row for row in events if row["effective_at"] is not None],
            "undated": [row for row in events if row["effective_at"] is None],
        }

    def search_notices(
        self,
        *,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str = "all",
        status_scope: str = "notice",
        event_types: list[str] | None = None,
    ) -> list[dict]:
        """날짜·상태·일정 유형을 파라미터 바인딩 SQL로 조회한다."""
        event_types = event_types or []
        effective_at = (
            "CASE WHEN e.event_type IN "
            "('application_deadline', 'submission_deadline') "
            "AND e.end_at IS NOT NULL THEN e.end_at ELSE e.start_at END"
        )
        conditions: list[str] = []
        parameters: list[object] = []
        event_filter_used = bool(start_at or end_at or event_types)

        if status != "all":
            if status_scope == "event":
                conditions.append("e.status = ?")
                event_filter_used = True
            else:
                conditions.append("n.status = ?")
            parameters.append(status)
        if start_at is not None:
            conditions.append(f"{effective_at} >= ?")
            parameters.append(start_at)
        if end_at is not None:
            conditions.append(f"{effective_at} < ?")
            parameters.append(end_at)
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            conditions.append(f"e.event_type IN ({placeholders})")
            parameters.extend(event_types)
        if event_filter_used:
            conditions.append("e.id IS NOT NULL")

        where_clause = (
            "WHERE " + " AND ".join(conditions) if conditions else ""
        )
        query = f"""
            SELECT
                n.id AS notice_id,
                n.title,
                n.status AS notice_status,
                n.target_json,
                n.action_required_json,
                n.application_method,
                n.created_at,
                e.id AS event_id,
                e.event_type,
                e.date_text,
                e.start_at,
                e.end_at,
                e.all_day,
                e.location,
                e.evidence_text,
                e.status AS event_status,
                {effective_at} AS effective_at
            FROM notices AS n
            LEFT JOIN notice_events AS e ON e.notice_id = n.id
            {where_clause}
            ORDER BY effective_at IS NULL, effective_at, n.created_at DESC, n.id DESC
        """
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        notices: dict[int, dict] = {}
        for row in rows:
            notice_id = int(row["notice_id"])
            notice = notices.setdefault(
                notice_id,
                {
                    "id": notice_id,
                    "title": row["title"],
                    "status": row["notice_status"],
                    "target": json.loads(row["target_json"]),
                    "action_required": json.loads(row["action_required_json"]),
                    "application_method": row["application_method"],
                    "created_at": row["created_at"],
                    "events": [],
                },
            )
            if row["event_id"] is not None:
                notice["events"].append(
                    {
                        "id": int(row["event_id"]),
                        "event_type": row["event_type"],
                        "date_text": row["date_text"],
                        "start_at": row["start_at"],
                        "end_at": row["end_at"],
                        "effective_at": row["effective_at"],
                        "all_day": bool(row["all_day"]),
                        "location": row["location"],
                        "evidence_text": row["evidence_text"],
                        "status": row["event_status"],
                    }
                )
        return list(notices.values())


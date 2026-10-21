"""SQLite에 저장된 SK 채용 공고 10장을 통합 정답 파일과 비교한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.schemas import NoticeExtraction
from notice.repository import NoticeRepository


SAMPLES = ROOT / "data" / "samples"
GROUND_TRUTH = SAMPLES / "sk_jobs_ground_truth.json"
RESULTS = ROOT / "eval" / "results"
DATABASE = ROOT / "data" / "notices.db"
TEXT_MATCH_THRESHOLD = 0.80


def normalize_text(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (value or "").casefold())


def text_similarity(expected: str, actual: str) -> float:
    left, right = normalize_text(expected), normalize_text(actual)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def flatten_items(groups: list[dict[str, Any]]) -> list[str]:
    return [item for group in groups for item in group.get("items", [])]


def match_items(
    expected_items: list[str], actual_items: list[str], *, threshold: float
) -> dict[str, Any]:
    matches = []
    for expected in expected_items:
        candidates = [(text_similarity(expected, actual), actual) for actual in actual_items]
        score, actual = max(candidates, default=(0.0, ""), key=lambda item: item[0])
        matches.append(
            {
                "expected": expected,
                "matched": score >= threshold,
                "score": round(score, 4),
                "actual": actual or None,
            }
        )
    hit_count = sum(item["matched"] for item in matches)
    return {
        "expected_count": len(expected_items),
        "matched_count": hit_count,
        "recall": hit_count / len(expected_items) if expected_items else 1.0,
        "matches": matches,
    }


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Asia/Seoul"))
        return parsed.date().isoformat()
    except ValueError:
        return None


def evaluate_posting(
    expected: dict[str, Any],
    extraction: NoticeExtraction,
    *,
    notice_id: int,
    status: str,
    created_at: str,
) -> dict[str, Any]:
    expected_title = expected.get("title")
    title_ok = (
        not extraction.title.strip()
        if expected_title is None
        else normalize_text(extraction.title) == normalize_text(expected_title)
    )
    deadline = next(
        (event for event in extraction.events if event.event_type == "application_deadline"),
        None,
    )
    period = expected["application_period"]
    event_type_ok = deadline is not None
    start_date_ok = bool(deadline and deadline.start_date == period["start_date"])
    end_date_ok = bool(deadline and deadline.end_date == period["end_date"])

    actual_responsibilities = [
        item
        for position in extraction.recruitment_positions
        for item in position.responsibilities
    ]
    actual_preferred = [
        item
        for position in extraction.recruitment_positions
        for item in position.preferred_qualifications
    ]
    cleaned_lines = [line.strip() for line in extraction.cleaned_text.splitlines() if line.strip()]
    responsibilities = match_items(
        flatten_items(expected.get("responsibilities", [])),
        actual_responsibilities,
        threshold=TEXT_MATCH_THRESHOLD,
    )
    preferred = match_items(
        flatten_items(expected.get("preferred", [])),
        actual_preferred,
        threshold=TEXT_MATCH_THRESHOLD,
    )
    qualifications = match_items(
        flatten_items(expected.get("qualifications", [])),
        cleaned_lines,
        threshold=TEXT_MATCH_THRESHOLD,
    )
    expected_status = "needs_review" if expected_title is None else "confirmed"
    return {
        "file": expected["file"],
        "notice_id": notice_id,
        "created_at": created_at,
        "title_ok": title_ok,
        "event_type_ok": event_type_ok,
        "start_date_ok": start_date_ok,
        "end_date_ok": end_date_ok,
        "status_ok": status == expected_status,
        "expected_status": expected_status,
        "saved_status": status,
        "responsibilities": responsibilities,
        "qualifications": qualifications,
        "preferred": preferred,
        "extraction": extraction.model_dump(mode="json"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row.get("extraction") is not None]
    total = len(rows)

    def accuracy(key: str) -> float:
        return sum(bool(row.get(key)) for row in rows) / total if total else 0.0

    def micro_recall(section: str) -> float:
        expected = sum(row.get(section, {}).get("expected_count", 0) for row in rows)
        matched = sum(row.get(section, {}).get("matched_count", 0) for row in rows)
        return matched / expected if expected else 1.0

    return {
        "source": "saved_sqlite_notices",
        "text_match_threshold": TEXT_MATCH_THRESHOLD,
        "sample_count": total,
        "failure_count": total - len(successful),
        "title_accuracy": accuracy("title_ok"),
        "event_type_accuracy": accuracy("event_type_ok"),
        "start_date_accuracy": accuracy("start_date_ok"),
        "end_date_accuracy": accuracy("end_date_ok"),
        "status_accuracy": accuracy("status_ok"),
        "responsibility_recall": micro_recall("responsibilities"),
        "qualification_recall": micro_recall("qualifications"),
        "preferred_recall": micro_recall("preferred"),
        "rows": rows,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_extraction(notice: dict[str, Any]) -> NoticeExtraction:
    return NoticeExtraction.model_validate(
        {
            "title": notice["title"],
            "raw_text": notice["raw_text"],
            "cleaned_text": notice["cleaned_text"],
            "target": notice["target"],
            "action_required": notice["action_required"],
            "application_method": notice["application_method"],
            "events": [
                {
                    "event_type": event["event_type"],
                    "date_text": event["date_text"],
                    "start_date": _iso_date(event["start_at"]),
                    "end_date": _iso_date(event["end_at"]),
                    "location": event["location"],
                    "evidence_text": event["evidence_text"],
                }
                for event in notice["events"]
            ],
            "recruitment_positions": notice["recruitment_positions"],
            "additional_information": notice["additional_information"],
            "confidence": notice["confidence"],
        }
    )


def load_saved_notices(database_path: Path) -> dict[str, dict[str, Any]]:
    repository = NoticeRepository(database_path)
    by_hash: dict[str, dict[str, Any]] = {}
    for summary in repository.list_notices():
        notice = repository.get_notice(int(summary["id"]))
        if notice is not None:
            by_hash.setdefault(notice["source_image_hash"], notice)
    return by_hash


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="저장된 sk_job_11~20 추출 결과를 정답과 비교합니다."
    )
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH)
    parser.add_argument(
        "--output", type=Path, default=RESULTS / "day3_sk_jobs.json"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database.exists():
        raise FileNotFoundError(f"저장 DB를 찾을 수 없습니다: {args.database}")
    ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    postings = ground_truth.get("postings", [])
    if len(postings) != 10:
        raise RuntimeError(f"정답 공고는 10건이어야 합니다. 현재 {len(postings)}건입니다.")

    notices_by_hash = load_saved_notices(args.database)
    rows = []
    for expected in postings:
        image_path = SAMPLES / expected["file"]
        if not image_path.exists():
            raise FileNotFoundError(f"평가 이미지를 찾을 수 없습니다: {image_path}")
        notice = notices_by_hash.get(_sha256(image_path))
        if notice is None:
            rows.append(
                {
                    "file": expected["file"],
                    "error": "원본 이미지 해시가 일치하는 저장 공지를 찾지 못했습니다.",
                    "extraction": None,
                }
            )
            print(f"{expected['file']}: MISSING")
            continue
        extraction = _as_extraction(notice)
        row = evaluate_posting(
            expected,
            extraction,
            notice_id=int(notice["id"]),
            status=notice["status"],
            created_at=notice["created_at"],
        )
        rows.append(row)
        print(
            f"{expected['file']}: title={row['title_ok']} "
            f"period={row['start_date_ok'] and row['end_date_ok']} "
            f"type={row['event_type_ok']} status={row['status_ok']} "
            f"notice_id={row['notice_id']}"
        )

    summary = summarize(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "rows"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()

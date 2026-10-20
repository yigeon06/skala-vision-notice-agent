"""평가 정답을 알고 있는 한국어 사내 공지 이미지 5장을 생성한다."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "samples"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

SAMPLES = [
    {
        "name": "notice_01_security_training",
        "title": "2026년 정보보안 필수교육 안내",
        "lines": [
            "대상: 전 임직원",
            "신청 마감: 2026년 10월 23일까지",
            "교육 일시: 2026년 10월 28일 오후 2시",
            "장소: 본관 3층 교육장",
            "신청 방법: 사내 교육 포털에서 신청",
            "교육 미이수자는 보안 담당자에게 별도 안내됩니다.",
        ],
        "expected": {
            "event_types": ["application_deadline", "event"],
            "date_fragments": ["10월 23일", "10월 28일"],
            "expected_status": "confirmed",
        },
    },
    {
        "name": "notice_02_townhall",
        "title": "11월 전사 타운홀 미팅",
        "lines": [
            "대상: 전 임직원",
            "행사 일시: 2026년 11월 5일 오후 3시",
            "장소: 대강당 및 온라인 생중계",
            "해야 할 일: 참석이 어려운 경우 부서장에게 사전 공유",
            "별도의 신청 절차는 없습니다.",
        ],
        "expected": {
            "event_types": ["event"],
            "date_fragments": ["11월 5일"],
            "expected_status": "confirmed",
        },
    },
    {
        "name": "notice_03_expense_deadline",
        "title": "10월 법인카드 정산 마감 안내",
        "lines": [
            "대상: 법인카드 사용자",
            "제출 마감: 2026년 10월 31일 오후 6시",
            "제출 방법: ERP 경비처리 메뉴에서 영수증 첨부",
            "마감 이후 제출 건은 다음 달 비용으로 처리됩니다.",
        ],
        "expected": {
            "event_types": ["submission_deadline"],
            "date_fragments": ["10월 31일"],
            "expected_status": "confirmed",
        },
    },
    {
        "name": "notice_04_health_check",
        "title": "임직원 건강검진 예약 안내",
        "lines": [
            "대상: 2026년 건강검진 대상자",
            "예약 마감: 2026년 11월 7일까지",
            "검진 일시: 2026년 11월 10일 오전 9시",
            "장소: 새봄 건강검진센터",
            "신청 방법: 복지 포털에서 검진 시간을 선택하세요.",
        ],
        "expected": {
            "event_types": ["application_deadline", "event"],
            "date_fragments": ["11월 7일", "11월 10일"],
            "expected_status": "confirmed",
        },
    },
    {
        "name": "notice_05_ambiguous_workshop",
        "title": "개발본부 팀워크 워크숍 사전 안내",
        "lines": [
            "대상: 개발본부 구성원",
            "일정: 11월 중 진행 예정",
            "장소와 정확한 시간은 추후 공지합니다.",
            "참석이 어려운 구성원은 팀장에게 알려주세요.",
        ],
        "expected": {
            "event_types": ["event"],
            "date_fragments": ["11월 중"],
            "expected_status": "needs_review",
        },
    },
]


def _font(size: int):
    return ImageFont.truetype(str(FONT_PATH), size=size)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for index, sample in enumerate(SAMPLES, 1):
        image = Image.new("RGB", (1200, 1500), "#f7f9fc")
        draw = ImageDraw.Draw(image)
        accent = ["#1d4ed8", "#0f766e", "#7c3aed", "#b45309", "#be123c"][index - 1]
        draw.rectangle((0, 0, 1200, 180), fill=accent)
        draw.text((75, 60), "사내 공지", font=_font(48), fill="white")
        draw.rounded_rectangle((55, 240, 1145, 1370), radius=24, fill="white", outline="#d7deea", width=3)
        y = 310
        for line in textwrap.wrap(sample["title"], width=24):
            draw.text((105, y), line, font=_font(54), fill="#111827")
            y += 76
        draw.line((105, y + 15, 1095, y + 15), fill=accent, width=5)
        y += 75
        for original in sample["lines"]:
            wrapped = textwrap.wrap(original, width=36) or [original]
            for line_index, line in enumerate(wrapped):
                prefix = "• " if line_index == 0 else "  "
                draw.text((115, y), prefix + line, font=_font(38), fill="#273449")
                y += 58
            y += 28
        image_path = OUTPUT / f"{sample['name']}.png"
        image.save(image_path)
        expected = {
            "title": sample["title"],
            **sample["expected"],
        }
        (OUTPUT / f"{sample['name']}.expected.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(image_path)


if __name__ == "__main__":
    main()


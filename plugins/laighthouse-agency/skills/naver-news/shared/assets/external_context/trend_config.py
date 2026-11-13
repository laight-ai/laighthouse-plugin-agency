"""외부 요인 skill 공통 설정 — 한국 시각. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def now_kst_text() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")

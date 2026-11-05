"""외부 요인 skill 공통 설정 — 한국 시각. 표준 라이브러리만 쓴다.

PoC(external-context-poc ``skills/external-trend/assets/trend_config.py``)의 테넌트 찾기·DB 접속은
플러그인에서 저장 훅 응답 리더(:mod:`responses`)가 대신한다.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def now_kst_text() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")

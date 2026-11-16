"""외부 요인 skill 공통 코어 — 날짜 범위 창, 기간 통계, 급증 판정.

어느 소스인지 모른다. 일별 값은 `dict[date, int | None]`이고 None은 쓸 수 없는
날(수집 범위 밖·집계 불완전·데이터 없음)이다.

- 기간의 쓸 수 있는 날이 절반 미만이면 합계·평균을 비운다(`days > 0`인데 `total`이 없는 경우).
- 급증 기준선은 주말 다음 월요일이 매번 급증으로 잡히지 않도록 직전 7일 중 같은 요일 유형(평일·주말)인
  날의 평균이다(``same_daytype_avg``). 범위 안 모든 날에 판정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional

DOW = "월화수목금토일"
MIN_BASE_DAYS = 4
SPIKE_BASE = "직전 7일 중 같은 요일 유형(평일·주말) 평균"

Values = Dict[date, Optional[int]]


def md(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.month}/{d.day}({DOW[d.weekday()]})"


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or float(b) == 0:
        return None
    return round(100.0 * (float(a) - float(b)) / float(b), 1)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass
class Window:
    """보고 범위(시작~끝). 직전 7일 기준선을 위해 시작 − 7일부터 읽는다."""

    current: list[date]

    @property
    def load_start(self) -> date:
        return self.current[0] - timedelta(days=7)

    def to_json(self) -> dict:
        cur = self.current
        return {
            "current": {
                "start": cur[0].isoformat(),
                "end": cur[-1].isoformat(),
                "days": len(cur),
                "label": f"{md(cur[0])}~{md(cur[-1])}",
            },
            "spike_from": cur[0].isoformat(),
            "spike_to": cur[-1].isoformat(),
        }


def build_window(target: date, start: date | None) -> Window:
    """skill의 날짜 범위 입력(시작~끝). 끝 7일 vs 앞 7일 비교는 skill의 facts가 일별 값으로 한다."""
    if start is None or start > target:
        raise ValueError(f"범위 시작이 없거나 끝({target})보다 늦습니다: {start}")
    return Window(days_between(start, target))


def period_stats(values: Values, days: list[date], incomplete: set[date] = frozenset()) -> dict:
    """합·일수·평균·피크. 쓸 수 있는 날이 없으면 total=None·days=0.

    incomplete는 범위 안이지만 집계가 불완전해 뺀 날(값은 None)로, `incomplete_days`에 남긴다.
    """
    usable = [(d, values[d]) for d in days if values.get(d) is not None]
    partial = [d.isoformat() for d in days if d in incomplete]
    if not usable:
        return {"total": None, "days": 0, "avg": None, "peak": None, "incomplete_days": partial}
    total = sum(v for _, v in usable)
    peak_d, peak_v = max(usable, key=lambda x: (x[1], x[0]))
    enough = 2 * len(usable) >= len(days)
    return {
        "total": total if enough else None,
        "days": len(usable),
        "avg": round(total / len(usable), 1) if enough else None,
        "peak": {"date": peak_d.isoformat(), "count": peak_v},
        "incomplete_days": partial,
    }


def trailing_avg(values: Values, d: date) -> float | None:
    """직전 7일 중 쓸 수 있는 날의 평균. 그런 날이 MIN_BASE_DAYS일 미만이면 None."""
    vals = [
        values[x]
        for x in days_between(d - timedelta(days=7), d - timedelta(days=1))
        if values.get(x) is not None
    ]
    return round(sum(vals) / len(vals), 1) if len(vals) >= MIN_BASE_DAYS else None


def ratio_x(value: int | None, base: float | None) -> float | None:
    if value is None or not base:
        return None
    return round(value / base, 2)


def is_weekend(d: date) -> bool:
    # shortcut: 공휴일은 평일로 본다. 공휴일 급증 오판이 문제 되면 공휴일 표를 넣는다.
    return d.weekday() >= 5


def same_daytype_avg(values: Values, d: date) -> float | None:
    """직전 7일 중 d와 같은 요일 유형(평일·주말)이고 쓸 수 있는 날의 평균. 평일은 3일, 주말은 2일 미만이면 None."""
    vals = [
        values[x]
        for x in days_between(d - timedelta(days=7), d - timedelta(days=1))
        if is_weekend(x) == is_weekend(d) and values.get(x) is not None
    ]
    return round(sum(vals) / len(vals), 1) if len(vals) >= (2 if is_weekend(d) else 3) else None


def is_spike(
    values: Values, d: date, ratio: float, minimum: int, same_daytype: bool = False
) -> tuple[bool, float | None]:
    """기준선(직전 7일 평균, same_daytype면 같은 요일 유형 평균)의 ratio배 이상이고 minimum건 이상인가와 그 기준선."""
    v = values.get(d)
    base = same_daytype_avg(values, d) if same_daytype else trailing_avg(values, d)
    if v is None or base is None:
        return False, base
    return (v >= minimum and v >= ratio * base), base

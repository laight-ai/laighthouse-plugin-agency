#!/usr/bin/env python3
"""요약 숫자 대조(check_citations) 자체 검사(표준 라이브러리만). 성공하면 "ok".

facts는 검사용 고정값이다(보고서에 쓰는 수치가 아니다).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "plugins", "laighthouse-agency", "shared", "assets")
sys.path[:0] = [os.path.normpath(os.path.join(KIT, "external_context")), os.path.normpath(KIT)]

import check_citations as cc  # noqa: E402


def unmatched(summary: str, facts: dict) -> list:
    return cc.missing_numbers(cc.cited_numbers(summary), cc.allowed_values([facts]))


def test_small_count_not_in_facts_is_caught():
    facts = {"spikes": [{"count": 15}]}
    assert unmatched("급증일 15건", facts) == []
    assert unmatched("급증일 12건", facts) == ["12"]


def test_sign_must_match_when_written():
    facts = {"last7_vs_prev7": {"change_pct": -25.0}}
    assert unmatched("끝 7일이 -25.0% 줄었다", facts) == []
    assert unmatched("끝 7일이 25.0% 줄었다", facts) == []  # 부호 없이 쓴 크기는 허용
    assert unmatched("끝 7일이 +25.0% 늘었다", facts) == ["+25.0"]


def test_dates_and_day_rank_units_are_not_checked():
    facts = {"brands": [{"rank": 2, "total": 294}]}
    assert unmatched("11/3(화)·2026-11-03 기준 2위(294건), 14일 동안", facts) == []
    assert unmatched("2위(295건)", facts) == ["295"]


def test_quarters_and_months_are_not_checked():
    facts = {"top_docs": [{"same_topic": 21}]}
    assert unmatched("주제 21건, 3분기 실적, 8월 더위", facts) == []
    # 제목에 없는 이름 속 숫자는 대조한다(H3: 이름 예외가 '9999 수준' 같은 틀린 숫자를 숨겼다)
    assert unmatched("컬처프로젝트 31 웨인 티보 전", facts) == ["31"]
    assert unmatched("관람 글 12 건", facts) == ["12"]


def test_plain_numbers_before_words_are_checked():
    facts = {"brands": [{"total": 100}], "brand_count": 5}
    assert unmatched("하루 평균 9999 수준", facts) == ["9999"]
    assert unmatched("현대카드 2,222 증가", facts) == ["2222"]
    assert unmatched("기사 12개", facts) == ["12"]
    assert unmatched("5개 브랜드", facts) == []


def test_numbers_in_fact_titles_are_allowed():
    facts = {"top_docs": [{"title": "컬처프로젝트 31 웨인 티보 전 관람", "same_topic": 21}]}
    assert unmatched("컬처프로젝트 31 웨인 티보 전(21건)", facts) == []


def test_differences_of_same_metric_are_allowed():
    facts = {
        "last7_vs_prev7": {"brands": {"A": {"last7": 397, "prev7": 542, "change_pct": -26.8}}},
        "spikes": [{"count": 42, "last_week": 10}],
        "brands": [{"name": "A", "total": 57, "weekday_avg": 86.1, "weekend_avg": 19.5},
                   {"name": "B", "total": 125}],
    }
    assert unmatched("끝 7일 397건으로 앞 7일 542건보다 145건 줄었다", facts) == []
    assert unmatched("42건으로 지난주 같은 요일 10건보다 32건 많았다", facts) == []
    assert unmatched("평일 86.1건, 주말 19.5건 — 차이 66.6건", facts) == []
    assert unmatched("1위 B(125건)와 68건 차이", facts) == []
    assert unmatched("397건과 10건의 차이 387건", facts) == ["387"]  # 다른 지표끼리의 차는 허용하지 않는다


def test_ratio_rounded_half_up_is_allowed():
    facts = {"spikes": [{"ratio_x": 2.15}, {"ratio_x": 1.45}]}
    assert unmatched("평일 평균의 2.2배, 1.5배", facts) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

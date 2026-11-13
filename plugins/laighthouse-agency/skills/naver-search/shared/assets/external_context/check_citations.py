"""모델이 쓴 요약 문장의 수치가 facts에 있는지 대조한다.

요약 텍스트에서 숫자를 모두 뽑아, facts의 숫자 값 집합과 간단한 파생값에 있는지 확인한다.

- 허용 값: facts의 정수, 소수 1자리(반올림 1.45 → 1.5 포함), 소수 2자리 값(배수 1.44배)은 2자리 그대로도.
  부호를 쓴 숫자(+12.3%·-25.0%)는 부호까지 같아야 하고, 부호 없이 쓴 숫자는 크기만 맞으면 된다.
- facts 문자열(기사·글 제목, 데이터 상태 문장)에 든 숫자도 허용한다(컬처프로젝트 31 웨인 티보 전).
- 31 이하 정수 뒤에 일·위·주·번·월·분기가 붙으면(14일 동안, 2위, 3분기) 대조하지 않는다. 건수·개·%·배는
  작은 수도 대조한다.
- 차("542건 → 397건, 145건 줄었다")는 같은 지표 짝에서만 허용한다(rules.md "같은 지표 두 값의 차"):
  같은 객체의 `last7`·`prev7`, `count`·`last_week`, `weekday_avg`·`weekend_avg`, 목록 안 객체들의
  `total`(브랜드 범위 합계끼리). 차는 소수 1자리와 반올림 정수로 허용한다.
- 날짜(10/16, 2026-10-20)·시각, 따옴표로 인용한 제목 안의 숫자, 글자에 붙은 숫자(snow116)는 뺀다.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|\d{1,2}:\d{2}|\d{4}년|\d{1,2}월 \d{1,2}일")
_QUOTED = re.compile(r"'[^'\n]*'|‘[^’\n]*’|\"[^\"\n]*\"|“[^”\n]*”")
# 아스키 숫자만(태국 숫자 ๑ 같은 유니코드 숫자 제외)
_NUM = re.compile(r"(?<![0-9A-Za-z가-힣_])[-+]?[0-9][0-9,]*(?:\.[0-9]+)?")
# 이 단위가 붙은 31 이하 정수는 일수·순위·기간이라 대조하지 않는다
_UNIT_EXEMPT = re.compile(r"\s?(일|위|주|번|월|분기)")
UNIT_EXEMPT_MAX = 31
# 차를 허용하는 같은 지표 짝(한 객체 안의 두 키)
METRIC_PAIRS = (("last7", "prev7"), ("count", "last_week"), ("weekday_avg", "weekend_avg"))


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _add_number(v, acc: set) -> None:
    if isinstance(v, int):
        acc.add(str(v))
        return
    acc.add(f"{v:.1f}")
    acc.add(str(Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)))
    if round(v, 2) != round(v, 1):
        acc.add(f"{v:.2f}")
    if v.is_integer():
        acc.add(str(int(v)))


def numbers_in(obj, acc: set) -> None:
    """facts의 숫자를 부호를 살린 문자열로 모은다(-25.0 → "-25.0"). 문자열 안 숫자도 모은다."""
    if _is_num(obj):
        _add_number(obj, acc)
    elif isinstance(obj, str):
        acc.update(m.group().replace(",", "") for m in _NUM.finditer(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            numbers_in(v, acc)


def cited_numbers(text: str) -> list:
    head = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    head = _QUOTED.sub(" ", head)
    head = _DATE.sub(" ", head)
    out = []
    for m in _NUM.finditer(head):
        raw = m.group().replace(",", "")
        if raw.isdigit() and int(raw) <= UNIT_EXEMPT_MAX and _UNIT_EXEMPT.match(head, m.end()):
            continue
        out.append(raw)
    return out


def same_metric_groups(obj) -> list:
    """차를 허용하는 같은 지표 값 묶음(METRIC_PAIRS, 목록 안 객체들의 total)."""
    groups = []
    if isinstance(obj, dict):
        for a, b in METRIC_PAIRS:
            if _is_num(obj.get(a)) and _is_num(obj.get(b)):
                groups.append([obj[a], obj[b]])
        for v in obj.values():
            groups += same_metric_groups(v)
    elif isinstance(obj, list):
        totals = [x["total"] for x in obj if isinstance(x, dict) and _is_num(x.get("total"))]
        if len(totals) > 1:
            groups.append(totals)
        for v in obj:
            groups += same_metric_groups(v)
    return groups


def allowed_values(docs: list) -> set:
    allowed: set = set()
    for data in docs:
        numbers_in(data, allowed)
        for group in same_metric_groups(data):
            for a, b in combinations(set(group), 2):
                diff = abs(a - b)
                allowed.add(str(int(diff)) if float(diff).is_integer() else f"{diff:.1f}")
                allowed.add(str(round(diff)))
    return allowed


def _known(mag: str, allowed: set) -> bool:
    return mag in allowed or (mag.endswith(".0") and mag[:-2] in allowed)


def missing_numbers(cited: list, allowed: set) -> list:
    """``cited``(부호 포함) 중 허용 값에 없는 것. ``+``는 양수, ``-``는 음수와만, 부호 없으면 크기만 맞춘다."""
    out = []
    for n in cited:
        mag = n.lstrip("+-")
        if n.startswith("-"):
            ok = _known(n, allowed)
        elif n.startswith("+"):
            ok = _known(mag, allowed)
        else:
            ok = _known(mag, allowed) or _known("-" + mag, allowed)
        if not ok:
            out.append(n)
    return out

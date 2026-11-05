#!/usr/bin/env python3
"""외부 요인 skill 4개 회귀 비교 — 저장 훅 응답 → ``prepare``가 쓰는 report.json 전체를 기준과 대조.

    # 기준 만들기(동작을 바꾸지 않는 정리를 하기 전에 한 번)
    python3 tests/regress_external_context.py --responses <응답 폴더> --baseline <기준 폴더> --write
    # 대조(차이가 없으면 종료 코드 0)
    python3 tests/regress_external_context.py --responses <응답 폴더> --baseline <기준 폴더>

응답 폴더는 저장 훅이 남긴 ``<세션>/<시각>_get_external_context.json``(로컬 스택으로 skill을 돌린 뒤
임시 폴더 ``laighthouse_mcp_responses``를 복사한 것)이다. 범위마다 skill 4개(naver-search·naver-news·
naver-blog·weather-impact)의 ``prepare``를 돌려 report.json을 ``<skill>_<시작>_<끝>.json``과 비교한다.
기본 범위는 차트 모양이 바뀌는 길이(1·3·4·14·92일, 끝 2026-11-03)다. 실행 시각(``generated_at``)은 뺀다.
``today_kst``는 ``--today``(기본 2026-11-05, 기준을 만든 날)로 고정한다 — 데이터 상태 문장이 오늘 날짜에
따라 바뀌기 때문이다. 기준은 그 시점 코드의 결과이므로, 의도한 동작 변경 뒤에는 차이를 검토한 다음에만 ``--write``로 다시 쓴다.
``--weather-csv``를 주면 날씨 응답의 일별 값(최고·최저기온, 강수량, 시간자료 수, 불쾌지수 평균·최대)을
DB에서 직접 뽑은 CSV와도 비교한다. 표준 라이브러리만 쓴다(macOS 기본 python3 3.9 포함).
"""

import argparse
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "plugins", "laighthouse-agency", "shared", "assets")
sys.path[:0] = [os.path.normpath(os.path.join(KIT, "external_context")), os.path.normpath(KIT)]

import range_report  # noqa: E402
import responses  # noqa: E402
import trend_config  # noqa: E402
import weather_trend  # noqa: E402

SKILLS = ("naver-search", "naver-news", "naver-blog", "weather-impact")
RANGES = (
    "2026-11-03~2026-11-03",
    "2026-11-01~2026-11-03",
    "2026-10-31~2026-11-03",
    "2026-10-21~2026-11-03",
    "2026-08-04~2026-11-03",
)


def strip_time(obj):
    if isinstance(obj, dict):
        return {k: strip_time(v) for k, v in obj.items() if k != "generated_at"}
    if isinstance(obj, list):
        return [strip_time(v) for v in obj]
    return obj


def report(skill: str, brand: str, rng: str, root: str) -> dict:
    if skill == "weather-impact":
        out = weather_trend.prepare(brand, rng, root)
    else:
        out = range_report.prepare(skill, brand, rng, root)
    if "json" not in out:
        raise SystemExit(f"{skill} {rng}: prepare 실패 {out}")
    with open(out["json"], encoding="utf-8") as f:
        return strip_time(json.load(f))


def diff(got, want, path: str = "") -> list:
    """값이 다른 곳의 경로 목록."""
    if isinstance(got, dict) and isinstance(want, dict):
        out = []
        for k in sorted(set(got) | set(want), key=str):
            if k not in got or k not in want:
                out.append(f"{path}.{k}: {'없음' if k not in got else '있음'} vs 기준 {'없음' if k not in want else '있음'}")
            else:
                out += diff(got[k], want[k], f"{path}.{k}")
        return out
    if isinstance(got, list) and isinstance(want, list) and len(got) == len(want):
        out = []
        for i, (g, w) in enumerate(zip(got, want)):
            out += diff(g, w, f"{path}[{i}]")
        return out
    return [] if got == want else [f"{path}: {str(got)[:80]} vs 기준 {str(want)[:80]}"]


def weather_diff(root: str, brand: str, csv_path: str) -> tuple:
    """CSV(날짜,최고,최저,강수,시간 수,DI 평균,DI 최대) vs 응답 rows(소수 1자리). 응답이 덮는 날만.
    유형은 반올림 전 값으로 판정하므로(예: DI 최대 74.97 → 보통, CSV 75.0) CSV로는 비교하지 않는다."""
    got = {}
    for rec in responses.records(root):
        ti = rec.get("tool_input") or {}
        if ti.get("brand_name") == brand and ti.get("kind") == "weather":
            for r in json.loads(rec["response"])["rows"]:
                got[r["tm"]] = r
    keys = ("max_ta", "min_ta", "sum_rn", "hours", "di_avg", "di_max")
    problems, n = [], 0
    with open(csv_path, encoding="utf-8") as f:
        for line in f:
            d, *vals = line.strip().split(",")
            if d not in got:
                continue
            n += 1
            want = [None if v == "" else float(v) for v in vals]
            have = [weather_trend.r1(got[d][k]) for k in keys]
            if have != want:
                problems.append(f"{d}: {have} vs 기준 {want}")
    return n, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--responses", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--write", action="store_true", help="대조 대신 기준을 새로 쓴다")
    ap.add_argument("--brand", default="현대카드")
    ap.add_argument("--range", action="append", dest="ranges", help="YYYY-MM-DD~YYYY-MM-DD(여러 번 줄 수 있음)")
    ap.add_argument("--weather-csv", help="날씨 기준 CSV")
    ap.add_argument("--today", default="2026-11-05", help="today_kst로 쓸 날짜(기준을 만든 날)")
    args = ap.parse_args()
    today = date.fromisoformat(args.today)
    trend_config.today_kst = lambda: today

    os.makedirs(args.baseline, exist_ok=True)
    failed = 0
    for rng in args.ranges or RANGES:
        for skill in SKILLS:
            got = report(skill, args.brand, rng, args.responses)
            path = os.path.join(args.baseline, f"{skill}_{rng.replace('~', '_')}.json")
            if args.write:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(got, f, ensure_ascii=False, indent=1, sort_keys=True)
                print(f"기준 저장: {path}")
                continue
            with open(path, encoding="utf-8") as f:
                problems = diff(got, json.load(f))
            print(f"{skill} {rng}: 차이 {len(problems)}")
            for p in problems[:20]:
                print("  - " + p)
            failed += bool(problems)
    if args.weather_csv:
        n, problems = weather_diff(args.responses, args.brand, args.weather_csv)
        print(f"weather: {n}일 — 차이 {len(problems)}")
        for p in problems[:20]:
            print("  - " + p)
        failed += bool(problems) or n == 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

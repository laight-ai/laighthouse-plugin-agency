#!/usr/bin/env python3
"""daily 최종 보고서 조립기 — 미리 검증된 asset 스크립트.

MCP 응답 봉투 원문을 섹션별로 그대로 받아, 공용 킷(`shared/assets/report_kit.*`)으로 뷰 모델을 계산하고
`assets/report-template.html`에 주입해 **최종 HTML 한 파일을 한 번의 호출로** 만든다. 모델은 HTML도,
집계도 하지 않는다 — 봉투 원문과 요약 불릿만 넘긴다.

사용법:
  python3 assets/build_report.py <입력.json>      (또는 stdin으로 JSON)
  {"base": <assets/prepare.py가 만든 build.json 경로>, "dims": ..., "s2": ...} 형태도 받는다(base 내용에 나머지 키를 덮어쓴다).

입력 (JSON):
{
  "out": "~/Downloads/laighthouse-reports/{브랜드}_daily_2026-09-20.html",   # 필수
  "title": "{브랜드} Daily 보고서",                                          # 필수
  "target_date": "2026-09-20",                                              # 필수 (D0)
  "skeleton": true,             # 선택 — 전 섹션 "데이터 준비 중"
  "metric_keys": {...},         # discover.py 출력 그대로 (cost/impression/click/ctr/views/cpm/cpv)
  "currency": "₩",              # discover.py 출력 그대로
  "dims": "<차원 확인(group_by [\"__list_dimensions__\"]) 에러 메시지 원문>",   # 필수(표가 있을 때) — 빠진 차원이 있으면 멈춘다
  "s1": {"json": "<get_ad_performance day, group_by 없음, D-7~D0 응답 원문>"},
  "s2": {"bullets": [{"head": "Meta Reach", "text": "CPV가 ... <strong>+22.2%</strong> ...", "tone": "red|green|yellow|neutral"}]},
  "s3": {"json": "<day, group_by [\"media\"], D-7~D0 응답 원문>"},   # 차트는 최근 7일, D-7은 전주 동요일 표 대조 검증용
  "s4": {"json_files": ["<day, group_by = FINE_DIMS, D-7~D0 응답>"]}
        # 피벗 표: 하루 단위로 D-7~D0을 1회 받아 기준일·전일·전주 동요일 행만 쓴다(하루치 값 = 그날 total 값)
        # (기준일·전일·전주 동요일을 total grain으로 1회씩 받은 {"d0": ..., "d1": ..., "d7": ...}도 받는다)
}
- 키가 없거나 null인 섹션은 "데이터 준비 중"으로 렌더링된다(섹션 생략 없음).
- 출력(stdout): {"out": 절대경로, "bytes": 크기, "sections": {"s1": "ok"|"placeholder", ...}}
"""
import io
import json
import os
import sys
from datetime import date, timedelta

if __name__ == "__main__":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(ASSETS_DIR, "..", "shared", "assets"),
             os.path.join(ASSETS_DIR, "..", "..", "..", "shared", "assets")):
    if os.path.exists(os.path.join(cand, "report_kit.py")):
        sys.path.insert(0, os.path.normpath(cand))
        break
else:
    raise SystemExit("report_kit.py를 찾을 수 없다 (shared/assets)")
import report_kit as kit  # noqa: E402

P = kit.PRODUCT_DIM


def compute(payload, check_dims=True):
    target = date.fromisoformat(payload["target_date"])
    d1, d7 = target - timedelta(days=1), target - timedelta(days=7)
    D0, D1, D7 = target.isoformat(), d1.isoformat(), d7.isoformat()
    skeleton = bool(payload.get("skeleton"))
    keys = payload.get("metric_keys") or {}
    currency = payload.get("currency") or "₩"

    def env(sec):
        if skeleton or not payload.get(sec):
            return None
        return kit.section_envelope(payload[sec])

    e1, e3 = env("s1"), env("s3")
    s4 = None if skeleton else payload.get("s4")
    fine = {}
    if isinstance(s4, dict) and any(k in s4 for k in ("d0", "d1", "d7")):
        fine = {k: e for k in ("d0", "d1", "d7") for e in [kit.section_envelope(s4.get(k))] if e}
    elif s4:
        e4_legacy = kit.section_envelope(s4)
        fine = kit.split_by_period(e4_legacy, {D0: "d0", D1: "d1", D7: "d7"}) if e4_legacy else {}
    e4 = None
    if fine:   # 지표 목록·단위 판정용으로 행을 합친 봉투
        e4 = dict(next(iter(fine.values())), rows=[r for e in fine.values() for r in e["rows"]])
    day_of = {"d0": D0, "d1": D1, "d7": D7}
    if fine and check_dims:
        # 받은 날짜만 검사한다 — 빠진 날짜는 차원 오류가 아니라 그 비교가 비는 것이다(prepare.py의 missing)
        kit.require_dims(payload.get("dims"), [(f"s4 {day_of[k]}", v) for k, v in fine.items()], "s4 피벗 표")
    kit.require_rollup([("전체 ↔ 매체(s1·s3)", kit.check_rollup(e1, [], e3, [], keys))] +
                       [(f"매체 ↔ 표({day_of[k]})", kit.check_rollup(e3, ["media"], kit.with_period(v, "date", day_of[k]), ["media"], keys))
                        for k, v in fine.items()] +
                       [(f"전체 ↔ 표({day_of[k]})", kit.check_rollup(e1, [], kit.with_period(v, "date", day_of[k]), [], keys))
                        for k, v in fine.items()])
    i1 = kit.index_rows(e1, [])
    i3 = kit.index_rows(e3, ["media"])
    metrics, units = kit.metrics_units(e1, e3, e4)
    meta = kit.metric_meta(metrics, units, currency, kit.additive_metrics(i1, i3, metrics, units, keys), keys)
    media = kit.ordered_names(i3) or kit.ordered_names(kit.index_rows(e4, ["media"]))
    colors = kit.media_colors(media)
    sections = {}

    tot = lambda d: (i1.get(d) or {}).get(()) or {}  # noqa: E731
    if e1 and tot(D0):
        # 카드 = 서빙 지표 전부, 처음엔 고정 7 역할만 켠다 — 보는 사람이 지표 메뉴로 더하고 뺀다
        sections["s1"] = kit.kpi_pick(tot(D0), [("yday", "전일", tot(D1)), ("lastweek", "전주 동요일", tot(D7))],
                                      keys, meta, store="daily")

    sections["s2"] = None if skeleton else kit.bullets_of(payload.get("s2"))

    if e3:
        days = [target - timedelta(days=6 - i) for i in range(7)]
        periods = [d.isoformat() for d in days]
        sections["s3"] = {"labels": [kit.day_label(d) for d in days],
                          "weekend": [i for i, d in enumerate(days) if d.weekday() >= 5],
                          "metrics": meta, "default_metric": keys.get("cost"),
                          "series": [{"name": m, "color": colors[m],
                                      "values": kit.series_values(i3, periods, (m,), metrics)} for m in media]}

    if fine:
        totals = {k: tot(day_of[k]) for k in fine} if e1 else None
        compares = {"yday": {"base": "d1", "cur": "d0", "base_label": kit.day_label(d1), "cur_label": kit.day_label(target)},
                    "lastweek": {"base": "d7", "cur": "d0", "base_label": kit.day_label(d7), "cur_label": kit.day_label(target)}}
        sections["s4"] = kit.pick_section(fine, meta, keys, dots=colors,
                                          search_dim="campaign_name", compares=compares, totals=totals)

    for k in ("s1", "s2", "s3", "s4"):
        sections.setdefault(k, None)
    report = {"currency": currency, "sections": sections}
    md = lambda d: f"{d.month}월 {d.day}일"  # noqa: E731
    rep = {
        "__TITLE__": payload["title"],
        "__DATE_LABEL__": kit.kdate(target),
        "__CMP_LABEL__": f"전일 {md(d1)} ({kit.WEEKDAY_KO[d1.weekday()]}) · 전주 동요일 {md(d7)} ({kit.WEEKDAY_KO[d7.weekday()]})",
        "__MEDIA_SUM__": (" + ".join(media) + " 합산, ") if media else "",
        "__TARGET_MD__": md(target),
        "__RANGE_LABEL__": f"{md(target - timedelta(days=6))}~{md(target)}",
        "__CUR_DAY__": kit.day_label(target),
    }
    ctx = {"keys": keys, "currency": currency, "metrics": metrics, "units": units, "fine": fine, "tot": tot,
           "D0": D0, "D1": D1, "D7": D7}
    return sections, rep, report, ctx


def digest(payload):
    """Daily Summary 작성 근거 — 기준일·전일·전주 동요일 값과 변화(전체, 매체, 매체-상품). 화면 표와 같은 규칙의 숫자다."""
    _, _, _, c = compute(payload, check_dims=False)
    keys, metrics, units, fine = c["keys"], c["metrics"], c["units"], c["fine"]
    _, fmt, change = kit.digest_fmt(keys, units, c["currency"])

    def row(name, d0, d1, d7):
        return {"이름": name, "기준일": fmt(d0), "전일": fmt(d1), "전주 동요일": fmt(d7),
                "전일 대비": change(d0, d1), "전주 동요일 대비": change(d0, d7)}

    out = {"기준일": c["D0"], "전일": c["D1"], "전주 동요일": c["D7"]}
    if c["tot"](c["D0"]):
        out["전체"] = row("전체", c["tot"](c["D0"]), c["tot"](c["D1"]), c["tot"](c["D7"]))
    if "d0" in fine:
        dims = fine["d0"].get("dimensions") or []
        for name, ds in (("매체", ["media"]), ("매체-상품", ["media", P])):
            if any(d not in dims for d in ds):
                continue   # 응답에 없는 차원은 건너뛴다
            g = {k: kit.group_values(fine.get(k), ds, metrics, units, keys) for k in ("d0", "d1", "d7")}
            ks = sorted(g["d0"], key=lambda k: -((g["d0"][k].get(keys.get("cost")) or 0)))
            out[name] = [row(" ".join(k), g["d0"][k], g["d1"].get(k) or {}, g["d7"].get(k) or {}) for k in ks[:kit.DIGEST_TOP]]
            if len(ks) > kit.DIGEST_TOP:
                out[name + " 생략"] = f"광고비 상위 {kit.DIGEST_TOP}개만 — 나머지 {len(ks) - kit.DIGEST_TOP}개"
    return out


def main():
    payload = kit.read_payload()
    sections, rep, report, _ = compute(payload)
    path, size = kit.build_html(ASSETS_DIR, rep, report, payload["out"])
    json.dump({"out": path, "bytes": size,
               "sections": {k: ("ok" if v is not None else "placeholder") for k, v in sections.items()}},
              sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""monthly 최종 보고서 조립기 — 미리 검증된 asset 스크립트.

MCP 응답 봉투 원문을 섹션별로 그대로 받아, 공용 킷(`shared/assets/report_kit.*`)으로 뷰 모델을 계산하고
`assets/report-template.html`에 주입해 **최종 HTML 한 파일을 한 번의 호출로** 만든다.

사용법:
  python3 assets/build_report.py <입력.json>      (또는 stdin으로 JSON)
  {"base": <assets/prepare.py가 만든 build.json 경로>, "dims": ..., "s2": ...} 형태도 받는다(base 내용에 나머지 키를 덮어쓴다).

입력 (JSON):
{
  "out": "~/Downloads/laighthouse-reports/{브랜드}_monthly_2026-09.html",   # 필수
  "title": "{브랜드} Monthly 보고서",                                       # 필수
  "month": "2026-09",                                                      # 필수 (대상 월 M0)
  "skeleton": true,             # 선택 — 전 섹션 "데이터 준비 중"
  "metric_keys": {...}, "currency": "₩",          # discover.py 출력 그대로
  "dims": "<차원 확인(group_by [\"__list_dimensions__\"]) 에러 메시지 원문>",   # 필수(표가 있을 때) — 빠진 차원이 있으면 멈춘다
  "s1": {"json": "<month, group_by 없음, M-5 1일~M0 말일 응답 원문>",
         "target_progress": "<get_target_progress_v2(month=M0, media 생략) 응답 원문 그대로>"},
  "s2": {"groups": [{"title": "소진", "lead": "...", "media": [{"name", "desc", "bullets": [{"label", "text", "tone"}]}]}, ...]},
        # weekly와 같은 [소진]·[효율] 그룹. 예전 {"bullets": [{"head", "text", "tone"}]}도 받는다
  "s4": {"json": "<month, group_by [\"media\"], M-5~M0 응답 원문>"},
  "s6": {"json": "<month, group_by = 제공 차원 전부(date·source 제외), M-1~M0 응답 원문>",   # 목표 달성 표(예전 ["media","상품"]도 받는다)
         "targets": {"<매체>": "<get_target_progress_v2(month=M0, media=<매체>) 응답 원문>", ...}}   # 선택 — 예전 입력
  # 브랜드 전체 목표는 s1.target_progress 첫째 표, 매체 목표는 같은 원문의 둘째 표 매체 행을 쓴다(매체마다 부르지 않는다).
  # 목표가 없는 지표·단위는 조용히 '-'.
}
- s3(월별 광고 성과)은 s1 봉투, s5(매체 성과 비교)는 s4 봉투에서 만든다 — 따로 넘기지 않는다.
- 키가 없거나 null인 섹션은 "데이터 준비 중"으로 렌더링된다.
- 출력(stdout): {"out", "bytes", "sections": {"s1".."s6": "ok"|"placeholder"}}
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
S6_DIMS = ("media", "campaign_name")   # 예산 및 목표 달성 결과 표의 Dimension


def shift(y, m, back):
    n = y * 12 + (m - 1) - back
    return n // 12, n % 12 + 1


def compute(payload, check_dims=True):
    y, m = map(int, str(payload["month"])[:7].split("-"))
    months = [shift(y, m, 5 - i) for i in range(6)]
    keys6 = [f"{a:04d}-{b:02d}" for a, b in months]
    M0, M1 = keys6[-1], keys6[-2]
    skeleton = bool(payload.get("skeleton"))
    keys = payload.get("metric_keys") or {}
    currency = payload.get("currency") or "₩"

    def sec(name):
        return None if skeleton else payload.get(name)

    def env(name):
        s = sec(name)
        return kit.section_envelope(s)

    e1, e4, e6 = env("s1"), env("s4"), env("s6")
    if e6 and check_dims:
        kit.require_dims(payload.get("dims"), [("s6", e6)], "s6 피벗 표")
    kit.require_rollup([("전체 ↔ 매체(s1·s4)", kit.check_rollup(e1, [], e4, [], keys)),
                        ("매체 ↔ 표(s4·s6)", kit.check_rollup(e4, ["media"], e6, ["media"], keys))])
    i1 = kit.index_rows(e1, [])
    i4 = kit.index_rows(e4, ["media"])
    i6 = kit.index_rows(e6, ["media", P])
    metrics, units = kit.metrics_units(e1, e4, e6)
    meta = kit.metric_meta(metrics, units, currency, kit.additive_metrics(i1, i4, metrics, units, keys), keys)
    mm = kit.meta_map(meta)
    media = kit.ordered_names(i4) or kit.ordered_names(i6)
    colors = kit.media_colors(media)
    cost = keys.get("cost")
    yy = lambda k: f"{k[2:4]}년 {int(k[5:])}월"  # noqa: E731
    tot = lambda k: (i1.get(k) or {}).get(()) or {}  # noqa: E731
    sections = {}

    if e1 and tot(M0):
        cur, prev = tot(M0), tot(M1)
        target = kit.parse_target_progress((sec("s1") or {}).get("target_progress"))["cost_target"]
        if target and isinstance(cur.get(cost), (int, float)):
            budget = {"key": "__budget", "label": "예산 소진율", "value": f"{cur[cost] / target * 100:.1f}%", "bar": cur[cost] / target,
                      "sub": f"월 예산 {kit.fmt_metric(target, currency)}", "deltas": []}
        else:
            budget = {"key": "__budget", "label": "예산 소진율", "value": "N/A", "sub": "이번 달 등록된 예산 목표가 없습니다", "deltas": []}
        cards = kit.kpi_cards(cur, [("prev", "전월", prev)], keys, meta)
        for c, role in zip(cards, [r for r in kit.ROLES if keys.get(r)]):
            k = keys[role]
            c["sub"] = f"전월 {kit.fmt_metric(prev.get(k), mm[k]['unit'])}" if k in mm else None
        # 기본 카드 = 예산 소진율 + 고정 7 역할, 그 밖의 서빙 지표는 전월 대비 카드로 덧붙여 지표 메뉴에서 켠다
        sections["s1"] = kit.kpi_more([budget] + cards, cur, [("prev", "전월", prev)], meta, "monthly", sub_label="전월")

        if cost in mm:   # 막대 = 광고비 고정, 꺾은선 = 드롭다운으로 고르는 지표 하나(기본 CPV, 없으면 첫 지표). 다른 지표가 없으면 막대만
            sections["s3"] = {"labels": [f"{b}월" for _, b in months],
                              "bar": {"label": kit.ROLE_LABELS["cost"], "unit": mm[cost]["unit"], "color": kit.BAR_COLOR,
                                      "data": [tot(k).get(cost) for k in keys6]},
                              "line_color": kit.LINE_COLOR,
                              "line_options": [{"key": x["key"], "label": x["label"], "unit": x["unit"],
                                                "data": [tot(k).get(x["key"]) for k in keys6]} for x in meta if x["key"] != cost],
                              "line_default": keys.get("cpv")}

    # s2 — Executive Summary (모델 작성): [소진]·[효율] 그룹(weekly와 같은 모양). 예전 불릿 입력도 받는다
    s2 = sec("s2")
    groups = (s2 or {}).get("groups") if isinstance(s2, dict) else None
    if groups:
        sections["s2"] = {"groups": [{"title": g.get("title", ""), "lead": g.get("lead", ""),
                                      "media": [dict(x, dot=x.get("dot") or colors.get(x.get("name"))) for x in g.get("media") or []]}
                                     for g in groups]}
    elif s2:
        b = kit.bullets_of(s2)
        sections["s2"] = {"bullets": b} if b else None

    if e4:
        cur_by = {n: ((i4.get(M0) or {}).get((n,)) or {}) for n in media}
        legend = kit.share_legend(cur_by, meta, currency)
        sections["s4"] = {"labels": [f"{b}월" for _, b in months], "metrics": meta, "default_metric": cost,
                          "legend_toggle": True, "metric_select": True,
                          "series": [{"name": n, "color": colors[n], "legend": legend[n],
                                      "values": kit.series_values(i4, keys6, (n,), metrics)} for n in media],
                          "note": f"* 범례 값은 {m}월 기준이며, 비중(%)은 합산 가능한 지표에만 표시합니다."}
        rows = [{"names": [n], "kind": "row", "dot": colors[n], "cur": cur_by[n],
                 "base": {"prev": (i4.get(M1) or {}).get((n,)) or {}}} for n in media]
        if tot(M0):
            rows.append({"names": ["전체"], "kind": "total", "cur": tot(M0), "base": {"prev": tot(M1)}})
        # 지표 메뉴: 처음엔 고정 7 역할만 그 순서로(광고비 맨 앞 고정), 나머지 서빙 지표는 메뉴에서 켠다
        role_order = [keys[r] for r in kit.ROLES if keys.get(r)]
        s5_metrics = sorted(meta, key=lambda x: role_order.index(x["key"]) if x["key"] in role_order else len(role_order))
        sections["s5"] = {"name_cols": ["매체"], "metrics": s5_metrics, "rows": rows,
                          "compares": {"prev": {"base_label": yy(M1), "cur_label": yy(M0)}},
                          "metric_pick": {"default": role_order, "pin": cost}}

    t_media, t_camp = {}, {}
    if e6:   # 예산 및 목표 달성 결과: s6 = month grain, group_by = 제공 차원 전부 — M0만 쓴다
        fine = kit.split_by_period(e6, {M0: M0})
        t_all = kit.parse_targets((sec("s1") or {}).get("target_progress"), keys)
        # 매체 목표 = s1 목표 원문(media 생략)의 둘째 표 매체 행. 매체마다 따로 부른 원문(s6.targets)이 있으면 그것이 우선
        tp = (sec("s1") or {}).get("target_progress")
        t_media = kit.parse_media_targets(tp, keys, metrics)
        t_media.update({str(x): t for x, raw in ((sec("s6") or {}).get("targets") or {}).items()
                        if (t := kit.parse_targets(raw, keys))})
        # 캠페인 목표(dashboard 브랜드만) = 같은 원문의 캠페인 행 — 표의 캠페인 행 예산·소진율, CPM·CPC 목표 대비
        t_camp = kit.parse_campaign_targets(tp, keys, metrics)
        tv = {"levels": [[], ["media"], ["media", "campaign_name"]],
              "values": {0: {"": t_all} if t_all else {}, 1: t_media,
                         2: {"\u0001".join(k): v for k, v in t_camp.items()}}}
        sec6 = kit.pick_section(fine, meta, keys, dots=colors, default_dims=list(S6_DIMS),
                                search_dim="campaign_name", totals={M0: tot(M0)} if e1 else None,
                                goal={"cur": M0, "cur_label": f"{m}월", "targets": tv, "full": True})
        if sec6:   # Dimension은 매체·캠페인만 보여 준다(응답의 더 잘게 받은 차원은 요약 근거에만 쓴다)
            sec6["dims"] = [d for d in sec6["dims"] if d["key"] in S6_DIMS] or sec6["dims"]
            sec6["default_dims"] = [d["key"] for d in sec6["dims"]]
        sections["s6"] = sec6

    for k in ("s1", "s2", "s3", "s4", "s5", "s6"):
        sections.setdefault(k, None)
    report = {"currency": currency, "sections": sections}
    first = date(y, m, 1)
    last = date(*shift(y, m, -1), 1) - timedelta(days=1)
    pfirst = date(*shift(y, m, 1), 1)
    plast = first - timedelta(days=1)
    rep = {
        "__TITLE__": payload["title"],
        "__PERIOD__": f"{first.year}년 {first.month}월 1일 ~ {last.month}월 {last.day}일",
        "__PREV_PERIOD__": f"{pfirst.year}년 {pfirst.month}월 1일 ~ {plast.month}월 {plast.day}일 (전월)",
        "__MEDIA_SUM__": (" + ".join(media) + " 합산, ") if media else "",
        "__CMP_TITLE__": f"{yy(M1)} vs {yy(M0)}",
        "__CUR_MONTH__": yy(M0),
        "__CUR_RANGE__": f"{m}월 1일~{m}월 {last.day}일",
    }
    ctx = {"keys": keys, "currency": currency, "metrics": metrics, "units": units, "media": media, "tot": tot,
           "i4": i4, "e6": e6, "M0": M0, "M1": M1, "t_media": t_media, "t_camp": t_camp,
           "target_all": kit.parse_target_progress((sec("s1") or {}).get("target_progress"))["cost_target"] if e1 else None}
    return sections, rep, report, ctx


def digest(payload):
    """Executive Summary 작성 근거 — 당월·전월 값과 변화(전체, 매체 + 광고비 비중·월 예산·소진율, 매체-캠페인·광고그룹).
    세부 단위는 광고비 상위 + 전월 대비 광고비 변동 상위(kit.digest_levels). 화면 표와 같은 규칙의 숫자다."""
    _, _, _, c = compute(payload, check_dims=False)
    keys, metrics, units, cur_c, M0, M1 = c["keys"], c["metrics"], c["units"], c["currency"], c["M0"], c["M1"]
    cost = keys.get("cost")
    _, fmt, change = kit.digest_fmt(keys, units, cur_c)

    def row(name, a, b):
        return {"이름": name, "당월": fmt(a), "전월": fmt(b), "전월 대비": change(a, b)}

    out = {"당월": M0, "전월": M1}
    t0 = c["tot"](M0)
    if t0:
        out["전체"] = row("전체", t0, c["tot"](M1))
        sp, bud = t0.get(cost), c["target_all"]
        out["예산"] = {"월예산": kit.fmt_metric(bud, cur_c, cur_c) if bud else None,
                     "소진율": f"{sp / bud * 100:.1f}%" if bud and isinstance(sp, (int, float)) else None}
    if c["media"]:
        i4 = c["i4"]
        cur_by = {n: (i4.get(M0) or {}).get((n,)) or {} for n in c["media"]}
        total_cost = sum(v.get(cost) or 0 for v in cur_by.values())
        def media_row(n):
            r = dict(row(n, cur_by[n], (i4.get(M1) or {}).get((n,)) or {}),
                     광고비비중=f"{(cur_by[n].get(cost) or 0) / total_cost * 100:.1f}%" if total_cost else None)
            bud, sp = (c["t_media"].get(n) or {}).get(cost), cur_by[n].get(cost)
            if bud:   # 매체 월 예산이 있으면 소진율(100% ± 10%p 밖이면 저조·초과)
                r.update(월예산=kit.fmt_metric(bud, cur_c, cur_c),
                         소진율=f"{sp / bud * 100:.1f}%" if isinstance(sp, (int, float)) else None)
            return r

        out["매체"] = [media_row(n) for n in sorted(c["media"], key=lambda n: -(cur_by[n].get(cost) or 0))]
    e6 = c["e6"]
    if e6:
        split = kit.split_by_period(e6, {M0: M0, M1: M1})
        out.update(kit.digest_levels([split.get(M0), split.get(M1)], kit.DIGEST_LEVELS[:2], metrics, units, keys, row))
        # 캠페인 월 예산이 있으면(dashboard 브랜드) 매체-캠페인 행에 예산·소진율을 붙인다 — 집행액은 표와 같은 광고비 값
        cur_camp = kit.group_values(split.get(M0), ["media", "campaign_name"], metrics, units, keys)
        for r in out.get("매체-캠페인") or []:
            k = tuple(r["이름"].split(" / ", 1))
            bud, sp = (c["t_camp"].get(k) or {}).get(cost), (cur_camp.get(k) or {}).get(cost)
            if bud:
                r.update(월예산=kit.fmt_metric(bud, cur_c, cur_c),
                         소진율=f"{sp / bud * 100:.1f}%" if isinstance(sp, (int, float)) else None)
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

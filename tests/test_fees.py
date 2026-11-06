#!/usr/bin/env python3
"""광고비·예산 Gross / Net 규칙(shared/assets/fees.py)과 Weekly·Monthly·종합 리포트 빌더의 연결 자체 검사(표준 라이브러리만).
기대값은 손으로 계산한 값이다: 마크업 Gross = Net × (1 + r/100), 커미션 Gross = Net ÷ (1 − r/100). 성공하면 "ok"."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
sys.path.insert(0, os.path.join(PLUGIN, "shared", "assets"))

import fees  # noqa: E402
import report_kit as kit  # noqa: E402


def _builder(skill):
    path = os.path.join(PLUGIN, "skills", skill, "assets", "build_report.py")
    spec = importlib.util.spec_from_file_location(f"build_{skill.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


weekly, monthly, overall = _builder("weekly-report"), _builder("monthly-report"), _builder("overall-summary")
sys.path.insert(0, os.path.join(PLUGIN, "skills", "overall-summary", "assets"))
import budget_targets  # noqa: E402

KEYS = {"cost": "cost", "impression": "impressions", "cpm": "cpm"}
METRICS = ["cost", "impressions", "cpm", "roas"]
UNITS = {"cost": "₩", "impressions": None, "cpm": "₩", "roas": "%"}


def close(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-6


def env(rows, dims, basis="net", fee_list=(), grain="day"):
    e = {"source": "elt", "tenant": "t", "time_grain": grain, "dimensions": dims, "metrics": METRICS,
         "metric_units": UNITS, "row_count": len(rows), "rows": rows}
    if basis:
        e.update(fee_basis=basis, fees=list(fee_list))
    return e


def fee(media, month, mode, rate):
    return {"media": media, "month": month, "fee_mode": mode, "rate": rate}


def costs(e):
    return [r.get("cost") for r in e["rows"]]


# ── 규칙(fees.py) ─────────────────────────────────────────────────────────────


def test_markup_both_directions():
    table = fees.fee_table([env([], ["media"], fee_list=[fee("Meta", "2026-10", "markup", 10)])])
    row = {"date": "2026-10-05", "media": "Meta", "cost": 1000, "impressions": 200, "cpm": 5000, "roas": 330}
    g = fees.convert_envelope(env([row], ["media"]), table, "net", "gross", KEYS)["rows"][0]
    assert close(g["cost"], 1100) and close(g["cpm"], 5500) and close(g["roas"], 300), g   # roas = 330 ÷ 1.1
    assert g["impressions"] == 200
    n = fees.convert_envelope(env([dict(row, cost=1100)], ["media"], "gross"), table, "gross", "net", KEYS)["rows"][0]
    assert close(n["cost"], 1000), n


def test_commission_both_directions():
    table = fees.fee_table([env([], ["media"], fee_list=[fee("Google", "2026-10", "commission", 20)])])
    row = {"date": "2026-10-05", "media": "Google", "cost": 800}
    assert close(costs(fees.convert_envelope(env([row], ["media"]), table, "net", "gross", KEYS))[0], 1000)   # 800 ÷ 0.8
    row = dict(row, cost=1000)
    assert close(costs(fees.convert_envelope(env([row], ["media"], "gross"), table, "gross", "net", KEYS))[0], 800)   # 1000 × 0.8


def test_media_without_fee_and_same_basis():
    table = fees.fee_table([env([], ["media"], fee_list=[fee("Meta", "2026-10", "markup", 10)])])
    e = env([{"date": "2026-10-05", "media": "Naver", "cost": 500}, {"date": "2026-10-05", "media": None, "cost": 70}], ["media"])
    assert costs(fees.convert_envelope(e, table, "net", "gross", KEYS)) == [500, 70]
    assert fees.convert_envelope(e, table, "net", "net", KEYS) is e   # 서버 기준 그대로 보는 보기는 손대지 않는다


def test_two_months_different_fees():
    fl = [fee("Meta", "2026-09", "markup", 10), fee("Meta", "2026-10", "markup", 20)]
    table = fees.fee_table([env([], ["media"], fee_list=fl)])
    day = env([{"date": "2026-09-30", "media": "Meta", "cost": 1000}, {"date": "2026-10-01", "media": "Meta", "cost": 1000},
               {"date": "2026-09-30", "media": "Naver", "cost": 500}, {"date": "2026-10-01", "media": "Naver", "cost": 1000}],
              ["media"])
    g = fees.convert_envelope(day, table, "net", "gross", KEYS)
    assert [round(c, 6) for c in costs(g)] == [1100, 1200, 500, 1000]
    # 매체가 없는 달 합계: 더 잘게 받은 응답(일 × 매체)의 그 달 실효 배수 — 9월 1600/1500, 10월 2200/2000
    month = env([{"month": "2026-09", "cost": 1500}, {"month": "2026-10", "cost": 2000}], [], grain="month")
    eff = fees.eff_factors([(day, g, lambda r: kit.period_of(r)[:7])], KEYS)
    gm = fees.convert_envelope(month, table, "net", "gross", KEYS, eff=eff)
    assert close(costs(gm)[0], 1600) and close(costs(gm)[1], 2200), costs(gm)
    # 두 달에 걸친 total 행(9/28~10/4, 하루 100씩): 더 잘게 받은 응답이 없으면 일수 가중 — (3×1.1 + 4×1.2) ÷ 7 × 700 = 810
    week = env([{"media": "Meta", "campaign_name": "A", "cost": 700}], ["media", "campaign_name"], grain="total")
    win = fees.window_months(date(2026, 9, 28), date(2026, 10, 4))
    assert win == {"2026-09": 3, "2026-10": 4}
    assert close(costs(fees.convert_envelope(week, table, "net", "gross", KEYS, window=win))[0], 810)
    # 같은 달 안의 total 행은 그 달 수수료 그대로
    win10 = fees.window_months(date(2026, 10, 1), date(2026, 10, 7))
    assert close(costs(fees.convert_envelope(week, table, "net", "gross", KEYS, window=win10))[0], 840)


NEW_TEXT = """month: 2026-10
as_of_date: 2026-10-20
media: all
fee_basis: {basis}

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | {total} | 1500 | 0.5 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | {meta} | 500 | 0.5 |
| Meta | - | - | cpm | {cpm} | 4800 | 0.96 |
| Meta | Brand | Y | cost | {brand} | 200 | 0.5 |
| Google | - | - | cost | {google} | 600 | 0.5 |
| Naver | - | - | cost | 800 | 400 | 0.5 |

| media | fee_mode | rate |
| --- | --- | --- |
| Meta | markup | 10 |
| Google | commission | 20 |"""
NET = dict(basis="net", total=3000, meta=1000, cpm=5000, brand=400, google=1200)
GROSS = dict(basis="gross", total=3400, meta=1100, cpm=5500, brand=440, google=1500)


def test_target_text_both_directions():
    for src, dst in ((NET, GROSS), (GROSS, NET)):
        text = NEW_TEXT.format(**src)
        table = fees.fee_table([], [text])
        assert table[("meta", "2026-10")]["mode"] == "markup" and table[("google", "2026-10")]["rate"] == 20
        out = fees.convert_target_text(text, table, src["basis"], dst["basis"])
        t = kit.parse_targets(out, KEYS)
        media = kit.parse_media_targets(out, KEYS, METRICS)
        camp = kit.parse_campaign_targets(out, KEYS, METRICS)
        assert close(t["cost"], dst["total"]), (src["basis"], t)   # 첫째 표 = 매체 행 환산 합(1100 + 1500 + 800)
        assert close(media["Meta"]["cost"], dst["meta"]) and close(media["Meta"]["cpm"], dst["cpm"]), media
        assert close(media["Google"]["cost"], dst["google"]) and media["Naver"]["cost"] == 800, media
        assert close(camp[("Meta", "Brand")]["cost"], dst["brand"]), camp   # 캠페인은 그 매체 수수료
        assert f"fee_basis: {dst['basis']}" in out


def test_served_basis():
    old_text = "| metric | target | actual | progress_ratio |\n| cost | 1100 | 500 | 0.4 |"
    assert fees.served_basis([env([], ["media"], basis=None)], [old_text, "No all budget/target available for 2026-10."]) is None
    assert fees.served_basis([env([], ["media"], basis="gross")], [NEW_TEXT.format(**GROSS)]) == "gross"
    for envs, texts in (([env([], [], basis="net"), env([], [], basis=None)], []),
                        ([env([], [], basis="net")], [old_text]),
                        ([env([], [], basis="net")], [NEW_TEXT.format(**GROSS)])):
        try:
            fees.served_basis(envs, texts)
        except SystemExit:
            continue
        raise AssertionError("새·옛 응답이나 net·gross가 섞이면 멈춰야 한다")


def test_split_envelopes_keep_every_months_fees():
    a = env([{"date": "2026-09-30", "media": "Meta", "cost": 1}], ["media"], fee_list=[fee("Meta", "2026-09", "markup", 10)])
    b = env([{"date": "2026-10-01", "media": "Meta", "cost": 1}], ["media"], fee_list=[fee("Meta", "2026-10", "markup", 20)])
    merged = kit.merged_envelope([a, b])
    assert sorted(f["month"] for f in merged["fees"]) == ["2026-09", "2026-10"]
    try:
        kit.merged_envelope([a, dict(b, fee_basis="gross")])
    except SystemExit:
        return
    raise AssertionError("조각마다 fee_basis가 다르면 멈춰야 한다")


def test_fee_note_and_ui():
    fl = [fee("Meta", "2026-09", "markup", 10), fee("Meta", "2026-10", "markup", 12.5), fee("Google", "2026-10", "commission", 15)]
    table = fees.fee_table([env([], ["media"], fee_list=fl)])
    both = ["2026-09", "2026-10"]
    assert fees.served_fee_note(table, "net", both) == "브랜드 기준 Net · 수수료 Meta(9월 마크업 10%, 10월 마크업 12.5%) · Google(10월 커미션 15%)"
    assert fees.served_fee_note(table, "net", ["2026-10"]) == "브랜드 기준 Net · 수수료 Meta 마크업 12.5% · Google 커미션 15%"
    assert fees.served_fee_note(table, "net", ["2026-10", "2026-11"]) == "브랜드 기준 Net · 수수료 Meta(10월 마크업 12.5%) · Google(10월 커미션 15%)"
    assert fees.served_fee_note(table, "net", ["2026-08"]) == "브랜드 기준 Net"
    same = fees.fee_table([env([], ["media"], fee_list=[fee("Meta", "2026-09", "markup", 12.5), fee("Meta", "2026-10", "markup", 12.5)])])
    assert fees.served_fee_note(same, "net", both) == "브랜드 기준 Net · 수수료 Meta 마크업 12.5%"
    ui = fees.served_ui("net")
    assert ui["default"] == "net" and [o["key"] for o in ui["options"]] == ["gross", "net"]
    assert "브랜드 설정" in ui["options"][1]["title"] and "환산" in ui["options"][0]["title"]


def test_conflicting_fee_stops():
    a = env([], ["media"], fee_list=[fee("Meta", "2026-10", "markup", 10)])
    text = NEW_TEXT.format(**NET)
    assert fees.fee_table([a], [text])[("meta", "2026-10")]["rate"] == 10   # 같은 수수료는 그대로 합친다
    for other in (NEW_TEXT.replace("| Meta | markup | 10 |", "| Meta | markup | 12 |"),
                  NEW_TEXT.replace("| Meta | markup | 10 |", "| meta | commission | 10 |")):
        try:
            fees.fee_table([a], [other.format(**NET)])
        except SystemExit as e:
            assert "Meta" in str(e) and "2026-10" in str(e) and "마크업 10%" in str(e), e
            continue
        raise AssertionError("같은 매체·달의 수수료가 응답마다 다르면 멈춰야 한다")


# ── 빌더 연결 ────────────────────────────────────────────────────────────────

WEEK_FEES = {"s3": [fee("Meta", "2026-09", "markup", 10), fee("Meta", "2026-10", "markup", 20)],
             "cur": [fee("Meta", "2026-10", "markup", 20)], "base": [fee("Meta", "2026-09", "markup", 10)]}
OLD_TP = """month: 2026-10
as_of_date: 2026-10-07
media: all

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 1060 | 400 | 0.38 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 660 | 300 | 0.45 |
| Meta | - | - | cost_net | 600 | - | - |
| Naver | - | - | cost | 400 | 100 | 0.25 |
| Naver | - | - | cost_net | 400 | - | - |"""
NEW_TP = """month: 2026-10
as_of_date: 2026-10-07
media: all
fee_basis: net

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 1000 | 400 | 0.4 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 600 | 300 | 0.5 |
| Naver | - | - | cost | 400 | 100 | 0.25 |

| media | fee_mode | rate |
| --- | --- | --- |
| Meta | markup | 20 |"""


def weekly_payload(new):
    """E = 10/7: 이번주 10/1~7(10월), 전주 9/24~30(9월). Meta 수수료 9월 마크업 10%, 10월 20%. Naver 수수료 없음."""
    b = "net" if new else None

    def fl(k):
        return WEEK_FEES[k] if new else ()

    s3 = [{"date": "2026-09-07", "media": "Meta", "cost": 100, "impressions": 100},
          {"date": "2026-09-25", "media": "Meta", "cost": 200, "impressions": 400},
          {"date": "2026-09-25", "media": "Naver", "cost": 100, "impressions": 200},
          {"date": "2026-10-02", "media": "Meta", "cost": 300, "impressions": 1000},
          {"date": "2026-10-02", "media": "Naver", "cost": 100, "impressions": 500}]

    def week(m, n, mi, ni):
        return [{"media": "Meta", "campaign_name": "A", "cost": m, "impressions": mi},
                {"media": "Naver", "campaign_name": "B", "cost": n, "impressions": ni}]

    return {"out": "unused.html", "title": "t", "target_date": "2026-10-07", "metric_keys": KEYS, "currency": "₩",
            "dims": "valid dimensions: ['date', 'media', 'campaign_name']",
            "s1": {"json": json.dumps(env([{"month": "2026-09", "cost": 100}, {"month": "2026-10", "cost": 400}], [],
                                          basis=b, grain="month")),
                   "target_progress": NEW_TP if new else OLD_TP},
            "s3": {"json": json.dumps(env(s3, ["media"], basis=b, fee_list=fl("s3")))},
            "s4": {"cur": {"json": json.dumps(env(week(300, 100, 1000, 500), ["media", "campaign_name"], b, fl("cur"), "total"))},
                   "base": {"json": json.dumps(env(week(200, 100, 400, 200), ["media", "campaign_name"], b, fl("base"), "total"))}}}


def test_weekly_served_net():
    p = weekly_payload(new=True)
    view, served, table = weekly.fee_view(p)
    assert (view, served) == ("net", "net") and table
    _, _, c = weekly.compute(p, check_dims=False, basis="net")   # 기본 보기 = 서버 값 그대로
    assert c["tot"]["cost"] == 400 and c["targets"]["cost"] == 1000
    _, _, c = weekly.compute(p, check_dims=False, basis="gross")
    # s1 10월: s3의 10/1~7 실효 배수 (300×1.2 + 100) ÷ 400 = 1.15 → 460. 예산 = 600×1.2 + 400 = 1120
    assert close(c["tot"]["cost"], 460) and close(c["targets"]["cost"], 1120), (c["tot"], c["targets"])
    cur = {r["media"]: r for r in c["fine"]["cur"]["rows"]}
    base = {r["media"]: r for r in c["fine"]["base"]["rows"]}
    assert close(cur["Meta"]["cost"], 360) and close(base["Meta"]["cost"], 220) and cur["Naver"]["cost"] == 100
    s3 = {(r["date"], r["media"]): r["cost"] for r in c["e3"]["rows"]}
    assert close(s3[("2026-09-07", "Meta")], 110) and close(s3[("2026-10-02", "Meta")], 360)


def prev_month_cost(target_date, basis):
    """E = target_date. s1 9월 MTD(9/1~E의 일) 광고비 200, s3(일 × 매체)는 E-34부터. Meta 수수료 9월 마크업 10%·10월 20%."""
    s3 = [{"date": "2026-09-03", "media": "Meta", "cost": 100}, {"date": "2026-09-04", "media": "Naver", "cost": 100},
          {"date": "2026-09-20", "media": "Meta", "cost": 500}, {"date": "2026-10-02", "media": "Meta", "cost": 200},
          {"date": "2026-10-02", "media": "Naver", "cost": 100}]
    p = {"out": "unused.html", "title": "t", "target_date": target_date, "metric_keys": KEYS, "currency": "₩",
         "s1": {"json": json.dumps(env([{"month": "2026-09", "cost": 200}, {"month": "2026-10", "cost": 300}], [], grain="month")),
                "target_progress": NEW_TP},
         "s3": {"json": json.dumps(env(s3, ["media"], fee_list=WEEK_FEES["s3"]))}}
    cards = {c["key"]: c for c in weekly.compute(p, check_dims=False, basis=basis)[0]["s1"]["cards"]}
    return cards["cost"]["sub"]


def test_weekly_previous_month_needs_covered_window():
    # E = 10/4: E-34 = 8/31이라 9월 1일~4일이 s3에 모두 있다 — 9월 실효 배수 (100×1.1 + 100) ÷ 200 = 1.05 → 210
    assert prev_month_cost("2026-10-04", "gross") == "전월 동기간 ₩210"
    # E = 10/7: E-34 = 9/3이라 9월 1~2일이 s3에 없다 — 9월에 Meta 수수료가 있으니 추정하지 않고 빈칸. 서버 기준 보기는 그대로 200
    assert prev_month_cost("2026-10-07", "gross") == "전월 동기간 -"
    assert prev_month_cost("2026-10-07", "net") == "전월 동기간 ₩200"


def test_weekly_old_format_unchanged():
    p = weekly_payload(new=False)
    assert weekly.fee_view(p) == ("gross", None, {})
    _, _, c = weekly.compute(p, check_dims=False, basis="gross")
    # 옛 규칙: Meta 비율 660/600 = 1.1을 모든 달에. s1 10월 = s3 10월 실효 (300×1.1 + 100) ÷ 400 → 430. 예산 = Gross 1060
    assert close(c["tot"]["cost"], 430) and c["targets"]["cost"] == 1060, (c["tot"], c["targets"])
    _, _, c = weekly.compute(p, check_dims=False, basis="net")
    assert c["tot"]["cost"] == 400 and c["targets"]["cost"] == 1000   # Net 예산 = 1060 − Meta 수수료 60


def test_weekly_main_report_basis():
    with tempfile.TemporaryDirectory() as d:
        for new, default, alt in ((True, "net", "gross"), (False, "gross", "net")):
            p = dict(weekly_payload(new), out=os.path.join(d, "w.html"))
            path = os.path.join(d, "in.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False)
            script = os.path.join(PLUGIN, "skills", "weekly-report", "assets", "build_report.py")
            subprocess.run([sys.executable, script, path], check=True, capture_output=True)
            html = open(p["out"], encoding="utf-8").read()
            assert f'"default":"{default}"' in html.replace(" ", "") and f'"sections":{{"{alt}"' in html.replace(" ", ""), new


MONTH_TP = """month: 2026-10
as_of_date: 2026-10-31
media: all
fee_basis: net

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 3000 | 1800 | 0.6 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 1500 | 1000 | 0.67 |
| Meta | A | Y | cost | 900 | 600 | 0.67 |
| Google | - | - | cost | 1500 | 800 | 0.53 |

| media | fee_mode | rate |
| --- | --- | --- |
| Meta | markup | 20 |
| Google | commission | 20 |"""


def test_monthly_served_net():
    """Meta 9월 마크업 10%·10월 20%, Google 9월 없음·10월 커미션 20%."""
    fl = [fee("Meta", "2026-09", "markup", 10), fee("Meta", "2026-10", "markup", 20), fee("Google", "2026-10", "commission", 20)]
    s4 = [{"month": m, "media": x, "cost": v} for m in ("2026-09", "2026-10") for x, v in (("Meta", 1000), ("Google", 800))]
    s6 = [{"month": "2026-09", "media": "Meta", "campaign_name": "A", "cost": 1000},
          {"month": "2026-09", "media": "Google", "campaign_name": "C", "cost": 800},
          {"month": "2026-10", "media": "Meta", "campaign_name": "A", "cost": 600},
          {"month": "2026-10", "media": "Meta", "campaign_name": "B", "cost": 400},
          {"month": "2026-10", "media": "Google", "campaign_name": "C", "cost": 800}]
    p = {"out": "unused.html", "title": "t", "month": "2026-10", "metric_keys": KEYS, "currency": "₩",
         "s1": {"json": json.dumps(env([{"month": "2026-09", "cost": 1800}, {"month": "2026-10", "cost": 1800}], [],
                                       grain="month")), "target_progress": MONTH_TP},
         "s4": {"json": json.dumps(env(s4, ["media"], fee_list=fl, grain="month"))},
         "s6": {"json": json.dumps(env(s6, ["media", "campaign_name"], fee_list=fl, grain="month"))}}
    view, served, _ = monthly.fee_view(p)
    assert (view, served) == ("net", "net")
    _, _, _, c = monthly.compute(p, check_dims=False, basis="gross")
    assert close(c["tot"]("2026-09")["cost"], 1900) and close(c["tot"]("2026-10")["cost"], 2200)   # 1100 + 800, 1200 + 1000
    assert close(c["target_all"], 3675)   # 1500×1.2 + 1500÷0.8
    assert close(c["t_media"]["Meta"]["cost"], 1800) and close(c["t_media"]["Google"]["cost"], 1875)
    assert close(c["t_camp"][("Meta", "A")]["cost"], 1080)
    oct6 = {r["campaign_name"]: r["cost"] for r in c["e6"]["rows"] if r["month"] == "2026-10"}
    assert close(oct6["A"], 720) and close(oct6["B"], 480) and close(oct6["C"], 1000)


OVERALL_TP = """month: 2026-10
as_of_date: 2026-10-05
media: all
fee_basis: gross

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 3600 | 2000 | 0.56 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 1100 | 1100 | 1 |
| Meta | - | - | cpm | 5500 | 5500 | 1 |
| Meta | A | Y | cost | 440 | 440 | 1 |
| Google | - | - | cost | 2000 | 500 | 0.25 |
| Naver | - | - | cost | 500 | 400 | 0.8 |

| media | fee_mode | rate |
| --- | --- | --- |
| Meta | markup | 10 |
| Google | commission | 20 |"""


def test_overall_budgets_and_rows():
    """서버 기준 Gross. Meta 마크업 10%, Google 커미션 20%, Naver 수수료 없음."""
    budgets = budget_targets.parse_budget({"month": "2026-10", "target_progress": OVERALL_TP})
    table = fees.fee_table([], [OVERALL_TP])
    net = {json.dumps(sorted(b["scope"].items())): b["v"] for b in fees.convert_budgets(budgets, table, "gross", "net",
                                                                                         budget_targets.derive_targets)}

    def key(**sc):
        return json.dumps(sorted(sc.items()))
    assert close(net[key()]["cost"], 3100)   # 1000 + 1600 + 500
    assert close(net[key(m="Meta")]["cost"], 1000) and close(net[key(m="Meta")]["cpm"], 5000)
    assert close(net[key(m="Meta")]["imp"], 200)   # 노출 = 예산 ÷ CPM × 1000 — 기준이 바뀌어도 같다
    assert close(net[key(m="Meta", c="A")]["cost"], 400) and close(net[key(m="Google")]["cost"], 1600)
    rows = [{"day": date(2026, 10, 1), "m": "Meta", "cost": 1100}, {"day": date(2026, 10, 1), "m": "Google", "cost": 500},
            {"day": date(2026, 10, 1), "m": "Naver", "cost": 400}]
    fees.add_cost_views(rows, table, "gross")
    assert [(r["cost"], r["cost_g"]) for r in rows] == [(1000, 1100), (400, 500), (400, 400)]


def test_overall_compute_served_gross():
    rows = [{"date": "2026-10-01", "media": m, "campaign_name": c, "cost": v, "impressions": 100}
            for m, c, v in (("Meta", "A", 1100), ("Google", "G", 500), ("Naver", "N", 400))]
    fl = [fee("Meta", "2026-10", "markup", 10), fee("Google", "2026-10", "commission", 20)]
    p = {"out": "unused.html", "brand": "b", "target_date": "2026-10-05", "start_date": "2026-10-01", "metric_keys": KEYS,
         "currency": "₩", "dims": "valid dimensions: ['date', 'media', 'campaign_name']",
         "data": {"json": json.dumps(env(rows, ["media", "campaign_name"], "gross", fl))},
         "budgets": [{"month": "2026-10", "target_progress": OVERALL_TP}]}
    report, out = overall.compute(p)
    assert report["fee"]["default"] == "gross" and "브랜드 기준 Gross" in report["fee"]["note"]
    by = {r["m"]: (r["cost"], r["cost_g"]) for r in out}
    assert by == {"Meta": (1000, 1100), "Google": (400, 500), "Naver": (400, 400)}, by

    def total(bs):
        return next(b["v"]["cost"] for b in bs if not b["scope"])
    assert total(report["table"]["budgets"]) == 3600 and close(total(report["table"]["budgets_net"]), 3100)
    rep, rs = overall.basis_view(report, out, "net")   # _net.xlsx가 보는 값
    assert rep["header"]["basis"] == "Net" and sorted(r["cost"] for r in rs) == [400, 400, 1000]


def test_overall_stops_on_legacy_placement():
    rows = [{"date": "2026-10-01", "media": "Meta", "campaign_name": "A", "cost": 1100, "impressions": 100}]
    prow = [{"date": "2026-10-01", "media": "Meta", "placement": "feed", "cost": 1000, "impressions": 100}]
    p = {"out": "unused.html", "brand": "b", "target_date": "2026-10-05", "start_date": "2026-10-01", "metric_keys": KEYS,
         "currency": "₩", "dims": "valid dimensions: ['date', 'media', 'campaign_name']",
         "data": {"json": json.dumps(env(rows, ["media", "campaign_name"], "gross"))},
         "place": {"json": json.dumps(env(prow, ["media", "placement"], None))}}
    try:
        overall.compute(p)
    except SystemExit as e:
        assert "수수료 기준" in str(e.code)
        return
    raise AssertionError("fee_basis가 없는 Placement 응답에서 멈추지 않았다")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

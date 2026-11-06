#!/usr/bin/env python3
"""Weekly·Monthly·종합 리포트 빌더의 광고비·예산 Gross / Net 연결 검사(표준 라이브러리만). 규칙 자체는 test_fees.py.
기대값은 손으로 계산한 값이다: 마크업 Gross = Net × (1 + r/100), 커미션 Gross = Net ÷ (1 − r/100), 옛 서버는 Gross = Net × cost ÷ cost_net.
성공하면 "ok"."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "shared", "assets"))

from test_fees import KEYS, OVERALL_TP, close, env, fee  # noqa: E402


def _builder(skill):
    path = os.path.join(PLUGIN, "skills", skill, "assets", "build_report.py")
    spec = importlib.util.spec_from_file_location(f"build_{skill.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


weekly, monthly, overall = _builder("weekly-report"), _builder("monthly-report"), _builder("overall-summary")


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


def prev_month_cost(target_date, basis, fee_list=WEEK_FEES["s3"]):
    """E = target_date. s1 9월 MTD(9/1~E의 일) 광고비 200, s3(일 × 매체)는 E-34부터. Meta 수수료 9월 마크업 10%·10월 20%."""
    s3 = [{"date": "2026-09-03", "media": "Meta", "cost": 100}, {"date": "2026-09-04", "media": "Naver", "cost": 100},
          {"date": "2026-09-20", "media": "Meta", "cost": 500}, {"date": "2026-10-02", "media": "Meta", "cost": 200},
          {"date": "2026-10-02", "media": "Naver", "cost": 100}]
    p = {"out": "unused.html", "title": "t", "target_date": target_date, "metric_keys": KEYS, "currency": "₩",
         "s1": {"json": json.dumps(env([{"month": "2026-09", "cost": 200}, {"month": "2026-10", "cost": 300}], [], grain="month")),
                "target_progress": NEW_TP},
         "s3": {"json": json.dumps(env(s3, ["media"], fee_list=fee_list))}}
    cards = {c["key"]: c for c in weekly.compute(p, check_dims=False, basis=basis)[0]["s1"]["cards"]}
    return cards["cost"]["sub"]


def test_weekly_previous_month_needs_covered_window():
    # E = 10/4: E-34 = 8/31이라 9월 1일~4일이 s3에 모두 있다 — 9월 실효 배수 (100×1.1 + 100) ÷ 200 = 1.05 → 210
    assert prev_month_cost("2026-10-04", "gross") == "전월 동기간 ₩210"
    # E = 10/7: E-34 = 9/3이라 9월 1~2일이 s3에 없다 — 9월에 Meta 수수료가 있으니 추정하지 않고 빈칸. 서버 기준 보기는 그대로 200
    assert prev_month_cost("2026-10-07", "gross") == "전월 동기간 -"
    assert prev_month_cost("2026-10-07", "net") == "전월 동기간 ₩200"
    assert prev_month_cost("2026-10-07", "gross", [fee("Meta", "2026-10", "markup", 20)]) == "전월 동기간 ₩200"


def test_weekly_week_across_months_uses_s3_effective_factor():
    fl = [fee("Meta", "2026-09", "markup", 10), fee("Meta", "2026-10", "markup", 20)]
    s3 = [{"date": "2026-09-28", "media": "Meta", "cost": 100, "impressions": 100},
          {"date": "2026-10-02", "media": "Meta", "cost": 600, "impressions": 300}]
    s4 = [{"media": "Meta", "cost": 700, "impressions": 400}]
    p = {"out": "unused.html", "title": "t", "target_date": "2026-10-03", "metric_keys": KEYS, "currency": "₩",
         "s3": {"json": json.dumps(env(s3, ["media"], fee_list=fl))},
         "s4": {"cur": {"json": json.dumps(env(s4, ["media"], fee_list=fl, grain="total"))}}}
    _, _, c = weekly.compute(p, check_dims=False, basis="gross")
    # s3 실효 배수로 환산 — 100 × 1.1 + 600 × 1.2 = 830 (일수 가중 (4 × 1.1 + 3 × 1.2) ÷ 7 × 700 = 800이 아니다)
    assert close(c["fine"]["cur"]["rows"][0]["cost"], 830), c["fine"]["cur"]["rows"]


def test_weekly_empty_fee_table_has_no_toggle():
    p = weekly_payload(new=True)
    p["s1"]["target_progress"] = NEW_TP.split("\n\n| media | fee_mode")[0]
    for sec in (p["s3"], p["s4"]["cur"], p["s4"]["base"], p["s1"]):
        sec["json"] = json.dumps(dict(json.loads(sec["json"]), fees=[]))
    assert weekly.fee_view(p) == (None, "net", {})


def test_weekly_mixed_old_and_new_responses_stop():
    p = weekly_payload(new=True)
    cur = p["s4"]["cur"]
    cur["json"] = json.dumps({k: v for k, v in json.loads(cur["json"]).items() if k != "fee_basis"})
    try:
        weekly.compute(p, check_dims=False, basis="net")
    except SystemExit as e:
        assert "수수료 기준" in str(e.code), e
        return
    raise AssertionError("s4 이번주만 fee_basis가 없으면 멈춰야 한다")


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
            flat = html.replace(" ", "")
            assert f'"default":"{default}"' in flat and f'"sections":{{"{alt}":{{"s1"' in flat, new
            # 다른 보기의 내용: 새 형식 Gross 10월 MTD 광고비 460(10/1~7 실효 배수 1.15 × 400), 옛 형식 Net 월예산 1,000(Gross 1,060 − 60)
            assert ("MTD광고비₩460" if new else "월예산₩1,000") in flat, new


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


OLD_MONTH_TP = """month: 2026-10
as_of_date: 2026-10-31
media: all

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 2900 | 2300 | 0.79 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 1100 | 1100 | 1 |
| Meta | - | - | cost_net | 1000 | - | - |
| Meta | A | Y | cost | 660 | 500 | 0.76 |
| Meta | A | Y | cost_net | 550 | - | - |
| Google | - | - | cost | 1000 | 800 | 0.8 |
| Google | C | Y | cost | 600 | 700 | 1 |
| Google | C | Y | cost_net | 500 | - | - |
| Naver | - | - | cost | 800 | 400 | 0.5 |"""


def old_monthly_payload():
    """옛 서버(fee_basis 없음). Meta 비율 1100/1000 = 1.1(캠페인 A만 660/550 = 1.2), Google은 매체 cost_net이 없고 캠페인 C 600/500 = 1.2, Naver 수수료 없음."""
    s6 = [("Meta", "A", 500), ("Meta", "B", 600), ("Google", "C", 700), ("Google", "D", 100), ("Naver", "N", 400)]
    s4 = [("Meta", 1100), ("Google", 800), ("Naver", 400)]
    return {"out": "unused.html", "title": "t", "month": "2026-10", "metric_keys": KEYS, "currency": "₩",
            "s1": {"json": json.dumps(env([{"month": "2026-10", "cost": 2300}], [], None, grain="month")), "target_progress": OLD_MONTH_TP},
            "s4": {"json": json.dumps(env([{"month": "2026-10", "media": m, "cost": v} for m, v in s4], ["media"], None, grain="month"))},
            "s6": {"json": json.dumps(env([{"month": "2026-10", "media": m, "campaign_name": c, "cost": v} for m, c, v in s6],
                                          ["media", "campaign_name"], None, grain="month"))}}


def test_monthly_old_server_gross_costs():
    p = old_monthly_payload()
    assert monthly.fee_view(p)[:2] == ("gross", None)
    _, _, _, c = monthly.compute(p, check_dims=False, basis="gross")
    oct6 = {r["campaign_name"]: r["cost"] for r in c["e6"]["rows"]}
    # 캠페인 A는 자기 비율 1.2(500 → 600), B는 Meta 비율 1.1(600 → 660), C는 1.2(700 → 840), D는 매체 비율 — 캠페인 합 600/500 = 1.2(100 → 120)
    assert close(oct6["A"], 600) and close(oct6["B"], 660) and close(oct6["C"], 840) and close(oct6["D"], 120) and oct6["N"] == 400, oct6
    cost4 = {k[0]: v["cost"] for k, v in c["i4"]["2026-10"].items()}
    assert close(cost4["Meta"], 1260) and close(cost4["Google"], 960) and cost4["Naver"] == 400, cost4   # 아래 표 Gross 합: 600 + 660, 840 + 120
    assert close(c["tot"]("2026-10")["cost"], 2620)   # 1260 + 960 + 400
    assert close(c["target_all"], 2900)   # 예산 = Gross 그대로


def test_monthly_old_server_net_budget():
    _, _, _, c = monthly.compute(old_monthly_payload(), check_dims=False, basis="net")
    assert close(c["tot"]("2026-10")["cost"], 2300)   # 광고비 실적은 항상 Net
    assert close(c["t_media"]["Meta"]["cost"], 1000) and close(c["t_camp"][("Meta", "A")]["cost"], 550)
    assert close(c["t_media"]["Google"]["cost"], 900)   # cost_net 없음: 1000 − 캠페인 C 수수료(600 − 500)
    assert close(c["t_media"]["Naver"]["cost"], 800)   # 수수료 없음
    assert close(c["target_all"], 2700)   # 2900 − 매체 수수료(Meta 100 + Google 100)


OLD_OVERALL_TP = """month: 2026-10
as_of_date: 2026-10-05
media: all

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 2900 | 2300 | 0.79 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 1100 | 1100 | 1 |
| Meta | - | - | cost_net | 1000 | - | - |
| Meta | A | Y | cost | 660 | 500 | 0.76 |
| Meta | A | Y | cost_net | 550 | - | - |
| Google | - | - | cost | 1000 | 800 | 0.8 |
| Google | C | Y | cost | 600 | 700 | 1 |
| Google | C | Y | cost_net | 500 | - | - |
| Naver | - | - | cost | 800 | 400 | 0.5 |"""


def test_overall_old_server_gross_rows_net_budgets_and_placement():
    """옛 서버. Meta 비율 1.1(캠페인 A만 1.2), Google은 매체 cost_net이 없고 캠페인 C 600/500 = 1.2, Naver 수수료 없음."""
    data = [("Meta", "A", 500), ("Meta", "B", 600), ("Google", "C", 700), ("Google", "D", 100), ("Naver", "N", 400)]
    rows = [{"date": "2026-10-01", "media": m, "campaign_name": c, "cost": v, "impressions": 100} for m, c, v in data]
    prow = [{"date": "2026-10-01", "media": m, "placement": "feed", "cost": v, "impressions": 100}
            for m, v in (("Meta", 1100), ("Google", 800), ("Naver", 400))]
    p = {"out": "unused.html", "brand": "b", "target_date": "2026-10-05", "start_date": "2026-10-01", "metric_keys": KEYS,
         "currency": "₩", "dims": "valid dimensions: ['date', 'media', 'campaign_name']",
         "data": {"json": json.dumps(env(rows, ["media", "campaign_name"], None))},
         "place": {"json": json.dumps(env(prow, ["media", "placement"], None))},
         "budgets": [{"month": "2026-10", "target_progress": OLD_OVERALL_TP}]}
    report, out = overall.compute(p)
    g = {r["c"]: r["cost_g"] for r in out}
    # A 500 × 1.2, B 600 × Meta 1.1, C 700 × 1.2, D 100 × Google(캠페인 합 600/500) 1.2, N 400 × 1
    assert [round(g[c], 6) for c in "ABCDN"] == [600, 660, 840, 120, 400], g
    gross = {tuple(sorted(b["scope"].items())): b["v"]["cost"] for b in report["table"]["budgets"]}
    net = {tuple(sorted(b["scope"].items())): b["v"]["cost"] for b in report["table"]["budgets_net"]}
    assert gross[()] == 2900 and gross[(("m", "Google"),)] == 1000
    assert close(net[(("m", "Meta"),)], 1000) and close(net[(("c", "A"), ("m", "Meta"))], 550) and close(net[(("m", "Naver"),)], 800)
    assert close(net[(("m", "Google"),)], 900)   # cost_net 없음: 1000 − 캠페인 C 수수료(600 − 500)
    assert close(net[()], 2700)   # cost_net 없음: 2900 − 매체 수수료(Meta 100 + Google 100 + Naver 0)
    # Placement는 본 표의 (달, 매체) 실효 비율을 쓴다 — Meta (600 + 660) ÷ (500 + 600), Google (840 + 120) ÷ 800, Naver 1
    pl = report["place"]
    cg = {pl["dict"]["m"][i]: v for i, v in zip(pl["cols"]["m"], pl["cols"]["cost_g"])}
    assert close(cg["Meta"], 1260) and close(cg["Google"], 960) and close(cg["Naver"], 400), cg


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

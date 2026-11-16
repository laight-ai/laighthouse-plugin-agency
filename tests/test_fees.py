#!/usr/bin/env python3
"""광고비·예산 Gross / Net 규칙(shared/assets/fees.py·report_kit.merged_envelope) 자체 검사(표준 라이브러리만). 빌더 연결은 test_fee_builders.py.
기대값은 손으로 계산한 값이다: 마크업 Gross = Net × (1 + r/100), 커미션 Gross = Net ÷ (1 − r/100). 성공하면 "ok"."""

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
sys.path.insert(0, os.path.join(PLUGIN, "shared", "assets"))

import fees  # noqa: E402
import report_kit as kit  # noqa: E402

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


def test_served_ui_titles_per_option():
    for served, other in (("net", "gross"), ("gross", "net")):
        ui = fees.served_ui(served)
        assert ui["default"] == served and [o["key"] for o in ui["options"]] == ["gross", "net"], ui
        title = {o["key"]: o["title"] for o in ui["options"]}
        assert "브랜드 설정" in title[served] and "서버 값 그대로" in title[served] and "환산" not in title[served], title
        assert "환산" in title[other] and "브랜드 설정" not in title[other] and "서버 값 그대로" not in title[other], title


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
    for rate in (100, 120):
        try:
            fees.fee_table([env([], ["media"], fee_list=[fee("Google", "2026-10", "commission", rate)])])
        except SystemExit as e:
            assert "Google" in str(e) and "100%" in str(e), e
            continue
        raise AssertionError("커미션율이 100% 이상이면 멈춰야 한다")


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
    net = by_scope(fees.convert_budgets(budgets, table, "gross", "net", budget_targets.derive_targets))
    assert close(net[scope()]["cost"], 3100)   # 1000 + 1600 + 500
    assert close(net[scope(m="Meta")]["cost"], 1000) and close(net[scope(m="Meta")]["cpm"], 5000)
    assert close(net[scope(m="Meta")]["imp"], 200)   # 노출 = 예산 ÷ CPM × 1000 — 기준이 바뀌어도 같다
    assert close(net[scope(m="Meta", c="A")]["cost"], 400) and close(net[scope(m="Google")]["cost"], 1600)
    rows = [{"day": date(2026, 10, 1), "m": "Meta", "cost": 1000}, {"day": date(2026, 10, 1), "m": "Google", "cost": 400},
            {"day": date(2026, 10, 1), "m": "Naver", "cost": 400}]
    fees.add_cost_views(rows, table, "net")   # 서버 기준 Net — Gross는 1000 × 1.1, 400 ÷ 0.8, 수수료 없음 그대로
    assert [(r["cost"], r["cost_g"]) for r in rows] == [(1000, 1100), (400, 500), (400, 400)]


def by_scope(budgets):
    return {tuple(sorted(b["scope"].items())): b["v"] for b in budgets}


def scope(**sc):
    return tuple(sorted(sc.items()))


NET_SERVED_TP = """month: 2026-10
as_of_date: 2026-10-20
media: all
fee_basis: net

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 3100 | 1500 | 0.5 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Meta | - | - | cost | 1000 | 500 | 0.5 |
| Meta | - | - | cpm | 5000 | 4800 | 0.96 |
| Meta | A | Y | cost | 400 | 200 | 0.5 |
| Google | - | - | cost | 1600 | 600 | 0.4 |
| Naver | - | - | cost | 500 | 400 | 0.8 |
| Kakao | K1 | Y | cost | 300 | 100 | 0.3 |

| media | fee_mode | rate |
| --- | --- | --- |
| Meta | markup | 10 |
| Google | commission | 20 |
| Kakao | markup | 25 |"""


def test_convert_budgets_net_to_gross():
    """서버 기준 Net → Gross. Meta 마크업 10%, Google 커미션 20%, Kakao 마크업 25%(캠페인 목표만 있는 매체), Naver 수수료 없음."""
    budgets = budget_targets.parse_budget({"month": "2026-10", "target_progress": NET_SERVED_TP})
    table = fees.fee_table([], [NET_SERVED_TP])
    gross = by_scope(fees.convert_budgets(budgets, table, "net", "gross", budget_targets.derive_targets))
    assert close(gross[scope(m="Meta")]["cost"], 1100) and close(gross[scope(m="Meta")]["cpm"], 5500)   # 1000 × 1.1, 5000 × 1.1
    assert close(gross[scope(m="Meta")]["imp"], 200)   # 노출 = 예산 ÷ CPM × 1000 — 기준이 바뀌어도 같다
    assert close(gross[scope(m="Google")]["cost"], 2000) and close(gross[scope(m="Naver")]["cost"], 500)   # 1600 ÷ 0.8, 수수료 없음
    assert close(gross[scope(m="Meta", c="A")]["cost"], 440)   # 캠페인은 그 매체 수수료: 400 × 1.1
    assert close(gross[scope(m="Kakao", c="K1")]["cost"], 375)   # 매체 행이 없어도 그 매체 수수료: 300 × 1.25
    assert close(gross[scope()]["cost"], 3600)   # 1100 + 2000 + 500 — 매체 행 합만. 캠페인 목표만 있는 Kakao는 합계에 들어가지 않는다


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

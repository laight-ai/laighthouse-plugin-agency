"""검색량 데이터 품질.

품질 정보(키워드별 데이터 상태, 쓴 요청, 키워드도구 눈금 대조)는 JSON `quality`와 모델용 데이터
상태에만 들어가고 보고서에는 싣지 않는다.

- 결측일은 최근 HISTORY_DAYS일 중 데이터가 시작된 날 이후만 센다(나중에 추가된 키워드는 그 키워드의
  데이터 시작일부터).
- 눈금 대조 창은 앵커의 최신(PC·모바일 모두 있는) 키워드도구 스냅샷 날짜에서 `window_lag_days`를 뺀
  날까지 30일이다. 수집기의 앵커 눈금 계산과 같은 기준이다. 키워드마다 그 날짜 이하의 최신 스냅샷
  값을 쓰고, PC·모바일 한쪽만 10 미만(NULL)이면 그쪽을 0으로 보며, 둘 다 없을 때만 값이 없다.
"""

from __future__ import annotations

from datetime import date, timedelta


VOLUME_WINDOW_DAYS = 30
HISTORY_DAYS = 395


def tool_total(pc: int | None, mo: int | None) -> int | None:
    """키워드도구 PC+모바일. 한쪽만 10 미만(None)이면 0으로 더하고 둘 다 없으면 None."""
    if pc is None and mo is None:
        return None
    return (pc or 0) + (mo or 0)


def calibration(
    est: dict[str, float], tool: dict[str, int | None], brands: list[tuple[str, list[str]]]
) -> list[dict]:
    """브랜드별 추정 30일 합 vs 키워드도구 30일 합. 키워드도구 값이 없는 키워드는 양쪽에서 뺀다."""
    out = []
    for name, keywords in brands:
        used = [k for k in keywords if tool.get(k) is not None]
        e = round(sum(est.get(k, 0.0) for k in used))
        t = sum(tool[k] for k in used)
        out.append(
            {
                "brand": name,
                "keywords": len(used),
                "est30": e if used else None,
                "tool30": t if used else None,
                "diff_pct": round(100.0 * (e / t - 1), 1) if used and t else None,
            }
        )
    return out


def keyword_rows(
    kw_by_brand: dict[str, list[str]],
    coverage: dict[str, int],
    firsts: dict[str, date],
    tool: dict[str, int | None],
    hist_start: date,
    target: date,
) -> list[dict]:
    history_days = (target - hist_start).days + 1
    out = []
    for name, keywords in kw_by_brand.items():
        for k in keywords:
            n = coverage.get(k, 0)
            k_start = max(hist_start, firsts.get(k, hist_start))
            missing = (target - k_start).days + 1 - n if n else history_days
            if n == 0:
                status = "데이터 없음(검색량 적음)"
            else:
                status = "결측일 있음" if missing else "정상"
            out.append(
                {
                    "keyword": k,
                    "brand": name,
                    "days_with_data": n,
                    "missing_days": missing,
                    "status": status,
                    "tool30": tool.get(k),
                }
            )
    return out


def quality(
    db,
    kw_by_brand: dict[str, list[str]],
    target: date,
    last_period: date | None,
    rows: list[tuple],
    days: list[date],
    counts: dict[str, list[int | None]],
) -> dict:
    keywords = list(dict.fromkeys(k for ks in kw_by_brand.values() for k in ks))
    firsts = db.first_periods(keywords)
    hist_start = max(
        target - timedelta(days=HISTORY_DAYS - 1), min(firsts.values(), default=target)
    )
    cfg = db.cfg
    snapshot_date, tool = db.snapshot(keywords, cfg["anchor_keyword"])
    calib, calib_window = [], None
    if snapshot_date:
        win_end = snapshot_date - timedelta(days=cfg["window_lag_days"])
        win_start = win_end - timedelta(days=VOLUME_WINDOW_DAYS - 1)
        calib_window = {"start": win_start.isoformat(), "end": win_end.isoformat()}
        est30 = db.window_sum(keywords, win_start, win_end)
        calib = calibration(est30, tool, list(kw_by_brand.items()))
    coverage = db.coverage(keywords, hist_start, target)
    kw_rows = keyword_rows(kw_by_brand, coverage, firsts, tool, hist_start, target)
    warnings = []
    if last_period and last_period < target:
        warnings.append(
            f"마지막 검색량 데이터가 {last_period}입니다(범위 끝 {target} 값 없음). "
            "수집기가 아직 그 날 값을 받지 않았습니다."
        )
    if none_kw := [x["keyword"] for x in kw_rows if x["days_with_data"] == 0]:
        warnings.append(
            f"검색량이 적어 데이터가 없는 키워드: {', '.join(none_kw)} (브랜드 합에 0으로 들어감)."
        )
    if not snapshot_date:
        warnings.append("키워드도구 스냅샷이 없어 눈금 대조를 하지 못했습니다.")
    request_ids = sorted({int(x[3]) for x in rows})
    return {
        "warnings": warnings,
        "source": "search_volume_daily(앵커 눈금)",
        "last_period": last_period.isoformat() if last_period else None,
        "requests": db.requests(request_ids) if request_ids else [],
        "missing_dates": [
            d.isoformat()
            for i, d in enumerate(days)
            if any(v[i] is None for v in counts.values())
        ],
        "keywords": kw_rows,
        "snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
        "calibration_window": calib_window,
        "calibration": calib,
        "history_days": (target - hist_start).days + 1,
    }

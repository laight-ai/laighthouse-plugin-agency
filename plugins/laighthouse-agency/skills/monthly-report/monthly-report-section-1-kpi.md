# section-1: 월간 성과 요약

## MCP 호출 (2개, 같은 배치)

- `get_ad_performance` — `time_grain:"month"`, `group_by` 생략, M-5 1일 ~ M0 말일, `metrics`·`filters` 생략.
  같은 응답을 section-3(월별 광고 성과)과 section-5·6의 **전체** 행이 쓴다.
- `get_target_progress_v2` — `{"brand_name", "month": "<M0>", "as_of_date": "<M0 말일>", "cost_metric": "<metric_keys.cost>"}`
  (`media` 생략 = 전체 매체). markdown 표 또는 한 줄 "No all budget/target available…" 메시지가 온다.

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s1": {"json": "<get_ad_performance 응답 원문>", "target_progress": "<get_target_progress_v2 응답 원문 그대로>"}
```

## 빌더가 하는 일

- **예산 소진율 카드**: 표의 `cost` 행 target(월 예산)과 M0 광고비(get_ad_performance 값 — 목표 도구의
  `actual` 열은 쓰지 않는다)로 소진율·진행 바·"월 예산 ₩…"을 만든다. 목표가 없거나 0이면 `N/A`.
- **고정 7 KPI 카드**: M0 값, 전월(M-1) 대비 증감(% 지표는 %p), 보조 줄에 전월 값.
- 예산 소진율 + 7 KPI가 기본이고, 그 밖의 서빙 지표(VTR 등)도 같은 모양의 전월 대비 카드로 만들어 두어 카드 위 "지표" 메뉴에서
  더하고 빼고 순서를 바꾼다(초기화로 기본 카드, 메뉴에서 바꾼 상태만 그 브라우저에 기억).

# section-3: 매체별 일별 추이 (최근 7일)

## MCP 호출

`get_ad_performance` ×1 — `time_grain:"day"`, `group_by:["media"]`, `start_date` = D0-6일, `end_date` = D0,
`metrics`·`filters` 생략.

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s3": {"json": "<응답 원문 문자열 그대로>"}
```

## 빌더가 하는 일

- 매체마다 라인 1개(응답 등장 순서, 기존 분류형 팔레트). 주말(토·일)은 회색 배경.
- 지표 탭 = 응답 `metrics` 전부(서빙 순서). 기본 탭은 광고비. 비율 지표도 서버 값 그대로 그린다.
- 축·툴팁 단위는 `metric_units`를 따른다.

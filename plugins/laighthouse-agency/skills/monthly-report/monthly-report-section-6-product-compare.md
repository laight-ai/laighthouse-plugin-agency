# section-6: 예산 및 목표 달성 결과 (목표 달성 표)

Dimension·지표 메뉴·검색·페이지 규칙은 `shared/references/pivot-table.md`(이 스킬 폴더에서는 `../../shared/references/`)가 단일 소스다.

## MCP 호출

- `get_ad_performance` ×1 — `time_grain:"month"`, `group_by` = FINE_DIMS(차원 확인 결과), M-1 1일 ~ M0 말일, `metrics`·`filters` 생략.
  (M0만 쓴다. M-1은 예전 입력과의 호환을 위해 그대로 받아도 된다.)
- `get_target_progress_v2` × `media_list` 각 매체 — `month` = M0, `media` = 그 매체, `as_of_date` = M0 말일, `cost_metric` = `metric_keys.cost`.
  브랜드 전체 목표는 s1의 `target_progress`(media 생략)를 쓴다.

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s6": {"json_files": ["<응답 파일>"], "targets": {"<매체>": "<get_target_progress_v2 응답 원문>"}}
```

## 화면

- 기본 Dimension = 매체 → 상품, 기본 지표 = 광고비 하나(맨 앞 고정, 사용자가 지표 메뉴에서 늘린다).
- 열 = 지표마다 3열: 광고비 [월 예산, 집행액, 소진율(막대)], 합산 지표 [월 목표, 실적, 달성률(막대)], 비율 지표 [목표, 실적, 목표 대비(%)].
- 목표는 브랜드 전체·매체 단위만 있다. 목표가 없는 지표·단위(상품·캠페인 행 등)는 **묻지 않고 "-"**로 둔다.
- 색: 광고비 소진율이 100% ± 10%p를 벗어나면 빨강(초과)·주황(미소진). 그 외 합산 지표는 100% 이상 초록·90% 이상 주황·미만 빨강.
  비율 지표는 CTR 등 높을수록, CPM·CPV는 낮을수록 좋음 — 달성 초록, 미달 빨강.
- 첫 Dimension이 매체이고 Dimension이 둘 이상이면 매체마다 "{매체} 소계" 행(매체 목표 대비). 맨 아래 전체 행 = s1 서버 총계(검색 시 검색된 행의 합계).
- 매체부터 광고비 순으로 정렬하고 같은 상위 값은 감춘다. 10개씩 페이지(소계 행 포함).

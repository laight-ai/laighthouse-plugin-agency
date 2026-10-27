# section-1: 월간 성과 요약 (월 누적 · 목표 대비 진척도)

## MCP 호출

- `get_ad_performance` ×1 — `time_grain:"month"`, `group_by` 생략, `day_offset` = E의 일, `start_date` = E의 전월 1일,
  `end_date` = E. 응답에 당월(1일~E)·전월 동기간 두 행이 온다.
- `get_target_progress_v2` ×1 — `month` = E의 달, `media` 생략, `as_of_date` = E, `cost_metric` = `metric_keys.cost`.

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s1": {"json_files": ["<month 응답 파일>"], "target_progress": "<get_target_progress_v2 응답 원문>"}
```

## 빌더가 하는 일 (모델은 계산하지 않는다)

- **예산 소진율** = 월 누적 광고비 ÷ 월 예산(목표 표 `cost` 행). 막대 + 기간 진행률 세로선(E의 일 ÷ 그 달 일수).
  예산이 없으면 이 카드 대신 **광고비** 카드(전월 동기간 대비)가 나온다.
- 노출·클릭·CTR·조회수·CPM·CPV 카드:
  - 목표 표에 그 지표 행이 있으면 **목표 대비 카드** — 노출·클릭·조회수는 월 목표 대비 누적 달성률(진행률 대비 %p,
    예상 월마감, 태그 달성 예상 / 주의 / 미달 예상), CTR은 높을수록, CPM·CPV는 낮을수록 좋은 지표로 목표 달성/미달.
  - 행이 없으면(현재 서버) **전월 동기간 대비** 카드. 아무것도 묻지 않고 조용히 바뀐다.

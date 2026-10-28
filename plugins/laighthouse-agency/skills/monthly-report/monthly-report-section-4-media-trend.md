# section-4: 매체별 성과 추이 (최근 6개월)

## MCP 호출

`get_ad_performance` ×1 — `time_grain:"month"`, `group_by:["media"]`, M-5 1일 ~ M0 말일, `metrics`·`filters` 생략.
같은 응답을 section-5(매체 성과 비교)와 section-6의 매체 **소계** 행이 쓴다.

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s4": {"json": "<응답 원문 문자열 그대로>"}
```

## 빌더가 하는 일

- 매체마다 라인 1개, 지표 드롭다운 = 응답 `metrics` 전부, 범례를 누르면 매체를 끄고 켠다.
- 범례 값 = M0 값. **합산 가능한 지표**(전체 응답 값 = 매체 값 합인 지표 — 빌더가 판정)에만 비중 %를 붙인다.

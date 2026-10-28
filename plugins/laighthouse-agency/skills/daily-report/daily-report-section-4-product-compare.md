# section-4: 성과 비교 (피벗 표)

규칙·호출·입력 형식은 `shared/references/pivot-table.md`(이 스킬 폴더에서는 `../../shared/references/`)가 단일 소스다.

## MCP 호출

**1회** — `time_grain:"day"`, `start_date` = D7, `end_date` = D0, `group_by` = FINE_DIMS(차원 확인 결과), `metrics`·`filters` 생략.
빌더가 기준일(D0)·전일(D1)·전주 동요일(D7) 행만 쓴다(하루치 행 값 = 그날만 따로 조회한 값).

## 빌더 입력 (`assets/prepare.py`가 채운다 — 저장 훅이 없을 때만 직접 만든다)

```json
"s4": {"json_files": ["<D7~D0 응답 파일>"]}
```

## 화면

- Dimension·지표 드롭다운 표(`shared/references/pivot-table.md`). 기본 Dimension = 매체 → 상품(상품 차원이 없으면 매체 → 캠페인), 기본 지표 = 광고비 하나(맨 앞 고정, 사용자가 지표 메뉴에서 늘린다).
  Dimension 메뉴에서 캠페인·광고그룹·광고를 더하고 빼고 순서를 바꾼다. 검색은 표 오른쪽 위 `[검색 기준 | 차원 ▾ | 검색어]` 한 덩어리 — 기본 차원 = 캠페인(있을 때).
- 열 = 지표마다 [비교일, 기준일] 2열 + 증감. 비교일은 상단 "비교 기준" 토글(전일/전주 동요일)을 따른다.
- 기준일 광고비 순, 10개씩 페이지. 전체 행 = s1 서버 총계(검색 시 검색된 행의 합계). 빌더가 표의 매체별 합을 s3과 대조 검증한다.

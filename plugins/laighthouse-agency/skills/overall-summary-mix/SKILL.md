---
name: overall-summary-mix
description: >
  종합 리포트의 Mix 계획표만 뽑는 스킬. "종합 리포트 mix", "Mix 계획표", "overall summary mix", "예상 성과 계획표" 요청 시 사용. 캠페인 목표(예산·CPM·CPC·VTR)를 초기값으로 월 예산·단가를 입력하면 예상 노출·클릭·조회가 다시 계산되는 Mix 표만 담은 HTML과 Mix 시트 엑셀(수식 포함)을 만든다.
  사용자가 말한 브랜드의 차원·지표를 실행 시작에 디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.0.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

종합 리포트(`overall-summary`)에서 **Mix 계획표만** 뽑아 HTML 한 파일과 Mix 시트만 담은 엑셀(.xlsx — 값을 고치면 수식으로 다시 계산)을 만든다.
스크립트·규칙·데이터 처리 원칙은 `overall-summary`와 같다 — **`../overall-summary/SKILL.md`를 먼저 읽고 그대로 따른다.**
이 문서는 거기서 달라지는 점만 적는다. 스크립트는 `../overall-summary/assets/`에 있다(이 스킬 폴더 기준).

- 파라미터(브랜드명·기준일 E = 데이터 마지막 날, 기본 어제·오늘 이후 불가·시작일 S)와 기간 계산(S 기본 = E의 전월 1일, 366일까지)은 `overall-summary`와 같다.
- 섹션 규칙: `../overall-summary/overall-summary-section-4-mix.md`

## 실행 순서 (`overall-summary` 「실행 순서」에서 달라지는 점)

1. 파라미터 파싱 — 같다.
2. 차원 확인 + 매체별 일별 (한 메시지에 동시 2회) — 같다.
3. 데이터 호출 (한 메시지에 동시 발사):
   - 표 데이터: `time_grain:"day"`, `group_by` = FINE_DIMS — 달마다 1회(크기 오류 대응도 같다).
   - 예산·목표: `get_target_progress_v2` — 걸친 달마다 `media` 생략 1회(인자는 같다). Mix의 월 예산·단가 초기값이다.
   - Placement는 부르지 않는다(Mix에 쓰지 않는다).
4. 빌드 (1회) — `--part mix`를 붙인다:
   ```
   python3 ../overall-summary/assets/prepare.py --brand <브랜드> --target-date <E> [--start-date <S>] --part mix --build <<'PYEOF'
   <차원 확인 에러 메시지 원문>
   PYEOF
   ```
   `missing`·`errors`·`build_error` 처리는 `overall-summary`와 같다.
   HTML은 `~/Downloads/laighthouse-reports/{브랜드명}_overall_summary_mix_{기준_일자}.html`, 엑셀은 같은 폴더·같은 이름의 `.xlsx`(Mix 시트).
5. 완성된 HTML을 낸다(Artifact 등으로 보여 줄 수 있으면 게시). 엑셀은 경로만 알린다.
6. 완료 메시지는 아래 형식 그대로.

## 완료 메시지 형식

```
{브랜드명} 종합 리포트 Mix({기준_일자}) 생성 완료.
엑셀: {xlsx 경로} (Mix)
가장 인상적인 부분: {예산이 큰 매체·캠페인의 예상 성과에서 고른 한 문장}.
— by LaightAI
```

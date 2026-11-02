---
name: overall-summary-comment
description: >
  종합 리포트의 Comment만 뽑는 스킬. "종합 리포트 코멘트", "Daily/Weekly Comment만", "overall summary comment" 요청 시 사용. 전일 대비 급감 광고그룹을 짚는 Daily Comment와 소진·효율 관점의 Weekly Comment(빌더가 규칙으로 작성)만 담은 HTML을 만든다(엑셀 없음).
  사용자가 말한 브랜드의 차원·지표를 실행 시작에 디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.0.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

종합 리포트(`overall-summary`)에서 **Daily Comment · Weekly Comment만** 뽑아 HTML 한 파일로 만든다. 엑셀은 만들지 않는다.
스크립트·규칙·데이터 처리 원칙은 `overall-summary`와 같다 — **`../overall-summary/SKILL.md`를 먼저 읽고 그대로 따른다.**
이 문서는 거기서 달라지는 점만 적는다. 스크립트는 `../overall-summary/assets/`에 있다(이 스킬 폴더 기준).

- 파라미터(브랜드명·기준일 E = 데이터 마지막 날, 기본 어제·오늘 이후 불가·시작일 S)와 기간 계산(S 기본 = E의 전월 1일, 366일까지)은 `overall-summary`와 같다.
- 섹션 규칙: `../overall-summary/overall-summary-section-1-comment.md`

## 실행 순서 (`overall-summary` 「실행 순서」에서 달라지는 점)

1. 파라미터 파싱 — 같다.
2. 차원 확인 + 매체별 일별 (한 메시지에 동시 2회) — 같다.
3. 데이터 호출 (한 메시지에 동시 발사):
   - 표 데이터: `time_grain:"day"`, `group_by` = FINE_DIMS — 달마다 1회(크기 오류 대응도 같다).
   - 예산·목표: `get_target_progress_v2` — 걸친 달마다 `media` 생략 1회(인자는 같다).
   - Placement는 부르지 않는다(Comment에 쓰지 않는다).
   - 변경 이력(`list_campaign_change_raw`)과 이름 호출은 부르지 않는다(Comment에 쓰지 않는다).
4. 빌드 (1회) — `--part comment`를 붙인다:
   ```
   python3 ../overall-summary/assets/prepare.py --brand <브랜드> --target-date <E> [--start-date <S>] --part comment --build <<'PYEOF'
   <차원 확인 에러 메시지 원문>
   PYEOF
   ```
   `missing`·`errors`·`build_error` 처리는 `overall-summary`와 같다.
   HTML은 `~/Downloads/laighthouse-reports/{브랜드명}_overall_summary_comment_{기준_일자}.html`이다(엑셀 없음 — 출력의 `xlsx_note`가 그 이유다).
5. 완성된 HTML을 낸다(Artifact 등으로 보여 줄 수 있으면 게시).
6. 완료 메시지는 아래 형식 그대로.

## 완료 메시지 형식

```
{브랜드명} 종합 리포트 Comment({기준_일자}) 생성 완료.
가장 인상적인 부분: {Daily/Weekly Comment에서 고른 한 문장}.
— by LaightAI
```

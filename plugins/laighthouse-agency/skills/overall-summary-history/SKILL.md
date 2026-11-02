---
name: overall-summary-history
description: >
  종합 리포트의 Campaign History(캠페인 변경 이력)만 뽑는 스킬. "종합 리포트 history", "변경 이력", "캠페인 변경 히스토리", "overall summary history" 요청 시 사용. 매체(Google·Meta·TikTok·네이버·카카오)가 남긴 캠페인·광고그룹·광고 변경 기록을 일 · 미디어 · 단계 · 대상 · 변경 사항(ON/OFF·예산 증액/감액·소재·타겟팅 등) · 상세 표로 정리한 HTML과 History 시트 엑셀을 만든다.
  사용자가 말한 브랜드의 차원을 실행 시작에 디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.0.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

종합 리포트(`overall-summary`)에서 **Campaign History만** 뽑아 HTML 한 파일과 History 시트만 담은 엑셀(.xlsx)을 만든다.
스크립트·규칙·데이터 처리 원칙은 `overall-summary`와 같다 — **`../overall-summary/SKILL.md`를 먼저 읽고 그대로 따른다.**
이 문서는 거기서 달라지는 점만 적는다. 스크립트는 `../overall-summary/assets/`에 있다(이 스킬 폴더 기준).

- 파라미터(브랜드명·기준일 E = 데이터 마지막 날, 기본 어제·오늘 이후 불가·시작일 S)와 기간 계산(S 기본 = E의 전월 1일, 366일까지)은 `overall-summary`와 같다.
- 섹션 규칙: `../overall-summary/overall-summary-section-4-history.md`
- 줄은 빌더가 규칙으로 만든다 — 변경 이력 원본을 읽거나 옮겨 적지 않는다.

## 실행 순서 (`overall-summary` 「실행 순서」에서 달라지는 점)

1. 파라미터 파싱 — 같다.
2. 차원 확인만 1회(`get_ad_performance`, `group_by:["__list_dimensions__"]`) — 매체별 일별은 부르지 않는다(성과 수치를 쓰지 않는다).
   광고비 지표 키는 차원 확인 다음 호출(이름)에서 쓴다 — 모르면 `metrics`를 생략한다.
3. 데이터 호출 (한 메시지에 동시 발사):
   - 변경 이력: `list_campaign_change_raw`(`date_from` = S, `date_to` = E, `limit` = 1000,
     `streams` = `["change_event","activities","changelog","campaigns","campaign_detail","adgroups","ad_groups","ad_group_detail"]`).
     안내에 `next_cursor`가 있으면 같은 인자에 `cursor`만 바꿔 `null`이 될 때까지 이어 부른다.
   - 이름: 차원 목록에 `*_id`가 있을 때만 `get_ad_performance`(S ~ E, `time_grain:"total"`, `group_by` = `source`·`media` + 목록에 있는
     `campaign_id`·`campaign_name`·`ad_group_id`·`ad_group_name`·`ad_id`·`ad_name`) 1회. 크기 오류면 `ad_id`·`ad_name`을 빼고 다시 받는다.
   - 표 데이터·Placement·예산·목표는 부르지 않는다(History에 쓰지 않는다).
4. 빌드 (1회) — `--part history`를 붙인다:
   ```
   python3 ../overall-summary/assets/prepare.py --brand <브랜드> --target-date <E> [--start-date <S>] --part history --build <<'PYEOF'
   <차원 확인 에러 메시지 원문>
   PYEOF
   ```
   `missing`·`errors`·`build_error` 처리는 `overall-summary`와 같다(변경 이력 `missing`에 `cursor`가 있으면 그 페이지부터 이어 부른다).
   HTML은 `~/Downloads/laighthouse-reports/{브랜드명}_overall_summary_history_{기준_일자}.html`, 엑셀은 같은 폴더·같은 이름의 `.xlsx`(History 시트).
5. 완성된 HTML을 낸다(Artifact 등으로 보여 줄 수 있으면 게시). 엑셀은 경로만 알린다.
6. 완료 메시지는 아래 형식 그대로.

## 완료 메시지 형식

```
{브랜드명} 종합 리포트 History({기준_일자}) 생성 완료.
엑셀: {xlsx 경로} (History)
가장 인상적인 부분: {변경이 몰린 날·매체나 큰 예산 변경에서 고른 한 문장}.
— by LaightAI
```

변경 이력이 없으면 `가장 인상적인 부분:` 줄 대신 `집계 기간에 캠페인 변경 이력이 없습니다.`를 적는다.

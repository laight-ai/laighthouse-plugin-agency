# section-4: Campaign History (캠페인 변경 이력)

`list_campaign_change_raw`(변경 이력 원본) + 이름 호출 1회. **빌더가 규칙으로 줄을 만든다**(`assets/campaign_history.py`) —
모델은 원본을 읽거나 문장을 쓰지 않는다. **필터 미적용**(집계 기간 S~E 전체).

## 호출

- 변경 이력: `list_campaign_change_raw`(`date_from` = S, `date_to` = E, `limit` = 1000,
  `streams` = `["change_event","activities","changelog","campaigns","campaign_detail","adgroups","ad_groups","ad_group_detail"]`, `sources` 생략).
  응답 안내에 `next_cursor`가 있으면 **같은 인자에 `cursor`만 바꿔** 다시 부른다 — `next_cursor: null`이 나올 때까지(페이지는 차례로 부른다).
  스냅샷 매체(네이버·카카오)의 광고·소재 목록(`ads`·`creatives`)은 행이 아주 많아 받지 않는다.
- 이름: `get_ad_performance`(S~E, `time_grain:"total"`, `group_by` = `source`·`media`와 차원 목록에 있는
  `campaign_id`·`campaign_name`·`ad_group_id`·`ad_group_name`·`ad_id`·`ad_name`, `metrics` = [광고비 지표 키 하나]).
  변경 이력 원본에 이름이 없는 대상(TikTok·Google)을 ID로 찾는다. 크기 오류면 `ad_id`·`ad_name`을 빼고 다시 받는다.
  차원 목록에 `*_id`가 없는 브랜드는 부르지 않는다.

## 줄 만들기 (매체별 규칙)

| 매체 | 원본 | 규칙 |
|---|---|---|
| Google | `change_event` 로그 | 리소스 종류 → 단계(캠페인·광고그룹·광고·소재), CREATE = 생성(소재는 추가), REMOVE = 삭제, UPDATE는 바뀐 필드로: status → ON/OFF, 예산(amountMicros) → 증액/감액, 입찰·일정·이름·타겟팅(criterion) |
| Meta | `activities` 로그 | object_type → 단계(CAMPAIGN_GROUP = 캠페인, CAMPAIGN = 광고그룹, ADGROUP = 광고), event_type으로 상태·예산·입찰·타겟팅·소재·이름·생성·삭제·일정. 시각은 KST로 바꾼다 |
| TikTok | `changelog` 로그 | log_object_type → 단계, Activity details의 항목마다: On/Off → ON/OFF, Budget → 증액/감액, Creative → 소재 ON/OFF, Name → 이름 변경, Create → 생성 |
| 네이버·카카오 | 날마다 받은 캠페인·광고그룹 목록 | 같은 대상의 연속한 두 날 값 비교: 상태(userLock·config·status) → ON/OFF, 예산·입찰·이름·일정. 첫날 다음에 처음 나온 대상 = 생성(첫날은 기준이라 변경을 알 수 없다) |

- **빼는 기록**: 매체가 스스로 남긴 기록(TikTok 검수 상태·Platform-generated, Meta 시스템 작업자의 자동 타겟 등)과 계정 설정(사용자 권한 등).
  뺀 수는 섹션 머리에 `… N건 제외`로 적는다.
- **묶기**: 같은 날·같은 미디어·같은 대상·같은 변경은 한 줄(`×N`), 상세는 앞 3개 + `외 N건`. 소재는 같은 날·같은 변경을 한 줄로 묶고
  대상 칸에 `소재 N개`, 상세에 소재 이름을 적는다.
- **대상 이름**: 원본 이름(Meta object_name·Google 소재 이름) → 이름 호출의 ID → TikTok 이름 변경 로그의 새 이름 → 없으면 `ID 123…`.
- **미디어 이름**: 이름 호출의 `source → media`(성과 표와 같은 이름), 없으면 Google·Meta·TikTok·Naver Search Ads·Kakao Moment·Kakao Keyword.

## 화면 · 엑셀

- 표: 일 · 미디어 · 단계 · 대상 · 변경 사항 · 상세, 날짜순(같은 날은 미디어 → 단계 순). 같은 날·같은 미디어는 첫 줄에만 적는다.
- 변경 사항 색: OFF·감액·삭제 = 빨강, ON·증액·생성·추가 = 초록, 그 밖(이름·입찰·타겟팅·일정·설정 변경) = 회색.
- 변경 이력을 받지 않았으면 `변경 이력 데이터 준비 중`, 받았는데 기간 안에 없으면 `변경 이력 없음`.
- 엑셀 History 시트에 같은 줄이 들어간다(예시 양식의 History 시트 자리 — By Date 다음, Mix 앞).

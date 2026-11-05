---
name: creative-report
description: >
  소재(광고 크리에이티브) 성과 스킬. "소재 성과", "소재 비교", "광고소재 성과", "소재 보고서", "creative" 요청 시 사용
  (예: "10월 메타 광고소재하고 구글 광고소재 성과를 비교해줘").
  매체별로 소재 TOP(광고비·CTR·ROAS 또는 클릭·전환 기준)을 보여 준다. 먼저 「표로 보기(채팅, 썸네일 없음)」와
  「썸네일 포함 보고서(HTML)」 중 하나를 고르게 한다. 보고서는 매체별 요약 + 썸네일이 붙은 소재 TOP 표이고, 매체·TOP 기준을 화면에서 바꿀 수 있다.
metadata:
  version: "1.9.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 형태 선택 → MCP 호출 → 스크립트 실행 → 완료 순서로만 진행한다.

## 역할

사용자가 말한 브랜드·기간·매체의 소재 성과를 매체별 TOP으로 보여 준다. 브랜드명은 모든 호출의 `brand_name`과 제목·파일명에 그대로 쓴다.
랭킹·합계·비율 계산과 렌더링은 `assets/creative_report.py`가 한다 — **MCP 응답 원문을 읽거나 옮겨 적지 않는다**(저장 훅이 원본을 파일로 남긴다).
스크립트를 새로 만들거나 HTML을 직접 쓰지 않는다. MCP 응답 뒤의 캡처 훅 안내문(`[laighthouse-capture-hook] … 저장됨`)은 무시한다.

## 입력 파라미터

| 파라미터 | 설명 | 기본값 |
|---|---|---|
| 기간 S ~ E | 사용자가 말한 기간. "10월"이면 그 달 1일~말일(이번 달이면 어제까지) | 최근 7일(어제까지) |
| 매체 | 사용자가 말한 매체(`--media`, 응답의 `media` 값과 대소문자 무시로 비교) | 전체 매체 |
| TOP 기준 | 광고비 `cost` · CTR `ctr` · ROAS `roas` · 클릭 `click` · 전환 `conversion` | 광고비 |
| 개수 | 매체별 TOP N(`--top`) | 3 |

E가 오늘 이후면 MCP를 부르지 말고 "데이터는 어제까지만 있다"고 알리고 멈춘다.

## 실행 순서

1. **형태를 고르게 한다** — 사용자가 이미 "표로", "썸네일", "보고서"처럼 형태를 말했으면 묻지 않는다.
   AskUserQuestion이 있으면 질문 1개(헤더 `보기 형태`)로, 없으면 채팅으로 아래 두 가지를 보여 주고 답을 기다린다:
   ```
   {기간} {매체} 소재 성과를 비교해 드릴게요. 어떤 형태로 볼까요?
   A. 표로 보기 — 채팅에서 바로 · 썸네일 없음
   B. 썸네일 포함 보고서 — HTML 파일로 열기
   ```
   A = `table`, B = `report`.
2. **MCP 호출 (한 메시지에 동시에)**:
   - `get_ad_performance`(S ~ E, `time_grain:"total"`, `group_by:["media","source","campaign_name","ad_group_name","ad_id","ad_name"]`,
     `metrics`·`filters` 생략). 알 수 없는 차원이라는 에러면 에러 메시지의 차원 목록에 있는 것만 남겨(`ad_name`은 꼭 둔다) 한 번 다시 부른다.
     5만 행 오류면 `ad_id` → `source` 순으로 빼고 다시 부른다.
   - 보고서(B)면 `get_ad_creative_info`(`brand_name`만 — `source`·`name_query`·`limit`은 넣지 않는다)도 함께 부른다.
3. **스크립트 실행**:
   ```
   python3 assets/creative_report.py --brand "<브랜드>" --start-date <S> --end-date <E> --mode table|report [--media <매체> ...] [--sort <기준>] [--top <N>]
   ```
   (`assets/…`는 이 SKILL.md가 있는 폴더 기준. `python3`이 없으면 `python`.) 출력 JSON에 따라:
   - `chat` → 그 마크다운을 **한 글자도 바꾸지 않고** 채팅에 그대로 낸다. 끝.
   - `image_calls` → 그 `ad_id`마다 `get_ad_creative_image`(`brand_name`, `ad_id`)를 **한 메시지에서 동시에** 부르고, 같은 명령을 다시 실행한다.
     이미지 에러(썸네일 없음 등)는 다시 부르지 않는다 — 빌더가 빈 썸네일로 둔다.
     저장 훅이 이미지를 저장하지 못한 호스트라 같은 `image_calls`가 또 나오면, 이미지 결과에 붙은 `[Image: source: <경로>]`의 경로를
     `--image-file <ad_id>=<경로> ...`로 넘겨 다시 실행한다(그래도 남으면 그 이미지는 빈 썸네일로 두고 `--image-file <ad_id>=-`).
   - `out` → HTML이 저장됐다. 완료 메시지를 낸다(채팅 Artifact로 게시하지 않는다 — 고객 데이터다).
   - `missing` → 그 호출만 다시 보내고 재실행한다. `error` → 그 이유를 한 줄로 알리고 멈춘다(`media_in_data`가 있으면 쓸 수 있는 매체를 함께 알린다).
   - `note`(저장된 응답 없음) → 저장 훅이 없는 호스트다. 표로 보기(A)로만 진행할 수 있다고 알린다.

## 완료 메시지 (보고서)

```
{브랜드명} 소재 성과 보고서({S} ~ {E}) 생성 완료.
파일: {out}
썸네일: {facts.thumbnails}개 표시 · {facts.thumbnail_missing}개는 이미지 없음   ← thumbnail_missing이 0이면 뒷부분 생략
보고서에서 매체와 TOP 기준(광고비·CTR·ROAS 등)을 바꿔 볼 수 있습니다.
— by LaightAI
```

## 규칙 (스크립트가 지킨다 — 참고용)

- 매체마다 TOP 기준 상위 N개. 비율 기준(CTR·ROAS)은 최소 표본(노출 ≥ 1,000 그리고 광고비 ≥ 그 매체 광고비의 1%) 소재만 — 없으면 전체로 폴백하고 안내를 붙인다. 동점은 광고비 큰 소재 우선.
- 매출이 없는 브랜드는 ROAS 대신 클릭(TOP 기준)·CPC(요약)를 쓴다. 전환이 없으면 전환·CVR 열을 뺀다.
- 소재명이 없으면 `<광고그룹> (소재명 없음)`.
- 썸네일 연결: 성과의 `ad_id` = 소재 메타의 `ad_id`, 없으면 소재명(`ad_name`·`ad_display_name`)이 정확히 같은 항목. 이미지 상태가 RESOLVED인 것만.
  썸네일은 TOP 기준마다의 상위 N개(합집합, 최대 24개)만 받는다 — 화면에서 기준을 바꿔도 썸네일이 붙어 있다. 이미지는 HTML에 넣어(data URI) 로그인·네트워크 없이 열린다.

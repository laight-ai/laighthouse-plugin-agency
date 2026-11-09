# laighthouse-plugin-agency

대행사 양식 보고서를 라이트하우스 MCP 데이터로 만드는 Claude 플러그인 마켓플레이스입니다.

## 설치

```
/plugin install laighthouse-agency --marketplace laight-ai/laighthouse-plugin-agency
```

이전 버전 Claude Code에서는 두 단계로 설치합니다.

```
/plugin marketplace add laight-ai/laighthouse-plugin-agency
/plugin install laighthouse-agency@laighthouse-agency
```

## 플러그인

| 플러그인 | 스킬 | 설명 |
|---|---|---|
| `laighthouse-agency` | `overall-summary` | 종합 리포트(HTML + 엑셀) — 시작일(기본: 전월 1일)부터 어제까지 |
| | `overall-summary-comment` · `-total` · `-tables` · `-history` · `-mix` | 종합 리포트의 섹션 하나만(Comment · Summary · 세부 표 · 캠페인 변경 이력 · Mix) |
| | `daily-report` | Daily 보고서(HTML) — 기준일 vs 전일·전주 동요일 |
| | `weekly-report` | Weekly 보고서(HTML) — 이번주 vs 전주, 월 누적 진척도 |
| | `monthly-report` | Monthly 보고서(HTML) — 대상 월 vs 전월, 예산·목표 달성 |
| | `naver-search` | 외부 요인: 브랜드(자사·경쟁) 네이버 추정 검색수 비교(날짜 범위) |
| | `naver-news` | 외부 요인: 브랜드 네이버 뉴스 기사 수 비교 + 자사 주요 기사 4건 |
| | `naver-blog` | 외부 요인: 브랜드 네이버 블로그 글 수(제목 일치) 비교 + 자사 주요 글 4건 |
| | `weather-impact` | 외부 요인: 서울 일별 기온·강수·불쾌지수, 광고 클릭이 있으면 겹치기 |
| | `media-mix-result` | 월간 미디어믹스 결과(HTML) — 웹 결과 화면과 같은 모양(요약 수치·매체별 요약·일별 매체 배분·진단), 조건 확인 후 새로 실행도 가능 |

자세한 내용은 [plugins/laighthouse-agency/README.md](plugins/laighthouse-agency/README.md)를 보세요.

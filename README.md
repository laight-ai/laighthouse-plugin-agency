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

자세한 내용은 [plugins/laighthouse-agency/README.md](plugins/laighthouse-agency/README.md)를 보세요.

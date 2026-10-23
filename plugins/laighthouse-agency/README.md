# laighthouse-agency

라이트하우스 MCP 연동 데이터를 대행사 양식 보고서(HTML)로 렌더링하는 Claude 플러그인입니다.

## 설치

```
/plugin install laighthouse-agency --marketplace laight-ai/laighthouse-plugin-agency
```

## 컴포넌트

| 유형 | 이름 | 설명 |
|------|------|------|
| MCP | laighthouse | `https://app.laight.ai/api/mcp` 연동 |
| 훅 | capture_ad_performance | `get_ad_performance`의 큰 응답을 파일로 저장하고 경로만 모델에 보여 준다(재타이핑 방지) |
| 스킬 | tbwa-report | TBWA 보고서(HTML) 렌더링 |

## 사용법

> "breezm TBWA 보고서 만들어줘" → `tbwa-report`
> "breezm TBWA 보고서 7월 15일부터" → 시작일 지정(기본: 전월 1일, 366일까지)

### TBWA 보고서 구성

1. **Daily Comment · Weekly Comment** — 전일 대비 급감 광고그룹, 소진·효율 관점 요약(빌더가 규칙으로 작성)
2. **Total Summary · Monthly Summary** — 미디어 → 디멘전 계층, 예산·소진율·진행율 + 목표 영역(e.* 목표·달성률)
3. **월·미디어 필터 + Product · Target · Placement · Weekly · Daily 표**
   - Placement는 브랜드가 노출 위치 차원(`placement` 등)을 제공할 때만 나온다.
4. **Mix** — 월 예산·CPM·CPC·VTR을 입력해 예상 노출·클릭·조회를 보는 계획표(입력값은 브라우저에 저장)

모든 표: 디멘전·지표 설정(선택·순서), ▼/▶ 접기와 `펼침` 단계 버튼, 엑셀로 복사(시트 아이콘·Ctrl+C), 오른쪽 목차.

### 브랜드 비종속 동작

- 실행 시작에 차원 목록과 지표 키를 디스커버리한다(`assets/discover.py`). 브랜드가 제공하지 않는 차원(상품·노출 위치 등)은
  묻지 않고 보고서에서 조용히 빠진다.
- 예산·목표는 `get_target_progress_v2`(전체·매체·캠페인 단위)에서 읽는다. 목표가 없으면 빈칸이다.
- 렌더링 부품은 공용 킷 `shared/assets/report_kit.*`와 스킬의 `assets/tbwa_report.js`에 있다.

## MCP 서버

- **이름**: laighthouse
- **타입**: HTTP (Streamable HTTP transport)
- **URL**: `https://app.laight.ai/api/mcp`
- **인증**: oauth2.1

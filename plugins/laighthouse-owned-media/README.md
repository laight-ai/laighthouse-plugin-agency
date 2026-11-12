# laighthouse-owned-media

라이트하우스 **자사 매체(소셜 미디어 오가닉)** 데이터를 MCP로 조회하는 플러그인입니다. 브랜드가 연결한 자사 매체 계정의 일별 오가닉 지표와 수집 원자료를 채팅에 표로 보여 줍니다. HTML 보고서는 만들지 않습니다(보고서 skill은 추후).

> **지금은 dev 환경을 가리킵니다.** `.mcp.json`이 `https://dev-app.laight.ai/api/mcp`를 가리키며, 데이터도 dev 데이터입니다. 운영 배포 뒤 URL을 운영(`https://app.laight.ai/api/mcp`)으로 바꿔 마켓플레이스에 등록할 예정이라 아직 `marketplace.json`에는 넣지 않았습니다.

## 설치(내부 개발자용)

```
claude --plugin-dir <이 저장소 경로>/plugins/laighthouse-owned-media
```

처음 도구를 부를 때 dev 계정으로 OAuth 로그인합니다.

**운영 MCP 플러그인과 동시에 켜지 마세요.** 서버 이름이 `laighthouse`인 다른 플러그인(예: `laighthouse-agency`)은 `get_brand_list` 같은 같은 이름의 도구를 운영 데이터로 제공합니다. skill은 이 플러그인 서버의 도구(`mcp__plugin_laighthouse-owned-media_laighthouse-dev__*`)만 부르도록 적혀 있지만, 확실히 하려면 `/plugin`에서 그런 플러그인을 잠시 끈 세션에서 쓰세요. 끄는 설정은 다른 세션에도 적용되니 끝나면 다시 켭니다.

## 구성

```
laighthouse-owned-media/
├── .claude-plugin/plugin.json
├── .mcp.json                       # MCP 서버 laighthouse-dev → dev
└── skills/
    └── owned-media-data/SKILL.md   # 조회 skill(일별 지표 + 원자료 스트림)
```

## 쓰는 MCP 도구(report-backend)

| 도구 | 내용 |
|---|---|
| `get_owned_media_insights(brand_name, media, start_date, end_date)` | 자사 매체의 일별 오가닉 지표. 브랜드가 게시한 지표를 하루 한 값씩(팔로워 총수 같은 누적값은 보통 원자료 스트림에서 봄) |
| `get_brand_list()` | 브랜드 이름 확인(이름이 정확히 맞지 않을 때) |
| `get_owned_media_raw(brand_name, media, stream, start_date, end_date, offset, limit)` | 수집 원자료 스트림을 수집한 그대로(모든 열). 프로필, 시간대별 활동, 오디언스 분포, 게시물별 누적 지표 |

## 매체 추가

지원 매체는 서버 도구의 `media` 값으로, 지표는 응답으로 정해집니다. skill의 설명(description)에 적힌 매체 이름과, 원자료 열의 의미(날짜 기준·게시 시각 열 등)가 다른 매체라면 skill의 "보여 주는 방식" 절을 함께 고칩니다.

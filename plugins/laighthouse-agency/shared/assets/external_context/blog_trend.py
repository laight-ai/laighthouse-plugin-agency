"""블로그 언급량 집계 — naver-blog skill의 소스.

저장 훅 응답(`responses.BuzzData`, kind=blog)을 읽어 브랜드별 언급량과 급증일
글을 JSON으로 낸다. 브랜드 대표 검색어·고유 링크 집계·집계 불완전·급증 판정은 `buzz.py`, 기간
통계는 `trend_core.py` docstring을 따른다.

블로그 규칙
- 건수 = 제목 일치 글: 브랜드 검색어 중 하나라도 제목에 띄어쓰기까지 그대로 있는 글의 고유 링크 수.
  비교는 태그·따옴표를 지우고 연속 공백을 한 칸으로, 소문자로 한다. 블로그 검색은 합성어를 쪼개고
  따옴표를 무시해 제목·요약 일치만으로는 호텔 후기 같은 부수 언급이 섞이기 때문이다.
- 급증 = 제목 일치가 같은 요일 유형 기준선의 2배 이상이고 10건 이상(가설값).
- 급증일 글 = 그날 제목 일치 글에서 최신순, 같은 블로거는 1건만.

JSON은 `buzz.build`와 같고 글에 `blogger`가 더해진다.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import buzz

KIND = "blog"
SPIKE_RATIO, SPIKE_MIN = 2.0, 10
FOOTNOTES = [
    "블로그 검색은 합성어를 쪼개고 따옴표를 무시하므로, 건수는 브랜드 검색어가 제목에 그대로 있는 "
    "글의 고유 건수이며 썸트렌드 언급량과는 비교하지 않습니다.",
    "'집계 불완전' 표시가 있는 날은 1,000건 한도에 걸려 전부 받지 못한 날이며 합산에서 "
    "제외했습니다.",
]


_QUOTES = str.maketrans({c: " " for c in "\"'‘’“”`"})


@lru_cache(maxsize=65536)
def normalize(text: str) -> str:
    """수집기의 snippet_mentions와 같은 정규화(따옴표 제거, 연속 공백 한 칸, 소문자) + 태그 제거."""
    return " ".join(buzz.clean_title(text).translate(_QUOTES).split()).lower()


def title_match(title: str | None, queries: list[str]) -> bool:
    """브랜드 검색어 중 하나라도 제목에 띄어쓰기까지 그대로(정규화 후) 들어 있는지."""
    t = normalize(title or "")
    return any((q := normalize(query)) and q in t for query in queries)


def pick_posts(docs: list[buzz.Doc], queries: list[str], limit: int) -> list[dict]:
    """급증일 글: 링크로 합친 뒤 제목 일치 우선 → 최신순, 같은 블로거는 1건만."""
    merged = buzz.merge_by_link(
        docs,
        lambda doc: {
            "title_match": title_match(doc.title, queries),
            "blogger": (doc.author or "").strip(),
        },
    )
    ranked = sorted(
        merged,
        key=lambda r: (r["title_match"], r["date"], r["published_at"], r["link"]),
        reverse=True,
    )
    out, seen = [], set()
    for r in ranked:
        if r["blogger"] and r["blogger"] in seen:
            continue
        seen.add(r["blogger"])
        out.append(
            {
                "title": r["title"],
                "link": r["link"],
                "date": r["date"].isoformat(),
                "duplicates": 1,
                "snippet_match": r["snippet_match"],
                "title_match": r["title_match"],
                "blogger": r["blogger"] or None,
            }
        )
        if len(out) == limit:
            break
    return out


SPEC = buzz.BuzzSpec(
    kind=KIND,
    spike_ratio=SPIKE_RATIO,
    spike_min=SPIKE_MIN,
    count_rule="제목 일치 글 고유 링크 수",
    footnotes=FOOTNOTES,
    counted=lambda doc, queries: title_match(doc.title, queries),
    spike_doc=lambda doc, queries: title_match(doc.title, queries),
    pick=pick_posts,
)


def build(tenant: dict, target: date, db) -> dict:
    return buzz.build(tenant, target, db, SPEC)

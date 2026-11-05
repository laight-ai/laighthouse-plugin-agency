"""뉴스 언급량 집계 — naver-news skill의 소스.

조회 객체(kind=news)를 읽어 브랜드별 언급량과 급증일
기사를 JSON으로 낸다. 브랜드 대표 검색어·고유 링크 집계·집계 불완전·급증 판정은 `buzz.py`, 기간
통계는 `trend_core.py` docstring을 따른다.

뉴스 규칙
- 건수 = 제목·요약에 검색어가 띄어쓰기까지 그대로 들어 있는 기사(`snippet_match`)만. 한 단어
  검색어나 2026-10-30 이전 수집분은 뉴스 검색이 복합어를 쪼개 무관한 기사가 섞이기 때문이다.
- 급증 = 같은 요일 유형 기준선의 3배 이상이고 5건 이상.
- 급증일 기사 = 그날 브랜드 검색어에 걸린 모든 기사에서 snippet_match 우선 → 같은 제목 묶음 크기
  내림차순 → 최신순. 묶음 키는 제목에서 `[…]` 머리말·기호·공백을 뺀 전체 문자열이다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

import buzz

KIND = "news"
SPIKE_RATIO, SPIKE_MIN = 3.0, 5
FOOTNOTES = [
    "뉴스 건수는 네이버 뉴스 색인 기준이며 제목·요약에 검색어가 그대로 있는 기사만 센 값입니다. "
    "브랜드 건수는 브랜드 검색어들에 걸린 기사의 고유 건수입니다.",
    "'집계 불완전' 표시가 있는 날은 1,000건 한도에 걸려 전부 받지 못한 날이며 합산에서 "
    "제외했습니다.",
]
_HEAD = re.compile(r"^(\s*[\[(【][^\]\)】]*[\])】]\s*)+")
_NONWORD = re.compile(r"[^0-9a-z가-힣]+")


def title_key(title: str) -> str:
    """제목 묶음 키: `[브리프]` 같은 머리말을 떼고 기호·공백을 뺀 전체 문자열.

    앞 글자만 잘라 비교하지 않는다(서로 다른 기사가 합쳐지지 않도록).
    """
    return _NONWORD.sub("", _HEAD.sub("", buzz.clean_title(title)).lower())


def cluster_articles(docs: list[buzz.Doc], limit: int) -> list[dict]:
    """같은 기사(링크)와 같은 제목 묶음을 합쳐 대표 기사만 남긴다.

    순서: snippet_match 묶음 우선 → 묶음 크기 내림차순 → 최신순.
    """
    clusters: dict[str, list[dict]] = defaultdict(list)
    for rec in buzz.merge_by_link(docs):
        clusters[title_key(rec["title"]) or rec["link"]].append(rec)

    def recency(rec: dict) -> tuple:
        return rec["published_at"], rec["date"]

    out = []
    for members in clusters.values():
        members.sort(key=recency, reverse=True)
        out.append(
            members[0]
            | {
                "duplicates": len(members),
                "snippet_match": any(m["snippet_match"] for m in members),
            }
        )
    out.sort(key=lambda r: (r["snippet_match"], r["duplicates"], recency(r)), reverse=True)
    return [
        {
            "title": r["title"],
            "link": r["link"],
            "date": r["date"].isoformat(),
            "duplicates": r["duplicates"],
            "snippet_match": r["snippet_match"],
        }
        for r in out[:limit]
    ]


SPEC = buzz.BuzzSpec(
    kind=KIND,
    spike_ratio=SPIKE_RATIO,
    spike_min=SPIKE_MIN,
    count_rule="snippet_match 기사 고유 링크 수",
    footnotes=FOOTNOTES,
    counted=lambda doc, queries: doc.snippet_match,
    spike_doc=lambda doc, queries: True,
    pick=lambda docs, queries, limit: cluster_articles(docs, limit),
)


def build(tenant: dict, target: date, db) -> dict:
    return buzz.build(tenant, target, db, SPEC)

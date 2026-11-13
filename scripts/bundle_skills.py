#!/usr/bin/env python3
"""플러그인 공용 폴더(shared/)와 overall-summary를 각 스킬 폴더 안으로 복사해 스킬 폴더를 자기완결로 만든다.

왜: Claude 데스크톱 Cowork는 스킬 폴더를 하나씩 따로 올린다(`/mnt/skills/plugins/laighthouse-agency:<스킬>`).
플러그인 루트의 `shared/`는 어디에도 올라가지 않고, 옆 스킬도 다른 이름으로 올라간다. 그래서 스크립트가 찾는
`<스킬>/../../../shared/assets`나 문서의 `../overall-summary/`는 Cowork에서 없는 경로다. 스크립트는
`<스킬>/shared/assets`(스킬 폴더 안 사본)를 먼저 찾으므로, 사본을 넣어 두면 Cowork와 Claude Code 모두에서 동작한다.

단일 소스는 플러그인 루트의 `shared/`와 `skills/overall-summary/`다. 이 스크립트가 만드는 사본
(`skills/<스킬>/shared/`, overall-summary-* 하위 스킬의 `assets/`·`references/`)은 손으로 고치지 않는다.
원본을 고친 뒤 다시 실행해 사본까지 같은 커밋에 넣는다:

    python3 scripts/bundle_skills.py           # 사본을 다시 만든다
    python3 scripts/bundle_skills.py --check   # 사본이 원본과 다르거나 빠지거나 남는 파일이 있으면 목록을 내고 1로 끝난다

스킬마다 필요한 파일만 아래 목록대로 넣는다. 스크립트가 새 공용 파일을 쓰게 되면 목록에 더한다.
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "laighthouse-agency")
SHARED = os.path.join(PLUGIN, "shared")
SKILLS = os.path.join(PLUGIN, "skills")
OVERALL = os.path.join(SKILLS, "overall-summary")

# shared/ 기준 경로
KIT = ("assets/report_kit.py", "assets/report_kit.css", "assets/saved_responses.py")
REPORT_HTML = ("assets/report_kit.js", "assets/chart.umd.min.js")   # report_kit.build_html이 인라인한다
FEES = ("assets/fees.py", "assets/fees_legacy.py")
FEE_VIEWS = ("assets/fee_views.py",)
REFS = ("references/mcp-tools.md", "references/pivot-table.md")
EXTERNAL_CONTEXT = tuple(f"assets/external_context/{n}" for n in (
    "blog_trend.py", "buzz.py", "chart.umd.min.js", "check_citations.py", "news_trend.py", "page.py",
    "range_report.py", "responses.py", "saved.py", "search_aggregate.py", "search_db.py", "trend_config.py",
    "trend_core.py", "trend_report.py", "weather_trend.py"))
EXTERNAL = EXTERNAL_CONTEXT + ("references/mcp-tools.md",)
OVERALL_SHARED = KIT + FEES + REFS

SHARED_FILES = {
    "daily-report": KIT + REPORT_HTML + REFS,
    "weekly-report": KIT + REPORT_HTML + FEES + FEE_VIEWS + REFS,
    "monthly-report": KIT + REPORT_HTML + FEES + FEE_VIEWS + REFS,
    "overall-summary": OVERALL_SHARED,
    "media-mix-result": ("assets/saved_responses.py", "assets/chart.umd.min.js"),
    "naver-search": EXTERNAL,
    "naver-news": EXTERNAL,
    "naver-blog": EXTERNAL,
    "weather-impact": EXTERNAL,
    "skill-catalog": (),
}
# overall-summary-* 하위 스킬: overall-summary의 스크립트·문서를 자기 폴더로 넣는다
OVERALL_SUBSKILLS = ("overall-summary-comment", "overall-summary-history", "overall-summary-mix",
                     "overall-summary-tables", "overall-summary-total")
for _name in OVERALL_SUBSKILLS:
    SHARED_FILES[_name] = OVERALL_SHARED
OVERALL_ASSETS = ("budget_targets.py", "build_report.py", "campaign_history.py", "discover.py", "overall_summary.js",
                  "overall_summary_xlsx.py", "prepare.py", "report-template.html")


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _listing(path):
    """__pycache__·.pyc를 뺀 파일 목록(path 기준 상대 경로)."""
    out = set()
    for dirpath, dirnames, files in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in files:
            if not f.endswith(".pyc"):
                out.add(os.path.relpath(os.path.join(dirpath, f), path).replace(os.sep, "/"))
    return out


def _overall_docs():
    return sorted(n for n in os.listdir(OVERALL) if n.startswith("overall-summary-section-") and n.endswith(".md"))


def expected(skill):
    """스킬 폴더 기준 상대 경로 → 내용(bytes). 이 스크립트가 관리하는 파일 전부."""
    files = {f"shared/{rel}": _read(os.path.join(SHARED, rel)) for rel in SHARED_FILES[skill]}
    if skill in OVERALL_SUBSKILLS:
        for n in OVERALL_ASSETS:
            files[f"assets/{n}"] = _read(os.path.join(OVERALL, "assets", n))
        docs = _overall_docs()
        for n in docs:
            files[f"references/{n}"] = _read(os.path.join(OVERALL, n))
        # 본 스킬 문서 안의 섹션 문서 이름은 references/ 아래로(다른 경로는 이미 스킬 폴더 기준이다)
        main = _read(os.path.join(OVERALL, "SKILL.md")).decode("utf-8")
        files["references/overall-summary.md"] = main.replace(
            "`overall-summary-section-", "`references/overall-summary-section-").encode("utf-8")
    return files


def managed_dirs(skill):
    """사본만 두는 폴더 — 여기 있는 파일은 모두 이 스크립트가 만든다."""
    return ("shared", "assets", "references") if skill in OVERALL_SUBSKILLS else ("shared",)


def unlisted_sources():
    """목록에 없는 원본 파일 — 새 파일이 사본에서 조용히 빠지지 않게 한다."""
    gaps = []
    ec = os.path.join(SHARED, "assets", "external_context")
    gaps += [f"shared/assets/external_context/{n}" for n in sorted(_listing(ec))
             if f"assets/external_context/{n}" not in EXTERNAL_CONTEXT]
    gaps += [f"skills/overall-summary/assets/{n}" for n in sorted(_listing(os.path.join(OVERALL, "assets")))
             if n not in OVERALL_ASSETS]
    return gaps


def skills():
    names = sorted(n for n in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, n, "SKILL.md")))
    unknown = [n for n in names if n not in SHARED_FILES]
    if unknown:
        raise SystemExit(f"bundle_skills.py의 SHARED_FILES에 없는 스킬: {unknown} — 필요한 공용 파일을 목록에 더한다")
    return names


def drift():
    problems = [f"목록에 없는 원본: {p}" for p in unlisted_sources()]
    for skill in skills():
        base = os.path.join(SKILLS, skill)
        want = expected(skill)
        have = set()
        for d in managed_dirs(skill):
            have |= {f"{d}/{rel}" for rel in _listing(os.path.join(base, d))}
        for rel in sorted(set(want) - have):
            problems.append(f"빠짐: skills/{skill}/{rel}")
        for rel in sorted(have - set(want)):
            problems.append(f"남는 파일: skills/{skill}/{rel}")
        for rel in sorted(set(want) & have):
            if _read(os.path.join(base, rel)) != want[rel]:
                problems.append(f"원본과 다름: skills/{skill}/{rel}")
    return problems


def write():
    gaps = unlisted_sources()
    if gaps:
        raise SystemExit("목록에 없는 원본 파일이 있다 — bundle_skills.py 목록에 더한다:\n  " + "\n  ".join(gaps))
    for skill in skills():
        base = os.path.join(SKILLS, skill)
        for d in managed_dirs(skill):
            shutil.rmtree(os.path.join(base, d), ignore_errors=True)
        files = expected(skill)
        for rel, data in files.items():
            path = os.path.join(base, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        print(f"{skill}: {len(files)}개")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="사본이 원본과 같은지만 확인한다(고치지 않는다)")
    if ap.parse_args().check:
        problems = drift()
        if problems:
            print("스킬 폴더 사본이 원본과 다르다 — python3 scripts/bundle_skills.py 를 실행해 다시 만든다:")
            print("\n".join(f"  {p}" for p in problems))
            sys.exit(1)
        print("ok")
    else:
        write()


if __name__ == "__main__":
    main()

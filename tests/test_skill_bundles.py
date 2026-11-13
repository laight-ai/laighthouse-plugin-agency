#!/usr/bin/env python3
"""스킬 폴더 자기완결 검사(표준 라이브러리만). 성공하면 "ok".

Claude 데스크톱 Cowork는 스킬 폴더를 하나씩 따로 올린다(`/mnt/skills/plugins/laighthouse-agency:<스킬>`).
플러그인 루트의 shared/와 옆 스킬은 없다. 그래서 스킬 폴더 안에 공용 파일 사본을 둔다(scripts/bundle_skills.py).

- 사본이 원본과 같다(`bundle_skills.py --check`). 원본을 고치고 사본을 다시 만들지 않으면 여기서 실패한다.
- Cowork 흉내: 스킬 폴더만 임시 폴더로 복사해 스크립트를 돌리면 공용 파일을 모두 스킬 폴더 안에서 찾는다.
- 스킬 폴더 안 글이 `../`로 폴더 밖을 가리키지 않는다.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "plugins", "laighthouse-agency")
SKILLS = os.path.join(PLUGIN, "skills")
BUNDLER = os.path.join(ROOT, "scripts", "bundle_skills.py")
RUN_BUNDLER = "python3 scripts/bundle_skills.py 를 실행해 사본을 다시 만들고 함께 커밋한다"

# 스킬 폴더 하나 안에서 도는 검사. 인자: 스킬 폴더. 출력: 문제 목록(JSON).
PROBE = r'''
import ast, importlib, importlib.util, json, os, runpy, sys, sysconfig
skill = os.path.realpath(sys.argv[1])
assets = os.path.join(skill, "assets")
std = tuple(os.path.realpath(sysconfig.get_paths()[k]) for k in ("stdlib", "platstdlib"))
problems = []

def inside(path):
    return os.path.realpath(path).startswith(skill + os.sep)

scripts = sorted(n for n in os.listdir(assets) if n.endswith(".py")) if os.path.isdir(assets) else []
sources = {n: open(os.path.join(assets, n), encoding="utf-8").read() for n in scripts}
# 1) 공용 킷을 찾는 진입 스크립트를 실행한다(--help, 빈 stdin). 찾지 못하면 SystemExit(문구)로 끝난다.
results = {}
sys.stdout = sys.stderr = open(os.devnull, "w")
for n in scripts:
    if '"shared", "assets"' not in sources[n]:
        continue
    path = os.path.join(assets, n)
    sys.argv = [path, "--help"]
    sys.path.insert(0, assets)
    try:
        results[n] = runpy.run_path(path, run_name="cowork_probe")
    except SystemExit as e:
        if isinstance(e.code, str):
            problems.append(f"{n}: {e.code}")
    except ImportError as e:
        problems.append(f"{n}: {type(e).__name__}: {e}")
    except Exception:
        pass   # 입력이 없어서 난 오류 — import는 이미 끝났다(아래 2에서 다시 본다)
# 2) assets/*.py가 import 하는 모듈은 모두 스킬 폴더 안 파일이거나 표준 라이브러리다.
names = set()
for n in scripts:
    for node in ast.walk(ast.parse(sources[n])):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
for name in sorted(names):
    if name in sys.builtin_module_names or name == "__future__":
        continue
    spec = importlib.util.find_spec(name)
    if spec is None:
        problems.append(f"import {name}: 찾을 수 없다")
    elif spec.origin and inside(spec.origin):
        try:
            importlib.import_module(name)
        except BaseException as e:
            problems.append(f"import {name}: {type(e).__name__}: {e}")
    elif not (spec.origin in ("built-in", "frozen") or os.path.realpath(spec.origin).startswith(std)):
        problems.append(f"import {name}: 스킬 폴더 밖 {spec.origin}")
for mod in list(sys.modules.values()):
    f = getattr(mod, "__file__", None)
    if f and not inside(f) and not os.path.realpath(f).startswith(std):
        problems.append(f"스킬 폴더 밖 모듈: {mod.__name__} ({f})")
# 3) 렌더링 때 읽는 파일(킷 CSS·JS, Chart.js)도 스킬 폴더 안에서 읽힌다.
def read(label, fn):
    try:
        fn()
    except BaseException as e:
        problems.append(f"{label}: {type(e).__name__}: {e}")
kit = sys.modules.get("report_kit")
if kit:
    if not inside(kit.KIT_DIR):
        problems.append(f"report_kit.KIT_DIR가 스킬 폴더 밖: {kit.KIT_DIR}")
    template = os.path.join(assets, "report-template.html")
    text = open(template, encoding="utf-8").read() if os.path.exists(template) else ""
    if "__REPORT_KIT_CSS__" in text:
        read("report_kit.css", lambda: kit._read_first(kit.KIT_DIR, ["report_kit.css"]))
    if "__CHART_JS_INLINE__" in text:   # report_kit.build_html
        read("report_kit.js", lambda: kit._read_first(kit.KIT_DIR, ["report_kit_js.txt", "report_kit.js"]))
        read("Chart.js", lambda: kit.chart_js(assets))
page = sys.modules.get("page")
if page:
    read("Chart.js(external_context)", lambda: open(os.path.join(page.HERE, "chart.umd.min.js")).close())
for n, g in results.items():
    if "SHARED_DIRS" in g and "read_first" in g:   # media-mix-result
        read(f"{n} Chart.js", lambda: g["read_first"]([g["ASSETS_DIR"], *g["SHARED_DIRS"]],
                                                       ["chart.umd.min.txt", "chart.umd.min.js"]))
sys.__stdout__.write(json.dumps(problems, ensure_ascii=False))
'''


def skill_names():
    return sorted(n for n in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, n, "SKILL.md")))


def mount_alone(tmp, skill):
    """Cowork처럼 스킬 폴더 하나만 올린다 — 둘레에 플러그인 루트가 없다."""
    dst = os.path.join(tmp, "mnt", "skills", "plugins", f"laighthouse-agency:{skill}")
    shutil.copytree(os.path.join(SKILLS, skill), dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def probe(skill_dir):
    # -I: 현재 폴더·PYTHONPATH·사용자 site를 보지 않는다, -S: site-packages도 보지 않는다
    p = subprocess.run([sys.executable, "-I", "-S", "-c", PROBE, skill_dir], cwd=skill_dir,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, f"{skill_dir}: 검사 실행 실패\n{p.stderr}"
    return json.loads(p.stdout)


def escaping_refs(skill_dir):
    """`../`로 스킬 폴더 밖을 가리키는 글. 문서(.md)는 스킬 폴더 기준, 그 밖의 파일은 파일 위치 기준으로 푼다."""
    out = []
    root = os.path.realpath(skill_dir)
    for dirpath, _, files in os.walk(skill_dir):
        for f in files:
            if not f.endswith((".md", ".py", ".js", ".html", ".css", ".json", ".txt")):
                continue
            path = os.path.join(dirpath, f)
            base = skill_dir if f.endswith(".md") else dirpath
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    for m in re.finditer(r"(?:\.\./)+[^\s`'\")\]]*", line):
                        target = os.path.realpath(os.path.join(base, m.group(0)))
                        if not (target + os.sep).startswith(root + os.sep):
                            out.append(f"{os.path.relpath(path, skill_dir)}:{i}: {m.group(0)}")
    return out


def missing_doc_refs(skill_dir):
    """스킬 문서(SKILL.md·섹션 문서·references/)가 `shared/…`·`assets/…`·`references/…`로 가리키는 파일이 스킬 폴더에 없다.
    shared/ 안 문서(플러그인 공용 문서의 사본)는 보지 않는다 — 개발자용 구현 위치 안내가 섞여 있다."""
    out = []
    for dirpath, _, files in os.walk(skill_dir):
        if os.path.relpath(dirpath, skill_dir).split(os.sep)[0] == "shared":
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(dirpath, f)
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    for m in re.finditer(r"`((?:shared|assets|references)/[^`\s…*]*)`", line):
                        if not os.path.exists(os.path.join(skill_dir, m.group(1))):
                            out.append(f"{os.path.relpath(path, skill_dir)}:{i}: {m.group(1)}")
    return out


def test_bundled_copies_match_their_sources():
    p = subprocess.run([sys.executable, BUNDLER, "--check"], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, f"스킬 폴더 사본이 원본과 다르다 — {RUN_BUNDLER}.\n{p.stdout}{p.stderr}"


def test_check_reports_a_copy_that_no_longer_matches_its_source():
    """--check 자체 검사: 임시 사본에서 원본 하나를 고치면 그 원본을 쓰는 사본이 '원본과 다름'으로 나온다."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(os.path.join(ROOT, "plugins"), os.path.join(tmp, "plugins"))
        shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(tmp, "scripts"))
        with open(os.path.join(tmp, "plugins", "laighthouse-agency", "shared", "assets", "fees.py"), "a") as f:
            f.write("\n# 고친 줄\n")
        p = subprocess.run([sys.executable, os.path.join(tmp, "scripts", "bundle_skills.py"), "--check"],
                           capture_output=True, text=True)
        assert p.returncode == 1, p.stdout
        assert "원본과 다름: skills/weekly-report/shared/assets/fees.py" in p.stdout, p.stdout
        assert "skills/daily-report/" not in p.stdout, p.stdout   # daily-report는 fees.py를 쓰지 않는다
        assert "python3 scripts/bundle_skills.py" in p.stdout, p.stdout


def test_each_skill_works_when_mounted_alone():
    with tempfile.TemporaryDirectory() as tmp:
        failures = {}
        for skill in skill_names():
            d = mount_alone(tmp, skill)
            problems = (probe(d) + [f"폴더 밖 경로 {r}" for r in escaping_refs(d)]
                        + [f"없는 파일을 가리킨다 {r}" for r in missing_doc_refs(d)])
            if problems:
                failures[skill] = problems
        assert not failures, (f"스킬 폴더만으로는 동작하지 않는다 — {RUN_BUNDLER}(목록에 없는 파일이면 "
                              f"bundle_skills.py 목록에 더한다).\n" + json.dumps(failures, ensure_ascii=False, indent=1))


# 스킬마다 진입 스크립트 하나를 저장된 응답 없이 끝까지 돌린다 — 응답이 없을 때 내는 출력(note·missing)의 키.
DATE = ["--target-date", "2026-01-05"]
RANGE = ["--range", "2026-01-01~2026-01-05"]

ENTRY = {
    "daily-report": ("assets/prepare.py", DATE, "note"),
    "weekly-report": ("assets/prepare.py", DATE, "note"),
    "monthly-report": ("assets/prepare.py", ["--month", "2025-12"], "note"),
    "overall-summary": ("assets/prepare.py", DATE, "note"),
    **{f"overall-summary-{p}": ("assets/prepare.py", DATE + ["--part", p], "note")
       for p in ("comment", "history", "mix", "tables", "total")},
    "naver-search": ("assets/prepare.py", RANGE, "missing"),
    "naver-news": ("assets/prepare.py", RANGE, "missing"),
    "naver-blog": ("assets/prepare.py", RANGE, "missing"),
    "weather-impact": ("assets/prepare.py", RANGE, "missing"),
    "media-mix-result": ("assets/build_report.py", ["--job-id", "job"], "note"),
}


def run_entry(skill_dir, script, args, tmp):
    """폴더 이름이 `laighthouse-agency:<스킬>`인 채로 스크립트를 돌린다. 저장 훅 폴더(임시 폴더)는 비어 있다."""
    env = {**os.environ, "TMPDIR": tmp, "HOME": tmp}
    p = subprocess.run([sys.executable, "-I", "-S", script, "--brand", "코워크검사", *args], cwd=skill_dir, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def test_each_entry_script_runs_to_its_no_responses_output_when_mounted_alone():
    assert set(ENTRY) | {"skill-catalog"} == set(skill_names()), "새 스킬은 ENTRY에 진입 스크립트를 더한다"
    with tempfile.TemporaryDirectory() as tmp:
        for skill, (script, args, key) in sorted(ENTRY.items()):
            d = mount_alone(tmp, skill)
            work = tempfile.mkdtemp(dir=tmp)
            code, out, err = run_entry(d, script, args, work)
            assert code == 0 and key in json.loads(out), f"{skill}: {script} 실패\n{out}{err}"


def test_media_mix_result_renders_from_a_response_file_when_mounted_alone():
    with tempfile.TemporaryDirectory() as tmp:
        d = mount_alone(tmp, "media-mix-result")
        out = os.path.join(tmp, "mm.html")
        code, stdout, err = run_entry(d, "assets/build_report.py", [
            "--json", os.path.join(HERE, "fixtures", "media_mix", "job-even.json"), "--out", out], tmp)
        assert code == 0, stdout + err
        with open(out, encoding="utf-8") as f:
            html = f.read()
        assert "__CHART_JS__" not in html and "Chart.js v" in html, "Chart.js가 인라인되지 않았다"


def test_a_missing_copy_is_caught_when_mounted_alone():
    """위 검사가 실제로 잡는지: 사본 하나를 지우면 그 스킬이 실패한다."""
    cases = [
        ("media-mix-result", "shared/assets/saved_responses.py"),      # 공용 킷 찾기
        ("media-mix-result", "shared/assets/chart.umd.min.js"),         # 렌더링 때 읽는 파일
        ("daily-report", "shared/assets/report_kit.css"),
        ("weekly-report", "shared/assets/fee_views.py"),                # 진입 스크립트가 import 하는 모듈
        ("naver-search", "shared/assets/external_context/page.py"),
        ("weather-impact", "shared/assets/external_context/chart.umd.min.js"),
        ("overall-summary-mix", "assets/budget_targets.py"),             # 하위 스킬에 넣은 overall-summary 스크립트
    ]
    for skill, rel in cases:
        with tempfile.TemporaryDirectory() as tmp:
            d = mount_alone(tmp, skill)
            assert not probe(d), skill
            os.remove(os.path.join(d, rel))
            assert probe(d), f"{skill}/{rel}를 지워도 검사가 통과한다"


def test_a_reference_outside_the_skill_folder_or_to_a_missing_file_is_caught():
    with tempfile.TemporaryDirectory() as tmp:
        d = mount_alone(tmp, "overall-summary-mix")
        with open(os.path.join(d, "SKILL.md"), "a", encoding="utf-8") as f:
            f.write("\n`../overall-summary/SKILL.md`\n")
        n = sum(1 for _ in open(os.path.join(d, "SKILL.md"), encoding="utf-8"))
        assert escaping_refs(d) == [f"SKILL.md:{n}: ../overall-summary/SKILL.md"]
        os.remove(os.path.join(d, "references", "overall-summary-section-5-mix.md"))
        assert [r for r in missing_doc_refs(d) if r.startswith("SKILL.md:")] == [
            "SKILL.md:19: references/overall-summary-section-5-mix.md"], missing_doc_refs(d)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

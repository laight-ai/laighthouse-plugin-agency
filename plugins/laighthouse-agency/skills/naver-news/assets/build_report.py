#!/usr/bin/env python3
"""통합 JSON + 파트별 요약(JSON 배열) → HTML 보고서. 본체는 shared/assets/external_context/range_report.py.

사용법:
  python3 assets/build_report.py --json <prepare가 준 json> --summary '<SKILL.md 4단계 형식의 요약 JSON 배열>'(없으면 stdin)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "shared", "assets"),          # ChatGPT 번들
             os.path.join(HERE, "..", "..", "..", "shared", "assets")):  # 플러그인 루트
    if os.path.exists(os.path.join(cand, "external_context", "range_report.py")):
        sys.path[:0] = [os.path.normpath(os.path.join(cand, "external_context")), os.path.normpath(cand)]
        break
else:
    raise SystemExit("range_report.py를 찾을 수 없다 (shared/assets/external_context)")
import range_report  # noqa: E402

sys.exit(range_report.main("naver-news", ["build", *sys.argv[1:]]))

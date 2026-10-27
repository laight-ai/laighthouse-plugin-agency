#!/usr/bin/env python3
"""디스커버리 해석기 — 매체·상품 목록, 고정 7 역할 지표 키, 통화를 한 번에 정한다.

사용법 (저장 훅이 없는 호스트에서만 — 훅이 있으면 prepare.py가 같은 일을 한다):
  python3 assets/discover.py <s3(day, group_by ["media"]) 응답 파일 경로>   (또는 stdin으로 응답 원문)

출력(stdout JSON):
  media_list   매체 값(응답 순서)                 products     {매체: [상품 ...]}
  metric_keys  역할→실제 키 (cost/impression/click/ctr/views/cpm/cpv)
  metric_names 봉투 metrics 전체                  metric_units 봉투 metric_units
  currency     광고비 단위(없으면 "₩")
  missing      못 찾은 역할 → 사용자에게 한 번에 질문
"""
import io
import os
import sys

sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "shared", "assets"),           # zip 번들
             os.path.join(HERE, "..", "..", "..", "shared", "assets")):  # 개발 트리(src)
    if os.path.exists(os.path.join(cand, "report_kit.py")):
        sys.path.insert(0, os.path.normpath(cand))
        break
else:
    raise SystemExit("report_kit.py를 찾을 수 없다 (shared/assets)")
import report_kit  # noqa: E402

report_kit.discover_main(sys.stdin, sys.stdout)

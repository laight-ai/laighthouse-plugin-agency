#!/usr/bin/env python3
"""Executive Summary 작성 근거 출력기 — 빌더 입력(build.json)을 그대로 읽어 당월·전월 값과 변화를 짧게 출력한다.

사용법 (저장 훅이 없는 호스트에서만 — 훅이 있으면 prepare.py 출력의 digest가 같은 내용이다):
  python3 assets/digest.py <작업 폴더>/build.json
출력(stdout JSON): 당월·전월, 전체, 예산(월예산·소진율), 매체(광고비비중 포함)·매체-상품별
  {이름, 당월, 전월, 전월 대비} — 숫자는 화면 표와 같은 규칙으로 계산된 값이다. 응답에 없는 차원은 빠진다.
"""
import io
import json
import os
import sys

sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_report  # noqa: E402

json.dump(build_report.digest(build_report.kit.read_payload()), sys.stdout, ensure_ascii=False, indent=1)

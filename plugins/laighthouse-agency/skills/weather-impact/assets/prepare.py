#!/usr/bin/env python3
"""저장된 날씨(+광고 성과) 응답 → facts. 본체는 shared/assets/external_context/weather_trend.py.

사용법:
  python3 assets/prepare.py --brand <브랜드> --range <시작>~<끝>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "shared", "assets"),          # ChatGPT 번들
             os.path.join(HERE, "..", "..", "..", "shared", "assets")):  # 플러그인 루트
    if os.path.exists(os.path.join(cand, "external_context", "weather_trend.py")):
        sys.path[:0] = [os.path.normpath(os.path.join(cand, "external_context")), os.path.normpath(cand)]
        break
else:
    raise SystemExit("weather_trend.py를 찾을 수 없다 (shared/assets/external_context)")
import weather_trend  # noqa: E402

sys.exit(weather_trend.main(["prepare", *sys.argv[1:]]))

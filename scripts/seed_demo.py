#!/usr/bin/env python3
"""Create a repeatable public demo. Never calls Meta or copies credentials."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from showme.demo import DEMO_SCENARIOS, seed_demo
from showme.store import Store


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "state")
    parser.add_argument("--scenario", choices=DEMO_SCENARIOS, default="reception")
    args = parser.parse_args()
    url = seed_demo(Store(args.data_dir), ROOT / "public/demo/reception-setup", scenario=args.scenario)
    print("데모 준비 완료 (AI 연출 사진, API 호출 없음): " + url)

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
    parser.add_argument("--scenario", choices=DEMO_SCENARIOS)
    args = parser.parse_args()
    store = Store(args.data_dir)
    for scenario in ((args.scenario,) if args.scenario else ("storage-tags", "storage-tags-en")):
        url = seed_demo(store, ROOT / "public/demo/reception-setup", scenario=scenario)
        print(f"{scenario} demo ready (staged photo, no API calls): {url}")
